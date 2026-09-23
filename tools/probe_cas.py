# -*- coding: utf-8 -*-
"""CAS 链路自检：不用真实账号，验证 flowKey 提取 / 公钥获取 / SM2 加密 / 响应解析。

用一个明显不存在的账号触发一次登录，预期拿到 170002（用户名或密码错误）
或 160002（要求验证码），说明链路通。绝不使用真实学号，避免影响账号。

用法: python tools/probe_cas.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

import requests  # noqa: E402

from buct_assistant.cas import cas_login  # noqa: E402
from buct_assistant.cas.errors import CasError  # noqa: E402
from buct_assistant.crypto.sm2_c1c3c2 import encrypt_password  # noqa: E402

FAKE_USER = "0000000000"


def main() -> int:
    s = requests.Session()
    s.headers["User-Agent"] = cas_login.UA

    print("[1] GET sso_login.jsp 跟随跳转 ...")
    r = s.get(cas_login.SSO_ENTRY, timeout=30)
    print(f"    最终 URL: {r.url}  status={r.status_code}")
    print(f"    cookie: {[c.name for c in s.cookies]}")

    print("[2] 提取 flowKey ...")
    try:
        fk = cas_login._extract_flow_key(s)
        print(f"    OK flowKey={fk[:14]}... len={len(fk)}")
    except CasError as e:
        print(f"    FAIL {e}")
        return 1

    print("[3] 获取 SM2 公钥 ...")
    try:
        pub = cas_login._get_public_key(s)
        print(f"    OK publicKey={pub[:20]}... len={len(pub)}")
    except CasError as e:
        print(f"    FAIL {e}")
        return 1

    print("[4] SM2 加密测试口令 ...")
    try:
        ct = encrypt_password("Test-password-123", pub)
        print(f"    OK 密文 base64 长度={len(ct)}")
    except Exception as e:  # noqa: BLE001
        print(f"    FAIL {e}")
        return 1

    print(f"[5] 用不存在账号 {FAKE_USER} 触发一次登录（预期 170002）...")
    payload = {"username": FAKE_USER, "password": ct, "flowKey": fk}
    resp = s.post(cas_login.LOGIN_URL, json=payload, timeout=30,
                  headers={"Referer": f"{cas_login.PORTAL}/cas/login"})
    print(f"    HTTP {resp.status_code}  body={resp.text[:300]}")

    print("\n结论：前 4 步全部 OK 即说明链路可用，第 5 步返回 170002/160002 均属正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
