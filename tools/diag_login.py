# -*- coding: utf-8 -*-
"""登录诊断：在不泄露密码的前提下，判断失败原因是「凭据不对」还是「请求格式不对」。

做法：用一个明显不存在的账号（不会影响真实账号的失败计数），分别发送
  A) 明显非法的 password 值（不是合法 base64）
  B) 合法 base64 但内容随机的 password 值（服务端解密出来必然是乱码）
比较两者的返回码：
  - 若 A 与 B 返回码不同 → 服务端会校验 password 字段格式，说明我们的格式是对的
  - 若 A 与 B 都是 170002 → 服务端不区分格式，无法据此判断，需要人工核对凭据
另外检查本地已保存的密码有没有异常字符（只打印统计，不打印内容）。
"""
import os
import sys
import unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

import requests  # noqa: E402

from buct_assistant.cas import cas_login  # noqa: E402
from buct_assistant.crypto.sm2_c1c3c2 import encrypt_password, to_halfwidth  # noqa: E402
from buct_assistant.security import credential_store as cs  # noqa: E402

FAKE_USER = "0000000000"


def inspect_password(pwd: str) -> None:
    print("— 本地保存的密码体检（不打印内容）—")
    print(f"  长度        : {len(pwd)}")
    print(f"  全是 ASCII  : {all(ord(c) < 128 for c in pwd)}")
    print(f"  首尾有空白  : {pwd != pwd.strip()}")
    print(f"  含控制字符  : {any(ord(c) < 32 for c in pwd)}")
    print(f"  全角转半角后是否变化: {to_halfwidth(pwd) != pwd}")
    try:
        pwd.encode("ascii")
    except UnicodeEncodeError:
        odd = sorted({c for c in pwd if ord(c) >= 128})
        print(f"  非 ASCII 字符: {[f'U+{ord(c):04X}' for c in odd][:8]}")
    print(f"  字符类别分布: 小写{sum(c.islower() for c in pwd)} 大写{sum(c.isupper() for c in pwd)} "
          f"数字{sum(c.isdigit() for c in pwd)} 符号{sum(not c.isalnum() for c in pwd)}")


def try_login(username: str, password_value: str, label: str) -> None:
    s = requests.Session()
    s.headers["User-Agent"] = cas_login.UA
    s.get(cas_login.SSO_ENTRY, timeout=30)
    fk = cas_login._extract_flow_key(s)
    r = s.post(cas_login.LOGIN_URL,
               json={"username": username, "password": password_value, "flowKey": fk},
               timeout=30, headers={"Referer": f"{cas_login.PORTAL}/cas/login"})
    body = r.text[:200]
    print(f"  {label}: HTTP {r.status_code} {body}")


def main() -> int:
    cred = cs.load_credentials()
    if cred:
        inspect_password(cred[1])
        print()
    print("— 请求格式诊断（用不存在的账号，不影响真实账号）—")
    try_login(FAKE_USER, "!!!not-base64!!!", "A 非法 base64")
    try_login(FAKE_USER, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==", "B 合法 base64 乱码")
    print()
    print("提示：若 A、B 与真实账号返回同一个 170002，说明该码不区分原因，")
    print("      需要人工确认密码是否与统一身份认证一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
