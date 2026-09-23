# -*- coding: utf-8 -*-
"""北化 CAS 统一身份认证登录（2026-09 实测链路）。

流程：
  1 GET  course.buct.edu.cn/meol/homepage/common/sso_login.jsp
       → 302→303→302 落到 portal.buct.edu.cn 登录页，拿到 COOKIE_INFO cookie
  2 从 COOKIE_INFO 解出 flowKey（一次性，用完即废）
  3 GET  portal.buct.edu.cn/cas/api/reset/rules → SM2 公钥
  4 POST portal.buct.edu.cn/cas/username-password/login
       JSON {username, password: SM2密文, flowKey}；code==666666 成功
  5 GET data.service（带 ticket 的回跳）→ 建立 MEOL 会话（JSESSIONID）
  6 GET /meol/personal.do 校验登录态
"""
import datetime
import json
import urllib.parse

import requests

from ..crypto.sm2_c1c3c2 import encrypt_password
from .errors import (CasAuthFailed, CasBlocked, CasError, CasProtocolChanged,
                     FLOWKEY_RETRY_CODES, HARD_BLOCK_CODES, NO_RETRY_CODES)
SSO_ENTRY = "https://course.buct.edu.cn/meol/homepage/common/sso_login.jsp"
PORTAL = "https://portal.buct.edu.cn"
RULES_URL = f"{PORTAL}/cas/api/reset/rules"
LOGIN_URL = f"{PORTAL}/cas/username-password/login"
PERSONAL_URL = "https://course.buct.edu.cn/meol/personal.do"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _flow_key_from_cookie_info(raw_value: str) -> str:
    """COOKIE_INFO 的值是 URL 编码的 JSON，解出一层（必要时两层）。"""
    txt = urllib.parse.unquote(raw_value)
    data = None
    for _ in range(2):
        try:
            data = json.loads(txt)
            break
        except json.JSONDecodeError:
            txt = urllib.parse.unquote(txt)
    if not isinstance(data, dict):
        raise CasProtocolChanged("C00", "COOKIE_INFO 不是合法 JSON，CAS 可能已改版")
    fk = (data.get("data") or {}).get("flowKey")
    if not fk:
        raise CasProtocolChanged("C01", f"COOKIE_INFO 中无 flowKey: keys={list(data.keys())}")
    return fk


def _extract_flow_key(session: requests.Session) -> str:
    for c in session.cookies:
        if c.name == "COOKIE_INFO":
            return _flow_key_from_cookie_info(c.value)
    raise CasProtocolChanged("C02", "未取到 COOKIE_INFO cookie（未落到 portal 登录页？）")


def _get_public_key(session: requests.Session) -> str:
    r = session.get(RULES_URL, timeout=30, headers={"Referer": f"{PORTAL}/cas/login"})
    try:
        data = r.json()
    except ValueError as e:
        raise CasProtocolChanged("C03", f"reset/rules 返回非 JSON: {r.text[:120]!r}") from e
    enc = (data.get("data") or {}).get("encrypt") or {}
    if enc.get("algorithm") != "sm2" or not enc.get("publicKey"):
        raise CasProtocolChanged("C04", f"reset/rules 结构变化: {data}")
    return enc["publicKey"]


def _login_once(session: requests.Session, username: str, password: str, log) -> str:
    """单次尝试，成功返回 data.service 回跳地址。"""
    # 步骤 1：走到 portal 登录页，拿 flowKey
    session.get(SSO_ENTRY, timeout=30)
    flow_key = _extract_flow_key(session)
    log(f"flowKey: {flow_key[:12]}...")

    # 步骤 2：公钥
    pubkey = _get_public_key(session)

    # 步骤 3：登录
    payload = {"username": username, "password": encrypt_password(password, pubkey),
               "flowKey": flow_key}
    r = session.post(LOGIN_URL, json=payload, timeout=30,
                     headers={"Referer": f"{PORTAL}/cas/login"})
    try:
        data = r.json()
    except ValueError as e:
        raise CasProtocolChanged("C05", f"登录返回非 JSON: {r.text[:160]!r}") from e

    code = data.get("code")
    if code == 666666:
        service = (data.get("data") or {}).get("service")
        if not service:
            raise CasProtocolChanged("C06", f"登录成功但缺 data.service: {data}")
        return service
    if code in HARD_BLOCK_CODES:
        raise CasBlocked(code, HARD_BLOCK_CODES[code])
    if code in NO_RETRY_CODES:
        raise CasAuthFailed(code, NO_RETRY_CODES[code])
    if code in FLOWKEY_RETRY_CODES:
        raise CasError(code, f"flowKey 失效({code})")
    raise CasProtocolChanged(code, f"未知登录响应: {data}")


