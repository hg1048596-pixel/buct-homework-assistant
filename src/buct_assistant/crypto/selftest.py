# -*- coding: utf-8 -*-
"""SM2 加密自检：不联网，用已确证的 BUCT 公钥验证密文格式与长度恒等式。"""
from .sm2_c1c3c2 import encrypt_password, to_halfwidth

# 2026-09-23 从 portal.buct.edu.cn/cas/api/reset/rules 实测取得
BUCT_PUBKEY_B64 = (
    "BMz9oCZtEVaFTYC8X8maUe3Vdo/Ju4gQnW5j9JGHccp016ylLUl9hLOFu3N8xt3"
    "+w5Cz5C3C28/lE+8oU16x8TQ="
)


def run() -> list[str]:
    problems = []

    hw = to_halfwidth("测试密码Ａｂｃ１２３！")
    if hw != "测试密码Abc123!":
        problems.append(f"全角转半角异常: {hw!r}")

    for pwd in ["abc123", "测试密码Ａｂｃ１２３！", "p" * 64]:
        try:
            out = encrypt_password(pwd, BUCT_PUBKEY_B64)
        except Exception as e:  # noqa: BLE001
            problems.append(f"加密 {pwd[:6]!r} 失败: {e}")
            continue
        plain = to_halfwidth(pwd).encode("utf-8")
        import base64

        if len(base64.b64decode(out)) != 96 + len(plain):
            problems.append(f"长度恒等式不成立: {pwd[:6]!r}")
    return problems
