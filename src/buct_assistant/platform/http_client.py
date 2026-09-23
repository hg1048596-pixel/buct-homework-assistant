# -*- coding: utf-8 -*-
"""平台会话封装：GBK 解码、限速、限流退避、会话失效检测、请求预算。

上层永远拿 str / bytes，不关心编码。
"""
import logging
import random
import re
import time
import urllib.parse

import requests

from .urls import ALLOWED_HOSTS

log = logging.getLogger("buct")

THROTTLE_MARKS = ("访问过于频繁", "请稍后再试")
LOGIN_MARKS = ("用户登录", "IPT_LOGINPASSWORD", "loginCheck.do")


class SessionExpired(Exception):
    """会话失效，需要重新登录。"""


class Throttled(Exception):
    """被平台限流。"""


class BudgetExceeded(Exception):
    """单轮请求预算用尽。"""


def _charset_of(content_type: str) -> str | None:
    for part in (content_type or "").split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip().strip('"')
    return None


_META_CHARSET = re.compile(rb"charset\s*=\s*[\"']?\s*([A-Za-z0-9_\-]+)", re.I)


def _meta_charset(content: bytes) -> str | None:
    m = _META_CHARSET.search(content[:3000])
    return m.group(1).decode("ascii", "ignore") if m else None


def decode_page(content: bytes, content_type: str = "") -> str:
    """按声明解码；没有声明就嗅探（先严格试 UTF-8，失败再 GBK）。

    实测平台并不统一：/meol/index.do 是 UTF-8，课程页与 loginCheck.do 是 GBK。
    绝不能全局假定 GBK。
    """
    cs = _charset_of(content_type) or _meta_charset(content)
    if cs:
        try:
            return content.decode(cs, "replace")
        except LookupError:
            pass
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("gbk", "replace")


class PlatformSession:
    def __init__(self, session: requests.Session, min_delay=0.3, max_delay=0.8,
                 budget=40, timeout=30):
        self.s = session
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.budget = budget
        self.timeout = timeout
        self.used = 0
        self.throttle_level = 0
        self._last = 0.0

    # ---- 基础设施 ----
    def _guard_host(self, url: str) -> None:
        host = urllib.parse.urlparse(url).hostname
        if host not in ALLOWED_HOSTS:
            raise ValueError(f"域名不在白名单内，拒绝请求: {host}")

    def _wait(self) -> None:
        gap = self._last + random.uniform(self.min_delay, self.max_delay) - time.monotonic()
        if gap > 0:
            time.sleep(gap)

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        if self.used >= self.budget:
            raise BudgetExceeded(f"本轮已达请求预算 {self.budget}，中止以免触发限流")
        self._guard_host(url)
        self._wait()
        kw.setdefault("timeout", self.timeout)
        r = self.s.request(method, url, **kw)
        self.used += 1
        self._last = time.monotonic()
        return r

    def _check(self, r: requests.Response, text_probe: str | None = None) -> None:
        probe = text_probe if text_probe is not None else r.text
        if any(m in probe for m in THROTTLE_MARKS):
            self.throttle_level += 1
            raise Throttled(f"命中限流提示（等级 {self.throttle_level}）")
        if "/cas/login" in r.url or "loginCheck" in r.url:
            raise SessionExpired(f"被踢回登录页: {r.url}")

    # ---- 读写 ----
    def get_bytes(self, url: str, **kw):
        r = self._request("GET", url, **kw)
        return r.content, r

    def get_text(self, url: str, **kw) -> str:
        r = self._request("GET", url, **kw)
        text = decode_page(r.content, r.headers.get("Content-Type", ""))
        self._check(r, text)
        return text

    def get_text_quiet(self, url: str, **kw) -> tuple[str, requests.Response]:
        """不抛限流/失效异常，由调用方自行判断（dump 场景用）。"""
        r = self._request("GET", url, **kw)
        return decode_page(r.content, r.headers.get("Content-Type", "")), r

    def post_gbk(self, url: str, fields: dict, **kw) -> requests.Response:
        body = urllib.parse.urlencode(fields, encoding="gbk", errors="replace").encode("ascii")
        headers = kw.pop("headers", {})
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        r = self._request("POST", url, data=body, headers=headers,
                          allow_redirects=kw.pop("allow_redirects", False), **kw)
        self._check(r, r.content.decode("gbk", "replace"))
        return r

    def post_multipart(self, url: str, fields: dict, files: dict, headers: dict | None = None,
                       allow_redirects: bool = False) -> requests.Response:
        r = self._request("POST", url, data=fields, files=files,
                          headers=headers or {}, allow_redirects=allow_redirects)
        self._check(r, r.content.decode("gbk", "replace"))
        return r

    # ---- 退避 ----
    def backoff_seconds(self) -> int:
        table = [5, 15, 45, 120, 300]
        return table[min(self.throttle_level, len(table)) - 1] if self.throttle_level else 0

    def note_success(self) -> None:
        if self.throttle_level > 0:
            self.throttle_level -= 1

    def reset_budget(self) -> None:
        self.used = 0
