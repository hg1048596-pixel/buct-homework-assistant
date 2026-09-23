# -*- coding: utf-8 -*-
"""提交与附件上传（2026-09 实测确证）。

提交页 write.jsp?hwtid=X 的结构：
  <form name="form1" action="write.do.jsp" method="post">
    <input type="hidden" name="hwtid" value="76948">
    <input type="hidden" name="hwaid" value="NA">
    ...
    <script id="ue_IPT_BODY" name="IPT_BODY" type="text/plain"></script>
    UE.getEditor("ue_IPT_BODY", { textarea:"IPT_BODY", serverUrl:"/meol/servlet/SerUpload" })
  </form>
  <input type="button" value="提交" onclick="chk()">
  chk() 里：getNullEditorContent("IPT_BODY") 检查非空 → document.form1.submit()

附件上传（UEditor 协议，配置来自 GET /meol/servlet/SerUpload?action=config）：
  POST /meol/servlet/SerUpload?action=uploadfile   multipart，字段名 upfile
  注意：服务端 fileAllowFiles 只列了图片/视频，**没有 .pdf** —— 是否放行要实测。
"""
import json
import mimetypes
import os
import re
from dataclasses import dataclass

from lxml import html as LH

from . import urls
from .http_client import PlatformSession, decode_page


class SubmitError(Exception):
    pass


@dataclass
class WriteForm:
    """提交页上解析出来的表单事实。"""
    hwtid: str = ""
    hwaid: str = ""
    action: str = ""
    method: str = "post"
    has_body_field: bool = False     # 有没有 IPT_BODY 编辑器
    has_submit_button: bool = False
    requirement_text: str = ""
    title: str = ""
    ddl_raw: str = ""


@dataclass
class UploadResult:
    ok: bool
    url: str = ""
    raw: str = ""
    err: str = ""


@dataclass
class SubmitResult:
    ok: bool
    kind: str = ""           # ok / http_error / no_redirect / unknown
    status_code: int = 0
    location: str = ""
    body_head: str = ""
    err: str = ""


def parse_write_form(html: str) -> WriteForm:
    doc = LH.fromstring(html)
    f = WriteForm()
    f.action = "write.do.jsp"
    form = doc.xpath('//form[@name="form1"]')
    if form:
        f.action = form[0].get("action") or f.action
        f.method = (form[0].get("method") or "post").lower()
        got = form[0].xpath('.//input[@name="hwtid"]/@value')
        if got:
            f.hwtid = got[0].strip()
        got = form[0].xpath('.//input[@name="hwaid"]/@value')
        if got:
            f.hwaid = got[0].strip()
    if not f.hwtid:
        got = doc.xpath('//input[@name="hwtid"]/@value')
        f.hwtid = got[0].strip() if got else ""

    f.has_body_field = bool(doc.xpath(
        '//script[@id="ue_IPT_BODY"]|//textarea[@name="IPT_BODY"]|//div[@id="ueditor_div_IPT_BODY"]'))
    f.has_submit_button = bool(doc.xpath('//input[@value="提交"]|//button[contains(.,"提交")]'))

    vals = doc.xpath('//input[contains(@name,"_content")]/@value')
    if vals:
        best = max(vals, key=len)
        f.requirement_text = re.sub(r"<[^>]+>", "", best).strip()
    # 元数据
    from .homework import find_labeled_table, lookup
    m = find_labeled_table(doc)
    f.title = lookup(m, "title")
    f.ddl_raw = lookup(m, "ddl")
    return f


def fetch_write_form(ps: PlatformSession, hwtid: str) -> tuple[WriteForm, str]:
    """拉提交页并解析。返回 (WriteForm, 原始 html)。"""
    html = ps.get_text(urls.hw_write(hwtid))
    return parse_write_form(html), html


# ---------------- 附件上传 ----------------

def upload_file(ps: PlatformSession, local_path: str, remote_name: str = "") -> UploadResult:
    """上传附件到 SerUpload（UEditor 协议）。"""
    name = remote_name or os.path.basename(local_path)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    with open(local_path, "rb") as fh:
        data = fh.read()
    try:
        r = ps.post_multipart(
            f"{urls.SER_UPLOAD}?action=uploadfile", fields={},
            files={"upfile": (name, data, ctype)},
            headers={"Referer": urls.BASE + "/meol/common/ueditor/",
                     "X-Requested-With": "XMLHttpRequest"})
    except Exception as e:  # noqa: BLE001
        return UploadResult(False, err=f"{type(e).__name__}: {e}")

    body = decode_page(r.content, r.headers.get("Content-Type", ""))
    try:
        d = json.loads(body)
    except ValueError:
        return UploadResult(False, raw=body[:400], err=f"返回不是 JSON（HTTP {r.status_code}）")

    state = (d.get("state") or "").upper()
    if state == "SUCCESS" and d.get("url"):
        return UploadResult(True, url=d["url"], raw=body[:400])
    return UploadResult(False, raw=body[:400], err=d.get("state") or "未知错误")


def attachment_html(url: str, name: str) -> str:
    """插入正文的附件链接。老师点开就能下载。"""
    return f'<p><a href="{url}" target="_blank">{name}</a></p>'


def beautify_name(original: str, template: str, fields: dict) -> str:
    """按老师要求的命名规则重命名，例如 template='{班级}-{姓名}-{实验项目名称}'。

    模板里没提供的字段保持原样；扩展名沿用原文件。
    """
    stem, ext = os.path.splitext(original)
    if not template:
        return original
    out = template
    for k, v in fields.items():
        out = out.replace("{" + k + "}", str(v or ""))
    out = re.sub(r"\{[^}]+\}", "", out).strip("-_ ")
    return (out or stem) + ext


# ---------------- 提交 ----------------

def submit(ps: PlatformSession, hwtid: str, hwaid: str, body_html: str,
           action_path: str = "write.do.jsp") -> SubmitResult:
    """真正提交。默认不允许跟随重定向——302 就是成功讯号（实测老系统如此）。"""
    action = action_path
    if not action.startswith("http"):
        action = f"{urls.BASE}/meol/common/hw/student/{action.lstrip('/')}"
    fields = {"hwtid": hwtid, "hwaid": hwaid or "NA", "IPT_BODY": body_html}
    try:
        r = ps.post_gbk(action, fields, allow_redirects=False)
    except Exception as e:  # noqa: BLE001
        return SubmitResult(False, kind="unknown", err=f"{type(e).__name__}: {e}")

    code = r.status_code
    loc = r.headers.get("Location", "")
    head = decode_page(r.content)[:300] if r.content else ""
    if code in (301, 302, 303, 307):
        return SubmitResult(True, kind="ok", status_code=code, location=loc)
    return SubmitResult(False, kind="no_redirect", status_code=code, body_head=head,
                        err=f"HTTP {code}，未见跳转")
