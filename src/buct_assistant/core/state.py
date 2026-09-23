# -*- coding: utf-8 -*-
"""状态存储：去重、限流窗口、提交状态。原子写 + 文件锁防并发。"""
import datetime
import json
import os
import time

from ..platform.models import TZ


class StateStore:
    def __init__(self, path: str):
        self.path = path
        self._mtime_seen = 0.0
        self.data = self._load()

    # ---- 读写 ----
    def _mtime(self) -> float:
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return 0.0

    def refresh(self) -> None:
        """文件被其它进程（定时任务）改过就重新载入，控制台才看得到后台的扫描结果。"""
        m = self._mtime()
        if m and m != self._mtime_seen:
            self.data = self._load()
            self._mtime_seen = m

    def _load(self) -> dict:
        self._mtime_seen = self._mtime()
        if not os.path.exists(self.path):
            return {"version": 1, "homeworks": {}, "login": {}, "throttle_until": None}
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            # 损坏的 state 不应阻塞运行，备份后重建
            os.replace(self.path, self.path + ".broken")
            return {"version": 1, "homeworks": {}, "login": {}, "throttle_until": None}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.data["updated_at"] = datetime.datetime.now(TZ).isoformat(timespec="seconds")
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        self._mtime_seen = self._mtime()

    # ---- 作业 ----
    def upsert(self, hw, content_hash: str, seen_at: str) -> dict:
        rec = self.data["homeworks"].get(hw.key)
        if rec is None:
            rec = {
                "course_id": hw.course_id, "course_name": hw.course_name,
                "hwtid": hw.hwtid, "title": hw.title, "ddl": None, "ddl_raw": "",
                "first_seen": seen_at, "last_seen": seen_at,
                "content_hash": content_hash, "notified": {}, "submit_state": "IDLE",
                "confidence": hw.confidence,
            }
        rec.update({
            "course_name": hw.course_name, "title": hw.title,
            "ddl": hw.ddl.isoformat() if hw.ddl else None, "ddl_raw": hw.ddl_raw,
            "last_seen": seen_at, "unsubmitted": hw.unsubmitted,
            "can_submit": hw.can_submit, "confidence": hw.confidence,
            "score_raw": hw.score_raw, "content_hash": content_hash,
            "scoring_method": hw.scoring_method, "url": hw.url,
            "layout": hw.layout, "content_text": hw.content_text,
        })
        self.data["homeworks"][hw.key] = rec
        return rec

    def get(self, key: str) -> dict | None:
        self.refresh()
        return self.data["homeworks"].get(key)

    def notified(self, key: str, tier: str) -> bool:
        return bool((self.data["homeworks"].get(key, {}).get("notified") or {}).get(tier))

    def mark_notified(self, key: str, tier: str) -> None:
        self.data["homeworks"].setdefault(key, {}).setdefault("notified", {})[tier] = True

    def reset_notified(self, key: str, tier: str) -> None:
        rec = self.data["homeworks"].get(key)
        if rec:
            (rec.get("notified") or {}).pop(tier, None)

    def set_submit_state(self, key: str, state: str) -> None:
        self.data["homeworks"].setdefault(key, {})["submit_state"] = state

    def unsubmitted_records(self) -> list[dict]:
        self.refresh()
        return [r for r in self.data["homeworks"].values() if r.get("unsubmitted", True)]

    # ---- 限流 ----
    def in_throttle_window(self) -> bool:
        until = self.data.get("throttle_until")
        if not until:
            return False
        try:
            return datetime.datetime.fromisoformat(until) > datetime.datetime.now(TZ)
        except ValueError:
            return False

    def set_throttle(self, seconds: int) -> None:
        until = datetime.datetime.now(TZ) + datetime.timedelta(seconds=seconds)
        self.data["throttle_until"] = until.isoformat(timespec="seconds")

    # ---- 登录 ----
    def note_login_ok(self) -> None:
        self.data.setdefault("login", {}).update({
            "last_login_ok": datetime.datetime.now(TZ).isoformat(timespec="seconds"),
            "last_fail_code": None})

    def note_login_fail(self, code, lockout_seconds: int = 0) -> None:
        lg = self.data.setdefault("login", {})
        lg["last_fail_code"] = code
        lg["last_fail_at"] = datetime.datetime.now(TZ).isoformat(timespec="seconds")
        if lockout_seconds:
            until = datetime.datetime.now(TZ) + datetime.timedelta(seconds=lockout_seconds)
            lg["lockout_until"] = until.isoformat(timespec="seconds")

    def login_locked(self) -> bool:
        until = (self.data.get("login") or {}).get("lockout_until")
        if not until:
            return False
        try:
            return datetime.datetime.fromisoformat(until) > datetime.datetime.now(TZ)
        except ValueError:
            return False


def _pid_alive(pid: int) -> bool:
    """进程是否还活着。Windows 用 OpenProcess，其它平台用 os.kill(pid, 0)。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        exit_code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and exit_code.value == 259   # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class FileLock:
    """跨进程互斥（网页控制台内嵌调度 vs 任务计划程序）。

    锁文件里写 PID：持有者进程已经死了就直接抢占，不必傻等超时
    （否则一次崩溃会让扫描停摆 15 分钟）。
    """

    def __init__(self, path: str, stale_seconds: int = 900):
        self.path = path
        self.stale_seconds = stale_seconds
        self.acquired = False

    def _holder_pid(self) -> int:
        try:
            with open(self.path, encoding="utf-8") as f:
                return int(f.read().split()[0])
        except (OSError, ValueError, IndexError):
            return 0

    def acquire(self) -> bool:
        if os.path.exists(self.path):
            pid = self._holder_pid()
            if pid and not _pid_alive(pid):
                self._note(f"持有进程 {pid} 已退出，抢占锁")
            else:
                try:
                    age = time.time() - os.path.getmtime(self.path)
                except OSError:
                    age = 0
                if age < self.stale_seconds:
                    return False
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {datetime.datetime.now(TZ).isoformat()}")
        self.acquired = True
        return True

    def _note(self, msg: str) -> None:
        if self.logger:
            self.logger.info(msg)

    logger = None

    def release(self) -> None:
        if self.acquired and os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass
        self.acquired = False

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("另一个实例正在扫描（scan.lock 被占用）")
        return self

    def __exit__(self, *exc):
        self.release()
        return False
