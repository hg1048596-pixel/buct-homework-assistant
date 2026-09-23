# -*- coding: utf-8 -*-
"""作业页解析。

两种布局：
1. vworkpage（当前主力，用户截图确证）：课程页内的「查看作业任务」页，
   信息以「标签 / 值」表格呈现（标题、截止时间、开分方式、作业内容）。
   用工整的标签定位而非列下标——布局微调不影响解析。
2. 老版 hwtask.jsp：table.valuelist 按列下标取值（备用分支）。
"""
import re
import urllib.parse

from lxml import html as LH

from .models import TZ, Homework

LABELS = {
    "title": ("标题", "作业标题", "名称"),
    "ddl": ("截止时间", "截止日期", "结束时间"),
    "scoring": ("开分方式", "评分方式", "分数"),
    "content": ("作业内容", "题目内容", "内容要求"),
}

DDL_RE = re.compile(
    r"(\d{4})\s*[年\-/]\s*(\d{1,2})\s*[月\-/]\s*(\d{1,2})\s*日?\s*"
    r"(\d{1,2})\s*[:：]\s*(\d{2})(?:\s*[:：]\s*(\d{2}))?")

UNSUBMITTED_MARKS = ("未提交", "尚未提交", "未做", "未完成")
SUBMITTED_MARKS = ("已提交", "已交", "已完成")


def text_of(el) -> str:
    return re.sub(r"\s+", " ", el.text_content() if el is not None else "").strip()


def parse_ddl(raw: str):
    m = DDL_RE.search(raw or "")
    if not m:
        return None
    y, mo, d, h, mi, s = m.groups()
    return __import__("datetime").datetime(
        int(y), int(mo), int(d), int(h), int(mi), int(s or 0), tzinfo=TZ)


def _strip_label(s: str) -> str:
    return s.replace("：", "").replace(":", "").replace("　", "").strip()


def find_labeled_table(doc) -> dict[str, str]:
    """在整页里找「标签单元格 → 值单元格」的映射。"""
    out: dict[str, str] = {}
    for tr in doc.xpath("//tr"):
        cells = tr.xpath("./td|./th")
        if len(cells) < 2:
            continue
        key = _strip_label(text_of(cells[0]))
        if not key or len(key) > 12:
            continue
        val = text_of(cells[1])
        if val or True:
            out.setdefault(key, val)
    return out


def lookup(mapping: dict[str, str], kind: str) -> str:
    for name in LABELS[kind]:
        if name in mapping:
            return mapping[name]
        for k, v in mapping.items():
            if name in k:
                return v
    return ""


def extract_requirement_html(doc) -> str:
    """取「作业内容」的富文本。

    实测：页面把要求正文放在 `<input id="{n}_content" name="{n}_content" value="<转义HTML>">`
    里，再用 `<iframe id="_rtf_content{n}">` 显示出来（text_content 取不到属性值，
    所以只读表格文本会得到空字符串）。
    """
    vals = doc.xpath('//input[contains(@name,"_content")]/@value')
    best = ""
    for v in vals:
        if v and len(v.strip()) > len(best.strip()):
            best = v
    if best.strip():
        return best
    # 兜底：iframe 的备用内容或直接写在单元格里的富文本
    for el in doc.xpath('//div[contains(@class,"rtf") or contains(@class,"content")]'):
        html = "".join(LH.tostring(c, encoding="unicode") for c in el.iterchildren())
        if html.strip():
            return html
    return ""


