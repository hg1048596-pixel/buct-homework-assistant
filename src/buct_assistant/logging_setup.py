# -*- coding: utf-8 -*-
"""日志：文件轮转 + 控制台，全程脱敏。"""
import logging
import logging.handlers
import os
import sys

from .security.redact import RedactingFilter

_configured = False


def setup(log_dir: str, quiet: bool = False, level: int = logging.INFO) -> logging.Logger:
    global _configured
    log = logging.getLogger("buct")
    if _configured:
        return log
    log.setLevel(level)
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    flt = RedactingFilter()

    os.makedirs(log_dir, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "app.log"), maxBytes=5 * 1024 * 1024,
        backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(flt)
    log.addHandler(fh)

    if not quiet and sys.stdout is not None:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        sh.addFilter(flt)
        log.addHandler(sh)

    _configured = True
    return log
