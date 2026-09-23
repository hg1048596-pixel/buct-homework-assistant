# -*- coding: utf-8 -*-
"""提交流程：草稿 → 预演(dry-run) → 人工确认 → 提交 → 校验。

四重闸门（缺一不可）：
  1. dry-run 逐字展示将要发送的字段（form action、hwtid/hwaid、正文、附件名与远端路径）
  2. 必须手工键入作业标题前 4 个字
  3. 一次性 token（30 分钟过期、用后即废）
  4. 提交前重新拉页面，确认该作业仍然「未提交且可提交」（幂等护栏）

提交结果不确定时一律标 UNKNOWN 且**绝不自动重试**（无法区分"已入库"与"没写"）。
"""
import datetime
import hashlib
import json
import os
import re
import secrets
import shutil
from dataclasses import asdict, dataclass, field

from ..platform import submit as sub
from ..platform import urls
from ..platform.models import TZ

STATES = ("DRAFT", "PREVIEWED", "SUBMITTING", "SUBMITTED", "FAILED", "UNKNOWN")
TOKEN_TTL_MIN = 30
CONFIRM_CHARS = 4


def gbk_lossy_chars(text: str) -> list[str]:
    """找出无法用 GBK 表示的字符（提交时会被替换成 ?，必须提前告知）。"""
    bad = []
    for ch in text:
        try:
            ch.encode("gbk")
        except UnicodeEncodeError:
            if ch not in bad:
                bad.append(ch)
    return bad


@dataclass
class Draft:
    token: str
    course_id: str
    course_name: str
    hwtid: str
    title: str
    kind: str = "text"            # text | file | both
    text: str = ""
    staged_file: str = ""         # 本地暂存路径
    original_name: str = ""
    final_name: str = ""
    name_template: str = ""
    state: str = "DRAFT"
    created_at: str = ""
    expires_at: str = ""
    used: bool = False
    result: dict = field(default_factory=dict)

    @property
    def confirm_phrase(self) -> str:
        return self.title[:CONFIRM_CHARS]

    def expired(self) -> bool:
        try:
            return datetime.datetime.fromisoformat(self.expires_at) < datetime.datetime.now(TZ)
        except (ValueError, TypeError):
            return True