def _verify_meol(session: requests.Session, log) -> str:
    """校验是否真的建立了登录态。

    判据用「有没有落回登录页」而不是「页面上有没有某个词」——后者太脆：
    实测 personal.do 里既没有『注销』也没有『个人首页』，但会话其实是好的。
    真正可靠的信号是：受保护页面 personal.do 返回了 200 且没有渲染出登录表单。
    """
    from ..platform.http_client import decode_page

    r = session.get(PERSONAL_URL, timeout=30)
    text = decode_page(r.content, r.headers.get("Content-Type", ""))
    if "/cas/login" in r.url or "loginCheck" in r.url:
        raise CasError("V0", f"登录态未建立，被踢回登录页: {r.url}")
    if "IPT_LOGINPASSWORD" in text or 'id="login"' in text:
        raise CasError("V0b", "personal.do 返回了登录表单，会话未建立")
    if "personal.do" in r.url:
        return f"personal.do 可达（{r.status_code}，{len(r.content)}B）"
    raise CasProtocolChanged("V1", f"未预期页面: {r.url}")


def login(username: str, password: str, session: requests.Session | None = None,
          log=print) -> requests.Session:
    """完整登录（flowKey 失效自动重取重试一次）。成功返回已建立 MEOL 会话的 Session。"""
    odd = [c for c in password if ord(c) > 126 or ord(c) < 32]
    if odd:
        # 学校密码不含非 ASCII 字符；出现基本是输入法把字母转成了汉字。
        # 直接拦下，避免无谓的失败次数把账号打到锁定。
        raise CasBlocked(
            "P001",
            f"本地保存的密码含 {len(odd)} 个非 ASCII 字符，疑似输入法转换所致。"
            "请重新运行 set-credentials（先把输入法切到英文），本次不发登录请求以免触发锁定")

    s = session or requests.Session()
    s.headers["User-Agent"] = UA

    try:
        service = _login_once(s, username, password, log)
    except CasError as e:
        if e.code in FLOWKEY_RETRY_CODES:
            log(f"flowKey 失效({e.code})，重取后重试一次")
            service = _login_once(s, username, password, log)
        else:
            raise

    # 步骤 5：跟随带 ticket 的回跳，建立 MEOL 会话
    if not service.startswith("http"):
        service = urllib.parse.urljoin(PORTAL + "/", service)
    r = s.get(service, timeout=30)
    log(f"ticket 回跳: {r.status_code} → {r.url}")

    who = _verify_meol(s, log)
    log(f"登录成功（页面命中关键字: {who}）")
    return s


def session_to_cookies(session: requests.Session) -> list[dict]:
    out = []
    for c in session.cookies:
        out.append({"name": c.name, "value": c.value, "domain": c.domain,
                    "path": c.path, "secure": bool(c.secure),
                    "expires": c.expires})
    return out


def cookies_to_session(cookies: list[dict], session: requests.Session | None = None) -> requests.Session:
    s = session or requests.Session()
    s.headers["User-Agent"] = UA
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
    return s


def session_alive(session: requests.Session) -> bool:
    """探活：personal.do 正常且未落回登录页视为存活。"""
    from ..platform.http_client import decode_page

    try:
        r = session.get(PERSONAL_URL, timeout=20, allow_redirects=True)
        if "/cas/login" in r.url or "loginCheck" in r.url:
            return False
        text = decode_page(r.content, r.headers.get("Content-Type", ""))
        if "IPT_LOGINPASSWORD" in text:
            return False
        return "personal.do" in r.url
    except requests.RequestException:
        return False


LEGACY_LOGIN = "https://course.buct.edu.cn/meol/loginCheck.do"


def login_legacy(username: str, password: str, session: requests.Session | None = None,
                 log=print) -> requests.Session:
    """老版直连登录（POST /meol/loginCheck.do，字段 IPT_LOGINUSERNAME/IPT_LOGINPASSWORD）。

    平台上这个表单现在仍然存在（menuId=1063），但很可能已改成跳到统一认证。
    这里只做一次尝试：若被重定向到 CAS 或返回登录表单，就说明此路不通，由调用方改用 CAS。
    注意：密码以明文表单提交（和浏览器里手动登录一样，HTTPS 保护），不像 CAS 那样做 SM2 加密。
    """
    import re

    from ..platform.http_client import decode_page

    s = session or requests.Session()
    s.headers["User-Agent"] = UA
    r = s.get(LEGACY_LOGIN, timeout=30)
    if "/cas/login" in r.url:
        raise CasProtocolChanged("L0", "loginCheck.do 已重定向到统一认证，老版登录不可用")
    text = decode_page(r.content, r.headers.get("Content-Type", ""))
    m = re.search(r'name="logintoken"\s+value="([^"]*)"', text)
    token = m.group(1) if m else ""

    r2 = s.post(LEGACY_LOGIN, timeout=30, allow_redirects=True, data={
        "logintoken": token, "IPT_LOGINUSERNAME": username, "IPT_LOGINPASSWORD": password})
    if "/cas/login" in r2.url:
        raise CasProtocolChanged("L1", "提交后跳到统一认证，老版登录不可用")
    text2 = decode_page(r2.content, r2.headers.get("Content-Type", ""))
    if "IPT_LOGINPASSWORD" in text2:
        raise CasAuthFailed("L2", "老版登录返回登录页（用户名或密码错误，或该入口已停用）")
    who = _verify_meol(s, log)
    log(f"老版直连登录成功（命中关键字: {who}）")
    return s


def now_str() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")
