# -*- coding: utf-8 -*-
"""SM2 口令加密（CAS 登录用）。

服务端要求（已实测确证）：
- 公钥：65 字节未压缩点（0x04 前缀），base64 编码，来自 /cas/api/reset/rules
- 密文：base64(C1.x ‖ C1.y ‖ C3 ‖ C2)，即 C1C3C2 顺序且**不含** 0x04 前缀
- 明文：先全角转半角再加密

gmssl 的 encrypt(mode=1) 返回值已不含 0x04 前缀，直接 base64 即可，不要再剥。
密文长度恒等式：len(cipher) == 96 + len(plain)  （C1=64B + C3=32B + 明文长度）
"""
import base64
import secrets
import unicodedata

from gmssl import func, sm2


def to_halfwidth(s: str) -> str:
    """全角转半角。NFKC 覆盖 Ａ→A、１→1、！→! 等。"""
    return unicodedata.normalize("NFKC", s)


def _secure_random_hex(n: int) -> str:
    return "".join(secrets.choice("0123456789abcdef") for _ in range(n))


# gmssl 内部用 random.choice（Mersenne Twister，非密码学安全）生成 SM2 随机数 k，
# k 可预测会导致私钥泄露，必须替换成 secrets 源。
func.random_hex = _secure_random_hex
if hasattr(sm2, "func"):
    sm2.func.random_hex = _secure_random_hex


def encrypt_password(password: str, public_key_b64: str) -> str:
    """加密口令，返回服务端要的 base64 密文。"""
    raw = base64.b64decode(public_key_b64)
    if len(raw) != 65 or raw[0] != 0x04:
        raise ValueError(f"非未压缩 SM2 公钥: len={len(raw)} head={raw[:1]!r}")
    pub_hex = raw[1:].hex()

    plain = to_halfwidth(password).encode("utf-8")
    cipher = sm2.CryptSM2(private_key="", public_key=pub_hex, mode=1).encrypt(plain)
    if not cipher:
        # KDF 输出全零时 gmssl 返回 None，概率约 2^-256，重试即可
        raise RuntimeError("SM2 encrypt 返回空，请重试")
    if len(cipher) != 96 + len(plain):
        raise RuntimeError(f"SM2 密文长度异常: {len(cipher)} != {96 + len(plain)}")
    return base64.b64encode(cipher).decode("ascii")
