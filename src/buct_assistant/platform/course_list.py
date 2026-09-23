# -*- coding: utf-8 -*-
"""课程列表解析。结构未最终确证，采用宽松提取 + 严格计数校验。"""
import re
import urllib.parse

from lxml import html as LH

from .urls import BASE

COURSE_PARAMS = ("courseId", "lid", "lId")
COURSE_ID_RE = re.compile(r"(?:course_index\.jsp|course\.do)\?[^\"'\s>]*?(?:courseId|lid|Id)=(\d+)", re.I)


def parse_lesson_list(text: str, page_url: str) -> list[tuple[str, str, str]]:
    """返回 [(course_id, name, url)]。

    实测课程列表页的链接不是普通 href —— 形如
      <a href="###" onclick="window.open('../homepage/course/course_index.jsp?courseId=29997','manage_course')">基础写作（Ⅰ）</a>
    所以既要看 href，也要看 onclick。
    """
    doc = LH.fromstring(text)
    out, seen = [], set()
    for a in doc.xpath("//a"):
        href = (a.get("href") or "").strip()
        onclick = a.get("onclick") or ""
        if href.startswith(("javascript:", "#")):
            href = ""

        cid = ""
        m = COURSE_ID_RE.search(onclick or href)
        if m:
            cid = m.group(1)
        elif href:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            for p in COURSE_PARAMS:
                if q.get(p):
                    cid = q[p][0]
                    break
        if not cid:
            continue

        name = re.sub(r"\s+", " ", a.text_content()).strip()
        if not name or cid in seen or re.search(r"(logout|inform|help|personal)", name, re.I):
            continue
        seen.add(cid)
        target = (urllib.parse.urljoin(page_url, href) if href
                  else f"{BASE}/meol/homepage/course/course_index.jsp?courseId={cid}")
        out.append((cid, name, target))
    return out


def guess_course_page(course_id: str) -> str:
    return f"{BASE}/meol/homepage/course/course_index.jsp?courseId={course_id}"
