# -*- coding: utf-8 -*-
"""页面结构分析器：替代手工 F12 抓包。

对 calibration/raw/ 下 dump 到的每个页面做结构化体检，直接读出：
  - 表单的 action / method / enctype 与全部字段名（提交接口就藏在这里）
  - 富文本编辑器（CKEditor）的 textarea 名称与配置
  - 附件上传接口与字段（SerUpload / Filedata / folder / fileext）
  - iframe 结构
  - 用作业解析器试跑一遍，验证「标签定位」规则与真实页面是否对得上

用法: python tools/analyze_pages.py [文件名关键字]
"""
import glob
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from lxml import html as LH  # noqa: E402

from buct_assistant.platform import homework as hwmod  # noqa: E402
from buct_assistant.platform.http_client import _charset_of, decode_page  # noqa: E402

RAW = os.path.join(BASE, "calibration", "raw")

UPLOAD_MARKS = ("SerUpload", "Filedata", "folder=", "fileext", "ShockwaveFlash", "uploadImage",
                "uploadFile", "uploadUrl", "filemanager", "connector")

INTERESTING = (
    re.compile(r"(hwtask|write\.jsp|write\.do|hwStuSubmit|vworkpage|sso_login|loginCheck)", re.I),
    re.compile(r"(action\s*[:=]\s*[\"']?[^\"'\s>]*)", re.I),
    re.compile(r"([A-Za-z0-9_]*[Uu]pload[A-Za-z0-9_]*\s*[:=]\s*[\"'][^\"']{0,80}[\"'])"),
)


def h(text: str, n: int = 100) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def analyze(path: str) -> None:
    raw = open(path, "rb").read()
    # 平台不同页面编码不同（首页 UTF-8、课程页 GBK），按声明解，没有声明就嗅探
    text = decode_page(raw)
    meta_path = path.replace(".html", "_meta.json")
    ctype = ""
    if os.path.exists(meta_path):
        import json
        ctype = json.load(open(meta_path, encoding="utf-8")).get("content_type", "")
    name = os.path.basename(path)
    print("=" * 78)
    print(f"文件: {name}   {len(raw)}B   charset={_charset_of(ctype) or '（嗅探）'}")
    try:
        doc = LH.fromstring(text)
    except Exception as e:  # noqa: BLE001
        print(f"  [解析失败] {e}")
        return

    t = doc.xpath("//title/text()")
    print(f"  标题: {h(t[0].strip(), 80) if t else '—'}")

    # --- 表单 ---
    forms = doc.xpath("//form")
    if not forms:
        print("  表单: 无")
    for i, f in enumerate(forms, 1):
        print(f"  表单#{i}: action={f.get('action')!r} method={f.get('method')!r} "
              f"enctype={f.get('enctype')!r} name={f.get('name')!r} id={f.get('id')!r}")
        for el in f.xpath(".//input|.//select|.//textarea|.//button"):
            tag = el.tag
            if tag == "textarea":
                print(f"      [{tag}] name={el.get('name')!r} id={el.get('id')!r} "
                      f"rows={el.get('rows')!r} class={h(el.get('class') or '', 40)!r}")
            else:
                print(f"      [{tag}] name={el.get('name')!r} type={el.get('type')!r} "
                      f"value={h(el.get('value') or '', 30)!r} id={el.get('id')!r}")

    # --- 编辑器 ---
    ck = [s.get("src") for s in doc.xpath("//script[@src]") if s.get("src") and "ckeditor" in s.get("src").lower()]
    if ck:
        print(f"  CKEditor: {ck[:2]}")

    # --- 内嵌 JS 里的接口线索 ---
    js = " ".join(doc.xpath("//script[not(@src)]/text()"))
    hits = set()
    for pat in INTERESTING:
        for m in pat.finditer(js + text):
            g = m.group(0 if m.lastindex is None else 1)
            if g and len(g) < 120:
                hits.add(g.strip())
    for kw in UPLOAD_MARKS:
        for m in re.finditer(r"[\"'][^\"']{0,90}" + re.escape(kw) + r"[^\"']{0,90}[\"']", text):
            hits.add(h(m.group(0), 110))
    if hits:
        print("  JS/HTML 里的接口线索:")
        for s in sorted(hits)[:14]:
            print(f"      {h(s, 110)}")

    # --- iframe ---
    for fr in doc.xpath("//iframe[@src]|//frame[@src]"):
        print(f"  iframe: name={fr.get('name')!r} src={h(fr.get('src') or '', 100)!r}")

    # --- 用作业解析器试跑（验证标签规则）---
    hw = hwmod.parse_vworkpage(text, "probe", "probe", f"file://{name}")
    if hw:
        print("  【解析器试跑】成功：")
        print(f"      标题={hw.title!r}")
        print(f"      截止={hw.ddl_raw!r} → {hw.ddl}")
        print(f"      开分方式={hw.scoring_method!r}")
        print(f"      hwtid={hw.hwtid!r}  未提交={hw.unsubmitted} 可提交={hw.can_submit} 置信={hw.confidence}")
        print(f"      要求正文={h(hw.content_text, 160)!r}")
    else:
        print("  【解析器试跑】未识别为作业页（可能是列表页或主页）")

    # --- 标签映射（看真实标签长什么样）---
    mapping = hwmod.find_labeled_table(doc)
    keys = [k for k in mapping if k][:18]
    if keys:
        print(f"  页面「标签→值」键: {keys}")


def main() -> int:
    pattern = sys.argv[1] if len(sys.argv) > 1 else ""
    files = sorted(glob.glob(os.path.join(RAW, "*.html")))
    if pattern:
        files = [f for f in files if pattern in os.path.basename(f)]
    if not files:
        print(f"[--] {RAW} 下没有 html，请先运行 tools/dump_pages.py")
        return 1
    for f in files:
        analyze(f)
    print("=" * 78)
    print(f"共分析 {len(files)} 个页面。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
