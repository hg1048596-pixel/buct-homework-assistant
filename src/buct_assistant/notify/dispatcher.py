# -*- coding: utf-8 -*-
"""提醒规则引擎：分档、静默时段、去重、单轮上限、噪音过滤。"""
import datetime
import re

from ..core import classfilter
from ..platform.models import TZ

URGENT_TIERS = {"d6", "d1"}
TIER_LABEL = {"new": "新作业", "d24": "24 小时内截止", "d6": "6 小时内截止",
              "d1": "1 小时内截止", "overdue": "已逾期未交", "submitted": "已提交"}
QUIET_START = datetime.time(23, 30)
QUIET_END = datetime.time(7, 30)


def in_quiet_hours(now: datetime.datetime) -> bool:
    t = now.timetz().replace(tzinfo=None)
    return t >= QUIET_START or t < QUIET_END


def fmt_left(delta: datetime.timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs < 0:
        s = -secs
        d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
        return (f"已逾期 {d} 天 {h} 小时" if d else (f"已逾期 {h} 小时 {m} 分" if h else f"已逾期 {m} 分"))
    d, h, m = secs // 86400, secs % 86400 // 3600, secs % 3600 // 60
    if d:
        return f"剩 {d} 天 {h} 小时"
    if h:
        return f"剩 {h} 小时 {m} 分"
    return f"剩 {m} 分"


def hw_body(hw) -> str:
    lines = [f"课程：{hw.course_name}", f"作业：{hw.title}"]
    if hw.ddl_raw:
        lines.append(f"截止：{hw.ddl_raw}")
    return "\n".join(lines)


class Dispatcher:
    def __init__(self, notifiers: list, cfg: dict, log):
        self.notifiers = notifiers
        self.cfg = cfg or {}
        self.log = log
        self.consecutive_failures: dict[str, int] = {}

    # ---- 规则 ----
    def run_rules(self, state, homeworks, now: datetime.datetime | None = None):
        """返回 [(NotifyMessage, [(key, tier), ...])]；去重标记由调用方在发送成功后写入。"""
        from .base import NotifyMessage

        now = now or datetime.datetime.now(TZ)
        new_items, urgent, normal = [], [], []
        max_per_cycle = int(self.cfg.get("max_notifications_per_cycle", 3))
        base_url = self.cfg.get("dashboard_url", "http://127.0.0.1:8765")
        include_overdue = bool(self.cfg.get("include_overdue", False))
        require_submittable = bool(self.cfg.get("new_requires_can_submit", True))
        ignore_pats = [str(p) for p in (self.cfg.get("ignore_title_patterns") or [])]
        instant_24h = bool(self.cfg.get("instant_24h", True))
        # 24h 那一档可以整体关掉（关掉后仍保留 6h / 1h 的更紧急提醒）
        tiers = [("d1", 3600), ("d6", 6 * 3600)]
        if instant_24h:
            tiers.append(("d24", 24 * 3600))
        try:
            ancient_days = int(self.cfg.get("hide_overdue_days", 0) or 0)
        except (TypeError, ValueError):
            ancient_days = 0
        ccfg = self.cfg.get("class_filter") or {}

        for hw in homeworks:
            if not hw.unsubmitted:
                continue
            # 逾期太久的老记录（平台课程实例多年复用攒下来的）不提醒
            if ancient_days and hw.ddl:
                if (hw.ddl - now).total_seconds() < -ancient_days * 86400:
                    continue
            # 别的班的实验时段不提醒
            if ccfg and not classfilter.decide(hw.course_name, hw.title, ccfg)[0]:
                continue
            # 实测踩坑：一门课里会混进「别的班的实验时段」这类条目（未提交且已逾期、
            # 且不允许提交），实测 158 条未提交里 143 条是这种噪音。默认不提醒，
            # 免得一上线就刷屏。
            if require_submittable and not hw.can_submit:
                continue
            if ignore_pats and any(re.search(p, hw.title) for p in ignore_pats):
                continue
            if not state.notified(hw.key, "new"):
                new_items.append(hw)
                continue
            left = hw.remaining(now)
            if left is None:
                continue
            secs = left.total_seconds()
            if secs < 0:
                if (include_overdue and not state.notified(hw.key, "overdue")
                        and now.hour >= int(self.cfg.get("overdue_digest_hour", 9))):
                    msg = NotifyMessage(
                        title=f"已逾期未交：{hw.course_name} {hw.title}",
                        body=hw_body(hw), tier="overdue", keys=[hw.key],
                        url=f"{base_url}/homework/{hw.course_id}/{hw.hwtid}")
                    normal.append((msg, [(hw.key, "overdue")]))
                continue
            for tier, thresh in tiers:
                if secs <= thresh and not state.notified(hw.key, tier):
                    urgent_flag = tier in URGENT_TIERS
                    msg = NotifyMessage(
                        title=f"[{TIER_LABEL[tier]}] {hw.course_name} {hw.title}",
                        body=f"{hw_body(hw)}\n{fmt_left(left)}",
                        tier=tier, urgent=urgent_flag, keys=[hw.key],
                        url=f"{base_url}/homework/{hw.course_id}/{hw.hwtid}")
                    (urgent if urgent_flag else normal).append((msg, [(hw.key, tier)]))
                    break

        if new_items:
            lines = []
            for hw in new_items[:10]:
                tail = f"（{fmt_left(hw.remaining(now))}）" if hw.ddl else ""
                lines.append(f"· {hw.course_name}｜{hw.title}{tail}")
            if len(new_items) > 10:
                lines.append(f"…另有 {len(new_items) - 10} 个")
            msg = NotifyMessage(
                title=f"发现 {len(new_items)} 个新作业",
                body="\n".join(lines), tier="new",
                keys=[h.key for h in new_items], url=f"{base_url}/dashboard")
            normal.insert(0, (msg, [(h.key, "new") for h in new_items]))

        picked = urgent + normal
        if len(picked) > max_per_cycle:
            self.log.info(f"本轮提醒 {len(picked)} 条超过上限 {max_per_cycle}，仅发紧急与最新")
            picked = urgent + normal[:max(0, max_per_cycle - len(urgent))]

        if in_quiet_hours(now):
            kept = [p for p in picked if p[0].urgent]
            if len(kept) != len(picked):
                self.log.info("静默时段：非紧急提醒延后")
            picked = kept
        return picked

    # ---- 发送 ----
    def send(self, msg) -> dict[str, str]:
        """逐渠道独立发送，单渠道失败不影响其它。返回 {渠道: 'ok'|错误信息}。"""
        results = {}
        for n in self.notifiers:
            if not n.enabled():
                continue
            try:
                n.send(msg)
                results[n.name] = "ok"
                self.consecutive_failures[n.name] = 0
            except Exception as e:  # noqa: BLE001
                results[n.name] = f"{type(e).__name__}: {e}"
                self.consecutive_failures[n.name] = self.consecutive_failures.get(n.name, 0) + 1
                self.log.warning(f"渠道 {n.name} 发送失败: {e}")
        return results

    def degraded(self) -> list[str]:
        return [k for k, v in self.consecutive_failures.items() if v >= 3]
