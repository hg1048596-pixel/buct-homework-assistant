# -*- coding: utf-8 -*-
"""抓真实的作业列表页与提交页（校准用）。

实测链路：
  课程页 index.jsp?courseId=X
    → 左菜单「课程作业」→ course_column_preview_transfer.jsp?tagbug=client&columnId=Y
      → 302 → /meol/common/hw/student/hwtask.jsp?tagbug=client&strStyle=new03  ← 作业列表
        → write.jsp?hwtid=Z                                                  ← 提交页

注意：hwtask.jsp 本身不带课程参数，课程由**会话上下文**决定，
所以必须先访问课程页/列页，再请求 hwtask.jsp。
"""
import json
import os
import re
import sys
import time
import urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from lxml import html as LH  # noqa: E402

from buct_assistant.cas import cas_login  # noqa: E402
from buct_assistant.platform import course_list, homework as hwmod  # noqa: E402
from buct_assistant.platform.http_client import _charset_of, decode_page  # noqa: E402
from buct_assistant.platform.urls import BASE as SITE  # noqa: E402
from buct_assistant.security import credential_store as cs  # noqa: E402

RAW = os.path.join(BASE, "calibration", "raw")
DELAY = 1.2
MAX_COURSES = int(os.environ.get("MAX_COURSES", "3"))
ONLY_IDS = [x.strip() for x in os.environ.get("ONLY_IDS", "").split(",") if x.strip()]


def get(s, url, tag=None):
    time.sleep(DELAY)
    r = s.get(url, timeout=30)
    text = decode_page(r.content, r.headers.get("Content-Type", ""))
    if tag:
        open(os.path.join(RAW, f"{tag}.html"), "wb").write(r.content)
        json.dump({"tag": tag, "url": url, "final_url": r.url, "status": r.status_code,
                   "content_type": r.headers.get("Content-Type", ""),
                   "charset": _charset_of(r.headers.get("Content-Type", "")),
                   "bytes": len(r.content), "throttled": "访问过于频繁" in text},
                  open(os.path.join(RAW, f"{tag}_meta.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    flag = " [限流!]" if "访问过于频繁" in text else ""
    print(f"   {r.status_code:4d} {len(r.content):7d}B  {tag or ''}{flag}")
    if r.status_code >= 400 or r.url != url:
        print(f"        → {r.url}")
    return text, r


def session():
    s = cas_login.cookies_to_session(cs.load_cookies())
    if not cas_login.session_alive(s):
        c = cs.load_credentials()
        s = cas_login.login(c[0], c[1])
        cs.save_cookies(cas_login.session_to_cookies(s))
    return s


def main() -> int:
    s = session()
    print("[1] 课程列表")
    text, _ = get(s, f"{SITE}/meol/lesson/blen.student.lesson.list.jsp", "hw_01_lesson_list")
    courses = course_list.parse_lesson_list(text, f"{SITE}/meol/lesson/blen.student.lesson.list.jsp")
    if ONLY_IDS:
        courses = [c for c in courses if c[0] in ONLY_IDS]
    print(f"    {len(courses)} 门课")

    for i, (cid, name, _url) in enumerate(courses[:MAX_COURSES]):
        print(f"\n[2.{i+1}] {cid} {name[:26]}")
        ctext, _ = get(s, f"{SITE}/meol/jpk/course/layout/newpage/index.jsp?courseId={cid}",
                       f"hw_2{i}_course_{cid}")
        doc = LH.fromstring(ctext)
        col_url = None
        for a in doc.xpath("//a"):
            t = re.sub(r"\s+", " ", a.text_content()).strip()
            href = a.get("href") or ""
            if "course_column_preview_transfer.jsp" not in href:
                continue
            if re.search(r"(课程作业|提交作业)", t):
                # 链接是相对 newpage 目录写的，基准要用 newpage 的 URL
                col_url = urllib.parse.urljoin(
                    f"{SITE}/meol/jpk/course/layout/newpage/index.jsp", href)
                break
        if not col_url:
            print("    未找到「课程作业」菜单")
            continue
        print(f"    作业列 → {col_url[:110]}")
        get(s, col_url, f"hw_3{i}_column")

        # 列表页（课程由会话上下文决定）
        ltext, lresp = get(s, f"{SITE}/meol/common/hw/student/hwtask.jsp?tagbug=client&strStyle=new03",
                           f"hw_4{i}_hwtask_{cid}")
        rows = []
        try:
            rows = hwmod.parse_hwtask_list(ltext, cid, name, lresp.url)
        except Exception as e:  # noqa: BLE001
            print(f"    parse_hwtask_list: {type(e).__name__}: {e}")
        print(f"    解析出 {len(rows)} 条作业")
        for h in rows[:6]:
            print(f"      · hwtid={h.hwtid:<8s} ddl={h.ddl_raw:<22s} 分={h.score_raw!r:8s} "
                  f"未交={h.unsubmitted} 可交={h.can_submit} | {h.title[:26]}")

        # 提交页结构
        if rows:
            h = rows[0]
            print(f"    提交页 write.jsp?hwtid={h.hwtid}")
            get(s, f"{SITE}/meol/common/hw/student/write.jsp?hwtid={h.hwtid}",
                f"hw_5{i}_write_{h.hwtid}")
    print("\n[OK] 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