def html_to_text(html: str) -> str:
    if not html:
        return ""
    txt = re.sub(r"<(br|/p|/div|/tr|/h\d)[^>]*>", "\n", html, flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = (txt.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
              .replace("&quot;", '"').replace("&#39;", "'").replace("&amp;", "&"))
    txt = re.sub(r"[ \t　]+", " ", txt)
    return re.sub(r"\n{2,}", "\n", txt).strip()


def parse_vworkpage(text: str, course_id: str, course_name: str, url: str,
                    page_title: str = "") -> Homework | None:
    """解析「查看作业任务」页（即 write.jsp?hwtid=）。返回 Homework；不是作业页则 None。"""
    doc = LH.fromstring(text)
    mapping = find_labeled_table(doc)

    title = lookup(mapping, "title")
    ddl_raw = lookup(mapping, "ddl")
    scoring = lookup(mapping, "scoring")
    content_html = extract_requirement_html(doc)

    if not title and not ddl_raw:
        return None  # 不是作业详情页（可能是列表页）

    # hwtid：URL 参数 → 表单隐藏域
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    hwtid = (q.get("hwtid") or q.get("hwtId") or q.get("hwtID") or [""])[0]
    if not hwtid:
        for name in ("hwtid", "hwtId", "hwtID", "hwtTid"):
            got = doc.xpath(f'//input[@name="{name}"]/@value')
            if got:
                hwtid = got[0].strip()
                break

    # 提交表单里的 hwaid（再提交时是真实值，首次是 NA）
    hwaid = ""
    got = doc.xpath('//input[@name="hwaid"]/@value')
    if got:
        hwaid = got[0].strip()

    # 是否已提交：有答案输入框 = 可以交
    has_answer_box = bool(doc.xpath('//script[@id="ue_IPT_BODY"]'
                                    '|//textarea[contains(@name,"IPT_BODY")]'
                                    '|//div[@id="ueditor_div_IPT_BODY"]'))
    has_submit_btn = bool(doc.xpath('//input[@value="提交"]|//button[contains(.,"提交")]'))

    if has_answer_box:
        unsubmitted, can_submit, conf = True, True, "high"
    elif has_submit_btn:
        unsubmitted, can_submit, conf = True, True, "low"
    else:
        unsubmitted, can_submit, conf = False, False, "low"

    return Homework(
        course_id=course_id, course_name=course_name,
        hwtid=hwtid or f"unk-{abs(hash(title)) % 100000}",
        title=title, ddl=parse_ddl(ddl_raw), ddl_raw=ddl_raw,
        scoring_method=scoring, content_html=content_html,
        content_text=html_to_text(content_html),
        unsubmitted=unsubmitted, can_submit=can_submit, confidence=conf,
        layout="vworkpage", url=url)


def parse_hwtask_list(text: str, course_id: str, course_name: str,
                      base_url: str) -> list[Homework]:
    """老版 hwtask.jsp 的作业列表。

    表头（实测，两种 strStyle 都一样）：
      标题 | 截止时间 | 分数 | 发布人 | 统计信息 | 提交作业 | 查看结果 | 优秀作品
    判定规则（实测确证）：
      - td[5]「提交作业」里有 write.jsp 链接 → 现在可以提交（can_submit）
      - td[6]「查看结果」里有 taskanswer.jsp 链接 → 已经交过（有答案/结果了）
      - td[6] 文本含「未提交」 → 明确没交
    """
    doc = LH.fromstring(text)
    rows = []
    tables = doc.xpath('//table[contains(@class,"valuelist")]')
    if not tables:
        raise ValueError("no valuelist")
    for tr in tables[0].xpath(".//tr"):
        tds = tr.xpath("./td")
        if len(tds) < 7:
            continue
        a = tds[0].xpath('.//a[contains(@href,"hwt")]')
        if not a:
            continue
        href = a[0].get("href") or ""
        m = re.search(r"hwt[iI]d=(\d+)", href)
        if not m:
            continue

        ddl_raw = text_of(tds[1])
        result_cell = tds[6]
        result_text = text_of(result_cell)
        result_href = " ".join(a2.get("href") or "" for a2 in result_cell.xpath(".//a"))
        submit_href = " ".join(a2.get("href") or "" for a2 in tds[5].xpath(".//a"))

        can_submit = "write.jsp" in submit_href or bool(tds[5].xpath(".//a"))
        has_answer = "taskanswer" in result_href
        says_unsub = any(k in result_text for k in ("未提交", "尚未提交"))
        says_sub = any(k in result_text for k in ("已提交", "已交"))

        if says_unsub:
            unsubmitted, conf = True, "high"
        elif has_answer or says_sub:
            unsubmitted, conf = False, "high"
        elif can_submit:
            unsubmitted, conf = True, "high"   # 能提交 = 还没交
        else:
            unsubmitted, conf = True, "low"    # 不能交也没结果链接 → 交人工确认

        ddl = parse_ddl(ddl_raw)
        # 逾期且不能提交，属于正常组合，不该留成低置信
        if conf == "low" and ddl and ddl < __import__("datetime").datetime.now(TZ):
            conf = "high"

        rows.append(Homework(
            course_id=course_id, course_name=course_name, hwtid=m.group(1),
            title=text_of(a[0]), ddl=ddl, ddl_raw=ddl_raw,
            score_raw=text_of(tds[2]), publisher=text_of(tds[3]),
            unsubmitted=unsubmitted, can_submit=can_submit,
            confidence=conf, layout="hwtask",
            url=urllib.parse.urljoin(base_url, href)))
    return rows
