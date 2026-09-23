# -*- coding: utf-8 -*-
"""服务层：把登录 / 扫描 / 状态 / 提醒串起来。CLI 与网页控制台共用。"""
import datetime
import hashlib
import time

from ..cas import cas_login
from ..notify import dispatcher as disp
from ..notify.board import Board, BoardNotifier
from ..notify.desktop import DesktopNotifier
from ..notify.email import EmailNotifier
from ..notify.wechat import WeChatNotifier
from ..platform.http_client import PlatformSession, SessionExpired, Throttled
from ..platform.models import TZ
from ..security import credential_store as cs
from . import classfilter
from .scanner import scan as run_scan
from .state import FileLock, StateStore


def _tier_rank(rec: dict) -> int:
    """列表排序档位：24h 内未提交(1) → 未提交(2) → 已提交(3) → 已逾期(4)。"""
    left = rec.get("left_seconds")
    if not rec.get("unsubmitted"):
        return 3
    if left is None:
        return 2
    if left < 0:
        return 4
    if left <= 86400:
        return 1
    return 2


class Service:
    def __init__(self, settings, log):
        self.s = settings
        self.log = log
        self.state = StateStore(settings.state_path)
        self.board = Board(settings.p("data", "board_feed.jsonl"))
        self._ps: PlatformSession | None = None
        # 扫描信息持久化，否则控制台一重启顶部就显示"尚未扫描"，和数据对不上
        self.last_scan_info: dict = dict(self.state.data.get("last_scan") or {})

    # ---- 会话 ----
    def platform_session(self, allow_relogin: bool = True,
                         force_login: bool = False) -> PlatformSession:
        if self._ps is not None and not force_login:
            return self._ps
        sc = self.s.scan_cfg
        if not force_login:
            # force_login=True 时跳过 Cookie 复用（重登按钮用），
            # 旧 Cookie 仍保留在凭据库里，直到新登录成功才被覆盖
            cookies = cs.load_cookies()
            if cookies:
                sess = cas_login.cookies_to_session(cookies)
                if cas_login.session_alive(sess):
                    self.log.info("复用已保存会话")
                    self.state.note_login_ok()
                    self.state.save()
                    self._ps = self._mk_ps(sess)
                    return self._ps
            self.log.info("已保存会话失效")
        if not allow_relogin:
            raise SessionExpired("无可用会话")
        if self.state.login_locked():
            raise SessionExpired("账号处于锁定窗口内，本次跳过（避免加重锁定）")
        cred = cs.load_credentials()
        if not cred:
            raise SessionExpired("尚未保存凭据，请先运行 set-credentials")
        sess = cas_login.login(cred[0], cred[1], log=self.log.info)
        cs.save_cookies(cas_login.session_to_cookies(sess))
        self.state.note_login_ok()
        self.state.save()
        self._ps = self._mk_ps(sess)
        return self._ps

    def _mk_ps(self, sess) -> PlatformSession:
        sc = self.s.scan_cfg
        return PlatformSession(sess, min_delay=sc["request_min_delay"],
                               max_delay=sc["request_max_delay"],
                               budget=sc["budget_per_scan"])

    def invalidate_session(self) -> None:
        self._ps = None

    # ---- 扫描 ----
    def scan(self, respect_lock: bool = True) -> "object":
        if self.state.in_throttle_window():
            self.log.warning("处于限流退避窗口内，跳过本轮")
            return None
        lock = FileLock(self.s.lock_path)
        if respect_lock and not lock.acquire():
            self.log.warning("已有实例在扫描，跳过")
            return None
        try:
            ps = self.platform_session()
            ps.reset_budget()
            self.board.publish({"kind": "scan_start",
                               "created_at": datetime.datetime.now(TZ).isoformat(timespec="seconds")})
            # 已经抓到过要求正文的作业，本轮就不再重复抓详情（省请求、降限流风险）
            known_content = {}
            for key, rec in self.state.data.get("homeworks", {}).items():
                if rec.get("content_text"):
                    known_content[key] = hashlib.sha1(
                        ((rec.get("title") or "") + "|" + (rec.get("ddl_raw") or ""))
                        .encode("utf-8", "replace")).hexdigest()
            res = run_scan(ps, self.log, self.s.p("calibration", "errors"),
                           columns_path=self.s.columns_path,
                           max_courses=self.s.scan_cfg["max_courses"],
                           known_content=known_content)
            if getattr(res, "session_expired", False):
                # 会话失效：自动重新登录（强制全新 CAS 登录）并重试一次
                self.log.warning("扫描发现会话失效，自动重新登录后重试")
                self._ps = None
                ps2 = self.platform_session(force_login=True)
                ps2.reset_budget()
                ps = ps2
                res = run_scan(ps2, self.log, self.s.p("calibration", "errors"),
                               columns_path=self.s.columns_path,
                               max_courses=self.s.scan_cfg["max_courses"],
                               known_content=known_content)
            if res.throttled:
                secs = ps.backoff_seconds() or 60
                self.state.set_throttle(secs)
                self.log.warning(f"命中限流，退避 {secs}s")
            now = datetime.datetime.now(TZ).isoformat(timespec="seconds")
            if res.errors and not res.courses:
                # 课程列表阶段就失败：保留上一次的统计数据与作业记录，不覆盖
                self.last_scan_info = {
                    "at": now, "courses": 0, "homeworks": 0, "unsubmitted": 0,
                    "pages": res.pages, "throttled": res.throttled,
                    "errors": res.errors[:5], "notes": res.notes[:5],
                }
                self.state.data["last_scan"] = self.last_scan_info
                self.state.save()
                self.board.publish({"kind": "scan_done", **self.last_scan_info})
                self.log.warning("扫描在课程列表阶段失败: %s", res.errors)
                return res
            now = datetime.datetime.now(TZ).isoformat(timespec="seconds")
            for hw in res.homeworks:
                h = hashlib.sha1(hw.content_hash_source().encode("utf-8")).hexdigest()
                self.state.upsert(hw, h, now)
            self.state.save()
            self.last_scan_info = {
                "at": now, "courses": len(res.courses), "homeworks": len(res.homeworks),
                "unsubmitted": len(res.unsubmitted), "pages": res.pages,
                "throttled": res.throttled, "errors": res.errors[:5], "notes": res.notes[:5],
            }
            self.state.data["last_scan"] = self.last_scan_info
            self.state.save()
            self.board.publish({"kind": "scan_done", **self.last_scan_info})
            return res
        except SessionExpired as e:
            self.log.warning(f"会话问题: {e}")
            self._ps = None
            self.last_scan_info = {"at": datetime.datetime.now(TZ).isoformat(timespec="seconds"),
                                   "errors": [str(e)]}
            return None
        finally:
            lock.release()

    # ---- 提醒 ----
    def build_notifiers(self) -> list:
        n = self.s.notify_cfg
        return [BoardNotifier(self.board, {"enabled": True}, self.log),
                DesktopNotifier(n.get("desktop", {}), self.log),
                EmailNotifier(n.get("email", {}), self.log),
                WeChatNotifier(n.get("wechat", {}), self.log)]

    def notify_from_state(self, homeworks) -> list[dict]:
        n = dict(self.s.notify_cfg)
        # 展示层和提醒层用同一套过滤，避免"看不到却还在提醒"
        n["hide_overdue_days"] = self.hide_overdue_days()
        n["class_filter"] = self.s.class_cfg
        d = disp.Dispatcher(self.build_notifiers(), n, self.log)
        sent = []
        for msg, marks in d.run_rules(self.state, homeworks):
            results = d.send(msg)
            if any(v == "ok" for v in results.values()):
                for key, tier in marks:
                    self.state.mark_notified(key, tier)
            sent.append({"title": msg.title, "tier": msg.tier, "results": results})
        self.state.save()
        return sent

    # ---- 每日摘要 ----
    def digest_due(self, now: datetime.datetime | None = None) -> bool:
        """到点且今天还没发过 → True。

        用「到点即发、每天一次」而不是「必须正好在 12:30 那一刻进程活着」：
        定时任务可能每 20~30 分钟才跑一次，靠时刻精确匹配会永远错过。
        """
        cfg = (self.s.notify_cfg.get("daily_digest") or {})
        if not cfg.get("enabled"):
            return False
        now = now or datetime.datetime.now(TZ)
        hh, mm = 12, 30
        raw = str(cfg.get("time") or "12:30")
        try:
            hh, mm = (int(x) for x in raw.split(":")[:2])
        except (ValueError, TypeError):
            pass
        if (now.hour, now.minute) < (hh, mm):
            return False
        return self.state.data.get("digest_sent_date") != now.strftime("%Y-%m-%d")

    def build_digest_message(self):
        """把当前所有未提交作业 + 剩余时间整理成一条通知。"""
        from ..notify.base import NotifyMessage
        from ..notify.dispatcher import fmt_left

        self.state.refresh()
        cfg = (self.s.notify_cfg.get("daily_digest") or {})
        only_submittable = str(cfg.get("scope") or "all") == "submittable"
        with_overdue = bool(cfg.get("include_overdue", True))
        ccfg = self.s.class_cfg
        now = datetime.datetime.now(TZ)

        items = []
        for rec in self.state.data.get("homeworks", {}).values():
            if not rec.get("unsubmitted", True):
                continue
            ddl = None
            if rec.get("ddl"):
                try:
                    ddl = datetime.datetime.fromisoformat(rec["ddl"])
                except ValueError:
                    ddl = None
            left = int((ddl - now).total_seconds()) if ddl else None
            if self._is_ancient(left):
                continue
            if not classfilter.decide(rec.get("course_name", ""), rec.get("title", ""), ccfg)[0]:
                continue
            if only_submittable and not rec.get("can_submit"):
                continue
            if left is not None and left < 0 and not with_overdue:
                continue
            items.append((left, rec))
        if not items:
            return None
        # 最紧的排前面；没有 DDL 的排最后
        items.sort(key=lambda t: (t[0] is None, t[0] if t[0] is not None else 0))

        lines = []
        for left, rec in items[:15]:
            course = (rec.get("course_name") or "")[:14]
            title = (rec.get("title") or "")[:30]
            if left is None:
                tail = "无截止时间"
            elif left < 0:
                tail = fmt_left(datetime.timedelta(seconds=left))
            else:
                tail = fmt_left(datetime.timedelta(seconds=left))
            lines.append(f"· {course}｜{title}｜{tail}")
        if len(items) > 15:
            lines.append(f"…另有 {len(items) - 15} 个")

        base = self.s.notify_cfg.get("dashboard_url", "http://127.0.0.1:8765")
        return NotifyMessage(
            title=f"[每日提醒] {len(items)} 个作业尚未提交",
            body="\n".join(lines), tier="digest", urgent=False,
            keys=[r.get("course_id", "") + ":" + str(r.get("hwtid", "")) for _l, r in items],
            url=f"{base}/dashboard")

    def maybe_send_daily_digest(self) -> dict | None:
        if not self.digest_due():
            return None
        msg = self.build_digest_message()
        if msg is None:
            # 没有未提交作业也算"今天已处理"，避免整天反复尝试
            self.state.data["digest_sent_date"] = datetime.datetime.now(TZ).strftime("%Y-%m-%d")
            self.state.save()
            return None
        d = disp.Dispatcher(self.build_notifiers(), self.s.notify_cfg, self.log)
        results = d.send(msg)
        if any(v == "ok" for v in results.values()):
            self.state.data["digest_sent_date"] = datetime.datetime.now(TZ).strftime("%Y-%m-%d")
            self.state.save()
        self.log.info("每日摘要已发送: %s（%s）", msg.title, results)
        return {"title": msg.title, "tier": "digest", "results": results}

    # ---- 一次性执行 ----
    def run_once(self) -> dict:
        res = self.scan()
        sent = []
        if res is not None:
            sent = self.notify_from_state(res.homeworks)
        # 每日摘要独立于扫描结果：即使本轮被限流或会话失效，也要按时间补发
        d = self.maybe_send_daily_digest()
        if d:
            sent.append(d)
        if res is None:
            return {"scanned": False, "info": self.last_scan_info, "notified": sent}
        return {"scanned": True, "info": self.last_scan_info, "notified": sent}

    # ---- 看板数据 ----
    def hide_overdue_days(self) -> int:
        try:
            return int(self.s.scan_cfg.get("hide_overdue_days", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _is_ancient(self, left_seconds: int | None) -> bool:
        """逾期超过阈值的老记录（平台课程实例多年复用攒下的），不展示也不提醒。"""
        days = self.hide_overdue_days()
        if not days or left_seconds is None:
            return False
        return left_seconds < -days * 86400

    def dashboard_payload(self) -> dict:
        self.state.refresh()
        now = datetime.datetime.now(TZ)
        items = []
        hidden = 0
        other_class = 0
        ccfg = self.s.class_cfg
        for rec in self.state.data.get("homeworks", {}).values():
            ddl = None
            if rec.get("ddl"):
                try:
                    ddl = datetime.datetime.fromisoformat(rec["ddl"])
                except ValueError:
                    ddl = None
            left = int((ddl - now).total_seconds()) if ddl else None
            if self._is_ancient(left):
                hidden += 1
                continue
            # 别的班的实验时段：不予展示
            show, code = classfilter.decide(rec.get("course_name", ""),
                                            rec.get("title", ""), ccfg)
            if not show:
                other_class += 1
                continue
            items.append({**rec, "left_seconds": left, "class_code": code})
        # 排序：24h 内未提交最优先 → 未提交 → 已提交 → 已逾期；
        # 同一档内按剩余时间从少到多（最紧的排最上面）。
        items.sort(key=lambda r: (_tier_rank(r),
                                  r.get("left_seconds") if r.get("left_seconds") is not None else 9e9))
        unsub = [i for i in items if i.get("unsubmitted")]
        return {
            "now": now.isoformat(timespec="seconds"),
            "last_scan": self.last_scan_info,
            "throttle_until": self.state.data.get("throttle_until"),
            "login": self.state.data.get("login", {}),
            "class_filter": {
                "enabled": bool(ccfg.get("enabled")),
                "my_class": ccfg.get("my_class") or "",
                "courses": ccfg.get("courses") or [],
            },
            "hidden": {
                "count": hidden + other_class,
                "ancient": hidden,
                "other_class": other_class,
                "days": self.hide_overdue_days(),
                "reason": (f"已隐藏 {hidden} 条逾期超 {self.hide_overdue_days()} 天的旧记录"
                           + (f"，{other_class} 条其他班的实验时段" if other_class else "")),
            },
            "stats": {
                "unsubmitted": len(unsub),
                "within_24h": len([i for i in unsub if (i.get("left_seconds") or 1e9) <= 86400
                                   and (i.get("left_seconds") or -1) > 0]),
                "within_6h": len([i for i in unsub if (i.get("left_seconds") or 1e9) <= 21600
                                  and (i.get("left_seconds") or -1) > 0]),
                "overdue": len([i for i in unsub if (i.get("left_seconds") or 0) < 0]),
                "submitted": len([i for i in items if not i.get("unsubmitted")]),
                "total": len(items),
                "hidden": hidden + other_class,
            },
            "homeworks": items,
        }

    def sleep_brief(self, sec: float = 0.0) -> None:
        if sec > 0:
            time.sleep(sec)
