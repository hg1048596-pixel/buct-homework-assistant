# -*- coding: utf-8 -*-
"""日志脱敏：密码、cookie、ticket、flowKey、SendKey 等绝不落日志。"""
import logging
import re

RULES = [
    (re.compile(r'("password"\s*:\s*")[^"]*(")', re.I), r"\1***\2"),
    (re.compile(r"(IPT_LOGINPASSWORD=)[^&\s]*", re.I), r"\1***"),
    (re.compile(r"(COOKIE_INFO=)[^;\s]*", re.I), r"\1***"),
    (re.compile(r"(JSESSIONID=)[^;\s]*", re.I), r"\1***"),
    (re.compile(r"(flowKey\"?\s*[:=]\s*\"?)(flow\.)?[0-9a-f]{8,}", re.I), r"\1***"),
    (re.compile(r"(ticket=)[^&\s]*", re.I), r"\1***"),
    (re.compile(r"(SCT_API_KEY=|SendKey=|sctapi\.ftqq\.com/)[^\s/]*", re.I), r"***"),
    (re.compile(r"([0-9a-zA-Z]{16,})", re.I), None),  # 兜底：超长 token 串
]

# 兜底规则会把正常的长串也打码，故仅对 40 字符以上的裸串生效
LONG_TOKEN = re.compile(r"\b[0-9a-zA-Z]{40,}\b")


def redact(text: str) -> str:
    for pat, rep in RULES:
        if rep is None:
            continue
        text = pat.sub(rep, text)
    return LONG_TOKEN.sub("***", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        new = redact(msg)
        if new != msg:
            record.msg = new
            record.args = ()
        return True
