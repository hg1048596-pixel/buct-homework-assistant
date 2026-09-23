# -*- coding: utf-8 -*-
"""CAS 错误码与异常类型（2026-09 实测 + go-buct-course 参照）。"""

HARD_BLOCK_CODES = {
    160001: "账号已开启 MFA 二次验证，本工具不支持自动处理",
    160002: "服务端要求图形验证码，本工具不做识别",
    180028: "登录失败次数过多，账号临时锁定 30 分钟",
    180029: "账号已锁死，请联系学校",
}
NO_RETRY_CODES = {170002: "用户名或密码错误"}
FLOWKEY_RETRY_CODES = {180046, 180076}  # flowKey 无效/已用：重取后可再试一次


class CasError(Exception):
    def __init__(self, code, msg):
        self.code = code
        self.msg = msg
        super().__init__(f"[{code}] {msg}")


class CasAuthFailed(CasError):
    """用户名或密码错误——绝不重试，避免触发锁定。"""


class CasBlocked(CasError):
    """MFA / 图形验证码 / 锁定——熔断，转人工或 Cookie 导入。"""


class CasProtocolChanged(CasError):
    """响应非预期（非 JSON、字段缺失等）——视为平台改版信号。"""
