# -*- coding: utf-8 -*-
"""登录流程离线测试：mock 会话，不发任何真实请求。

覆盖 2026-10 认证迁移后的路径：
  1. 新统一认证端点（experimental-auth-endpoint，SM2 + CAS API）成功
  2. 密码错误（170002）→ CasAuthFailed 直接抛出，不触发 legacy 重试（保护锁定计数）
  3. 硬阻断（160001 MFA）→ CasBlocked 直接抛出
  4. 新端点协议变化（非 JSON）→ 自动回退 THEOL legacy 直连并成功
"""
import sys
import unittest

sys.path.insert(0, "src")

from buct_assistant.cas import cas_login
from buct_assistant.cas.errors import CasAuthFailed, CasBlocked

# 实测抓取的 SM2 公钥（公开值，非秘密）
REAL_PUBKEY = ("BMz9oCZtEVaFTYC8X8maUe3Vdo/Ju4gQnW5j9JGHccp016ylLUl9h"
               "LOFu3N8xt3+w5Cz5C3C28/lE+8oU16x8TQ=")
SERVICE_URL = ("https://course.buct.edu.cn/meol/homepage/common/sso_login.jsp"
               "?ticket=ST-123456")
PERSONAL_URL = "https://course.buct.edu.cn/meol/personal.do"
EXP_LOGIN_URL = "https://experimental-auth-endpoint.buct.edu.cn/cas/username-password/login"


class FakeCookie:
    def __init__(self, name, value=""):
        self.name = name
        self.value = value
        self.domain = ""
        self.path = "/"
        self.secure = False
        self.expires = None


class FakeResponse:
    def __init__(self, url, text="", status_code=200, json_data=None):
        self.url = url
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.history = []
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    """按 URL 子串路由到脚本的假会话。script: [(match, FakeResponse|callable)]"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []          # (method, url, data)
        self.headers = {}
        self.cookies = []

    def _route(self, url, data):
        for match, resp in self.script:
            if match in url:
                if callable(resp):
                    return resp(data)
                return resp
        raise AssertionError("未脚本化的请求: " + url[:120])

    def get(self, url, timeout=None, allow_redirects=True, **kw):
        self.calls.append(("GET", url, None))
        return self._route(url, None)

    def post(self, url, timeout=None, data=None, json=None, **kw):
        self.calls.append(("POST", url, json if json is not None else data))
        return self._route(url, json if json is not None else data)


def personal_page():
    return FakeResponse(PERSONAL_URL, "<html><body>个人中心</body></html>")


def rules_resp():
    return FakeResponse(
        url="https://experimental-auth-endpoint.buct.edu.cn/cas/api/reset/rules",
        json_data={"code": 200, "msg": "操作成功", "data": {
            "encrypt": {"algorithm": "sm2", "publicKey": REAL_PUBKEY}}})


def exp_login_resp(json_data=None, text=""):
    return FakeResponse(url=EXP_LOGIN_URL, json_data=json_data, text=text)


class TestLoginExperimentalSuccess(unittest.TestCase):
    def test_success_via_experimental(self):
        login_post = {}

        def login_handler(data):
            login_post.update(data or {})
            return exp_login_resp({"code": 666666, "data": {"service": SERVICE_URL}})

        s = FakeSession([
            ("sso_login.jsp", FakeResponse(url=cas_login.SSO_ENTRY,
                                           text="<html>redirect</html>")),
            ("reset/rules", rules_resp()),
            ("username-password/login", login_handler),
            ("ticket=", personal_page()),
            ("personal.do", personal_page()),
        ])
        out = cas_login.login("2025090132", "praw123", session=s, log=lambda *a: None)

        self.assertIs(out, s)
        kinds = [(m, u) for m, u, _ in s.calls]
        self.assertEqual(kinds[0], ("GET", cas_login.SSO_ENTRY))
        self.assertTrue(any("reset/rules" in u for m, u in kinds), "应先取公钥")
        self.assertTrue(any("username-password/login" in u for m, u in kinds))
        # payload 断言：无 flowKey（新端点不再下发），密码已 SM2 加密
        self.assertNotIn("flowKey", login_post)
        self.assertEqual(login_post.get("username"), "2025090132")
        pwd = login_post.get("password", "")
        self.assertNotEqual(pwd, "praw123", "密码必须是密文")
        import base64 as b64
        raw = b64.b64decode(pwd)   # C1(64) + C3(32) + C2(len(plain))，base64 编码
        self.assertEqual(len(raw), 96 + len("praw123"))


class TestLoginFailurePropagation(unittest.TestCase):
    def test_wrong_password_propagates_without_legacy(self):
        s = FakeSession([
            ("sso_login.jsp", FakeResponse(url=cas_login.SSO_ENTRY, text="x")),
            ("reset/rules", rules_resp()),
            ("username-password/login",
             exp_login_resp({"code": 170002, "msg": "用户名或密码错误"})),
        ])
        with self.assertRaises(CasAuthFailed):
            cas_login.login("2025090132", "wrongpw", session=s, log=lambda *a: None)
        # 密码错误绝不触发 legacy 重试（避免消耗锁定计数）
        self.assertFalse(any("loginCheck.do" in u for m, u, _ in s.calls))

    def test_hard_block_propagates(self):
        s = FakeSession([
            ("sso_login.jsp", FakeResponse(url=cas_login.SSO_ENTRY, text="x")),
            ("reset/rules", rules_resp()),
            ("username-password/login",
             exp_login_resp({"code": 160001, "msg": "MFA"})),
        ])
        with self.assertRaises(CasBlocked):
            cas_login.login("2025090132", "praw123", session=s, log=lambda *a: None)


class TestLoginLegacyFallback(unittest.TestCase):
    def test_falls_back_to_legacy_on_protocol_change(self):
        legacy_post = {}

        def legacy_handler(data):
            if data is None:            # GET：返回登录表单页
                return legacy_page
            legacy_post.update(data or {})
            return personal_page()      # POST：模拟登录成功

        legacy_page = FakeResponse(
            url=cas_login.LEGACY_LOGIN,
            text="<html><form action=\"/meol/loginCheck.do\">"
                 "<input name=\"logintoken\" value=\"1790944292628\">"
                 "<input name=\"IPT_LOGINUSERNAME\" id=\"userName\">"
                 "<input name=\"IPT_LOGINPASSWORD\" id=\"passWord\" type=\"password\">"
                 "</form></html>")

        s = FakeSession([
            # 实验端点：公钥正常，但登录返回非 JSON（协议变化信号）
            ("sso_login.jsp", FakeResponse(url=cas_login.SSO_ENTRY, text="x")),
            ("reset/rules", rules_resp()),
            ("username-password/login",
             exp_login_resp(text="<html>Request Error!</html>")),
            # legacy 直连：表单 → 提交成功
            ("loginCheck.do", legacy_handler),
            ("ticket=", personal_page()),
            ("personal.do", personal_page()),
        ])
        out = cas_login.login("2025090132", "praw123", session=s, log=lambda *a: None)
        self.assertIs(out, s)
        # legacy POST 字段与 2026-10 表单一致
        self.assertIn("IPT_LOGINUSERNAME", legacy_post)
        self.assertEqual(legacy_post["IPT_LOGINUSERNAME"], "2025090132")
        self.assertEqual(legacy_post.get("IPT_LOGINPASSWORD"), "praw123")
        self.assertIn("logintoken", legacy_post)
        # 实验端点先于 legacy 被尝试
        first_login = next(u for m, u, _ in s.calls if "username-password/login" in u)
        self.assertIn("experimental-auth-endpoint", first_login)


if __name__ == "__main__":
    unittest.main()
