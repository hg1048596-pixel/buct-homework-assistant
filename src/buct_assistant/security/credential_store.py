# -*- coding: utf-8 -*-
"""凭据与会话 cookie 的本地存储。

存放 %LOCALAPPDATA%/buct-assistant/credentials.dat（DPAPI 加密，不进项目目录，
避免被 Git / 网盘同步带出去）。文件内容 JSON：
{"version":1, "username":..., "password":..., "cookies":[...], "saved_at":...}
"""
import datetime
import json
import os

from . import dpapi

STORE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "buct-assistant")
STORE_FILE = os.path.join(STORE_DIR, "credentials.dat")


def _load_raw() -> dict:
    if not os.path.exists(STORE_FILE):
        return {}
    import base64

    blob = base64.b64decode(open(STORE_FILE, "rb").read())
    return json.loads(dpapi.unprotect(blob).decode("utf-8"))


def _save_raw(payload: dict) -> None:
    os.makedirs(STORE_DIR, exist_ok=True)
    import base64

    blob = dpapi.protect(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    tmp = STORE_FILE + ".tmp"
    with open(tmp, "wb") as f:
        f.write(base64.b64encode(blob))
    os.replace(tmp, STORE_FILE)


def save_credentials(username: str, password: str) -> None:
    p = _load_raw()
    p.update({"version": 1, "username": username, "password": password,
              "saved_at": datetime.datetime.now().isoformat(timespec="seconds")})
    _save_raw(p)


def load_credentials() -> tuple[str, str] | None:
    p = _load_raw()
    if p.get("username") and p.get("password"):
        return p["username"], p["password"]
    return None


def save_cookies(cookies: list[dict]) -> None:
    p = _load_raw()
    p["cookies"] = cookies
    p["cookies_saved_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    _save_raw(p)


def load_cookies() -> list[dict]:
    return _load_raw().get("cookies", [])


def has_credentials() -> bool:
    return load_credentials() is not None