class SubmitManager:
    def __init__(self, settings, service, log):
        self.s = settings
        self.svc = service
        self.log = log
        self.outbox = os.path.join(settings.data_dir, "outbox")
        self.audit_dir = os.path.join(settings.data_dir, "audit")
        os.makedirs(self.outbox, exist_ok=True)
        os.makedirs(self.audit_dir, exist_ok=True)
        self.drafts: dict[str, Draft] = {}
        self._sweep_submitted()

    def _sweep_submitted(self) -> None:
        """启动时清扫：已成功提交的 outbox 项直接删除（证据在审计日志里，不占磁盘）。"""
        for name in os.listdir(self.outbox):
            d = os.path.join(self.outbox, name)
            meta = os.path.join(d, "draft.json")
            if not os.path.isfile(meta):
                continue
            try:
                with open(meta, encoding="utf-8") as f:
                    if json.load(f).get("state") == "SUBMITTED":
                        shutil.rmtree(d, ignore_errors=True)
                        self.log.info("已清理已提交的暂存目录: %s", name)
            except Exception:  # noqa: BLE001
                continue

    def _purge_draft(self, token: str) -> None:
        """提交成功后删除该 outbox 项（草稿、附件与正文一并清除）。"""
        shutil.rmtree(os.path.join(self.outbox, token), ignore_errors=True)
        self.drafts.pop(token, None)

    # ---------- 审计 ----------
    def audit(self, event: str, data: dict) -> None:
        os.makedirs(self.audit_dir, exist_ok=True)
        rec = {"at": datetime.datetime.now(TZ).isoformat(timespec="seconds"),
               "event": event, **data}
        path = os.path.join(self.audit_dir,
                            datetime.datetime.now(TZ).strftime("%Y-%m-%d") + ".jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---------- 草稿 ----------
    def create_draft(self, course_id: str, hwtid: str, text: str = "",
                     file_path: str = "", file_bytes: bytes | None = None,
                     upload_name: str = "", name_template: str = "",
                     name_fields: dict | None = None) -> Draft:
        rec = self.svc.state.get(f"{course_id}:{hwtid}") or {}
        title = rec.get("title", "") or "未命名作业"
        token = secrets.token_urlsafe(16)
        now = datetime.datetime.now(TZ)

        staged = ""
        original = upload_name or (os.path.basename(file_path) if file_path else "")
        final = original
        if file_path or file_bytes is not None:
            d = os.path.join(self.outbox, token)
            os.makedirs(d, exist_ok=True)
            # 先把原始文件落到 outbox，保证提交的是"我确认过的这一份"
            staged = os.path.join(d, original or "upload.bin")
            if file_bytes is not None:
                with open(staged, "wb") as f:
                    f.write(file_bytes)
            else:
                shutil.copy2(file_path, staged)
            if name_template:
                final = sub.beautify_name(original, name_template, name_fields or {})

        kind = "both" if (staged and text) else ("file" if staged else "text")
        draft = Draft(
            token=token, course_id=course_id, course_name=rec.get("course_name", ""),
            hwtid=hwtid, title=title, kind=kind, text=text, staged_file=staged,
            original_name=original, final_name=final, name_template=name_template,
            state="DRAFT",
            created_at=now.isoformat(timespec="seconds"),
            expires_at=(now + datetime.timedelta(minutes=TOKEN_TTL_MIN)).isoformat(timespec="seconds"))
        self.drafts[token] = draft
        self._save(draft)
        self.audit("draft", {"token": token, "key": f"{course_id}:{hwtid}", "kind": kind,
                             "size": os.path.getsize(staged) if staged else 0})
        return draft

    def _save(self, draft: Draft) -> None:
        d = os.path.join(self.outbox, draft.token)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "draft.json"), "w", encoding="utf-8") as f:
            json.dump(asdict(draft), f, ensure_ascii=False, indent=2)

    def get(self, token: str) -> Draft | None:
        return self.drafts.get(token)

    # ---------- 预演 ----------
    def preview(self, token: str) -> dict:
        draft = self.drafts.get(token)
        if not draft:
            return {"ok": False, "err": "草稿不存在或已过期"}
        if draft.used:
            return {"ok": False, "err": "该确认令牌已使用过（一次性）"}
        if draft.expired():
            return {"ok": False, "err": "确认令牌已过期，请重新生成"}

        ps = self.svc.platform_session()
        form, _html = sub.fetch_write_form(ps, draft.hwtid)

        parts: list[str] = []
        if draft.staged_file:
            parts.append(sub.attachment_html("[提交时替换为远端路径]", draft.final_name))
        if draft.text:
            parts.append(re.sub(r"\n", "<br>", draft.text))
        body_html = "\n".join(parts)

        lossy = gbk_lossy_chars(re.sub(r"<[^>]+>", "", body_html))
        payload = {
            "url": f"{urls.BASE}/meol/common/hw/student/{form.action}",
            "method": "POST",
            "content_type": "application/x-www-form-urlencoded（GBK 编码）",
            "fields": {
                "hwtid": form.hwtid or draft.hwtid,
                "hwaid": form.hwaid or "NA",
                "IPT_BODY": body_html,
            },
        }
        draft.state = "PREVIEWED"
        self._save(draft)
        self.audit("preview", {"token": token, "hwtid": draft.hwtid,
                               "body_len": len(body_html)})
        return {
            "ok": True,
            "token": token,
            "title": draft.title,
            "course": draft.course_name,
            "confirm_phrase": draft.confirm_phrase,
            "confirm_chars": CONFIRM_CHARS,
            "payload": payload,
            "attachment": {
                "local": draft.staged_file,
                "final_name": draft.final_name,
                "original_name": draft.original_name,
                "size": os.path.getsize(draft.staged_file) if draft.staged_file else 0,
                "note": "提交时会先上传到 SerUpload，再把返回的下载链接插进正文",
            } if draft.staged_file else None,
            "gbk_lossy": lossy,
            "expires_at": draft.expires_at,
            "requirement": form.requirement_text,
        }

    # ---------- 提交 ----------
    def confirm(self, token: str, typed: str) -> dict:
        draft = self.drafts.get(token)
        if not draft:
            return {"ok": False, "err": "草稿不存在"}
        # 闸门 3：token 只能用一次、且未过期
        if draft.used:
            return {"ok": False, "err": "该确认令牌已用过"}
        if draft.expired():
            return {"ok": False, "err": "确认令牌已过期"}
        if draft.state not in ("PREVIEWED", "DRAFT"):
            return {"ok": False, "err": f"状态不对：{draft.state}"}
        # 闸门 2：必须键入标题前 4 个字
        if typed.strip() != draft.confirm_phrase:
            self.audit("confirm_rejected", {"token": token, "reason": "phrase_mismatch"})
            return {"ok": False, "err": f"确认文字不匹配，请输入「{draft.confirm_phrase}」"}
        # 频率限制
        limit = int(self.s.submit_cfg.get("max_per_day", 3))
        if self._today_count() >= limit:
            return {"ok": False, "err": f"今日提交次数已达上限 {limit}"}
        if self._recent_submit(draft.hwtid):
            return {"ok": False, "err": "同一作业 10 分钟内已提交过一次，请稍后再试"}

        ps = self.svc.platform_session()

        # 闸门 4：提交前重新确认该作业仍「未提交且可提交」
        try:
            form, _html = sub.fetch_write_form(ps, draft.hwtid)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "err": f"提交前复核失败：{e}"}
        if not form.has_body_field:
            self.audit("confirm_aborted", {"token": token, "reason": "no_body_field"})
            return {"ok": False, "err": "平台上这个作业已经没有提交入口了（可能已交或已截止），已中止"}
        if not form.has_submit_button:
            return {"ok": False, "err": "页面上没有提交按钮，已中止"}

        draft.state = "SUBMITTING"
        self._save(draft)

        parts: list[str] = []
        upload_info = None
        if draft.staged_file:
            up = sub.upload_file(ps, draft.staged_file, draft.final_name)
            if not up.ok:
                draft.state = "FAILED"
                draft.result = {"stage": "upload", "err": up.err, "raw": up.raw}
                self._save(draft)
                self.audit("upload_failed", {"token": token, "err": up.err, "raw": up.raw})
                return {"ok": False, "err": f"附件上传失败：{up.err}", "stage": "upload"}
            # 回读校验：确认远端能取到同样字节数
            try:
                r = ps._request("GET", urls.BASE + up.url if up.url.startswith("/") else up.url)
                remote_len = len(r.content)
            except Exception:  # noqa: BLE001
                remote_len = -1
            local_len = os.path.getsize(draft.staged_file)
            if remote_len != local_len:
                draft.state = "FAILED"
                draft.result = {"stage": "upload_verify", "local": local_len, "remote": remote_len}
                self._save(draft)
                self.audit("upload_mismatch", {"token": token, "local": local_len,
                                               "remote": remote_len})
                return {"ok": False, "stage": "upload_verify",
                        "err": f"附件回读字节数不一致（本地 {local_len} / 远端 {remote_len}），已中止"}
            upload_info = {"url": up.url, "bytes": remote_len}
            parts.append(sub.attachment_html(up.url, draft.final_name))
        if draft.text:
            parts.append(re.sub(r"\n", "<br>", draft.text))
        body_html = "\n".join(parts)

        res = sub.submit(ps, form.hwtid or draft.hwtid, form.hwaid or "NA",
                         body_html, action_path=form.action)
        self.audit("submit_request", {
            "token": token, "hwtid": draft.hwtid, "course": draft.course_name,
            "title": draft.title, "action": form.action,
            "fields": {"hwtid": form.hwtid, "hwaid": form.hwaid},
            "body_sha1": hashlib.sha1(body_html.encode("utf-8", "replace")).hexdigest(),
            "body_len": len(body_html), "upload": upload_info,
            "status_code": res.status_code, "location": res.location,
            "kind": res.kind, "err": res.err, "body_head": res.body_head[:500],
        })

        if res.ok:
            draft.state = "SUBMITTED"
            draft.used = True
            draft.result = {"status_code": res.status_code, "location": res.location}
            self._mark_submitted(draft)
            # 提交成功 → 立即清除该 outbox 项（审计日志已留存证据，不占磁盘）
            self._purge_draft(draft.token)
        else:
            # 请求异常 / 没有跳转 —— 一律视为结果未知，绝不自动重试
            draft.state = "UNKNOWN"
            draft.used = True
            draft.result = {"status_code": res.status_code, "err": res.err,
                            "body_head": res.body_head[:300]}
        self._save(draft)
        return {"ok": res.ok, "state": draft.state, "status_code": res.status_code,
                "location": res.location, "err": res.err,
                "message": ("已提交" if res.ok else
                            "提交请求已发出但平台未按预期响应，结果未知，请到平台上人工确认，"
                            "本工具不会自动重试")}

    # ---------- 辅助 ----------
    def _today_count(self) -> int:
        path = os.path.join(self.audit_dir,
                            datetime.datetime.now(TZ).strftime("%Y-%m-%d") + ".jsonl")
        if not os.path.exists(path):
            return 0
        n = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    if json.loads(line).get("event") == "submit_request":
                        n += 1
                except json.JSONDecodeError:
                    pass
        return n

    def _recent_submit(self, hwtid: str) -> bool:
        cd = int(self.s.submit_cfg.get("cooldown_minutes", 10))
        path = os.path.join(self.audit_dir,
                            datetime.datetime.now(TZ).strftime("%Y-%m-%d") + ".jsonl")
        if not os.path.exists(path):
            return False
        cutoff = datetime.datetime.now(TZ) - datetime.timedelta(minutes=cd)
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("event") != "submit_request" or str(r.get("hwtid")) != str(hwtid):
                    continue
                try:
                    if datetime.datetime.fromisoformat(r["at"]) > cutoff:
                        return True
                except (ValueError, KeyError):
                    continue
        return False

    def _mark_submitted(self, draft: Draft) -> None:
        """写回 state：标记为已提交，并清掉提醒记录。"""
        st = self.svc.state
        st.set_submit_state(f"{draft.course_id}:{draft.hwtid}", "SUBMITTED")
        rec = st.data["homeworks"].get(f"{draft.course_id}:{draft.hwtid}")
        if rec:
            rec["unsubmitted"] = False
        st.save()
