# -*- coding: utf-8 -*-
"""按真实导航走一遍作业链路，把每一层页面都 dump 下来。

真实路径（实测）：
  课程列表 blen.student.lesson.list.jsp
  → 课程页 homepage/course/course_index.jsp?courseId=X（左菜单在页内）
  → 作业列 course_column_preview_transfer.jsp?tagbug=client&columnId=Y（菜单文字含「作业」）
  → 作业详情（在列页面里继续找）

带请求间隔，避免触发「访问过于频繁」。
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

import requests  # noqa: E402
from lxml import html as LH  # noqa: E402

from buct_assistant.cas import cas_login  # noqa: E402
from buct_assistant.platform import course_list  # noqa: E402
from buct_assistant.platform.http_client import _charset_of, decode_page  # noqa: E402
from buct_assistant.platform.urls import BASE as SITE  # noqa: E402
from buct_assistant.security import credential_store as cs  # noqa: E402

RAW = os.path.join(BASE, "calibration", "raw")
DELAY = 1.5           # 每次请求之间的间隔（实测 0.5s 间隔会触发限流）
MAX_COURSES = int(os.environ.get("MAX_COURSES", "4"))
HW_MENU_RE = re.compile(r"(课程作业|提交作业|作业|homework)", re.I)
NOT_HW_RE = re.compile(r"(小测|测试|试题|试卷|问卷|题库)")


def get(session, url, tag=None, save=True):
    time.sleep(DELAY)
    r = session.get(url, timeout=30)
    text = decode_page(r.content, r.headers.get("Content-Type", ""))
    throttled = "访问过于频繁" in text
    if save and tag:
        with open(os.path.join(RAW, f"{tag}.html"), "wb") as f:
            f.write(r.content)
        json.dump({
            "tag": tag, "url": url, "final_url": r.url, "status": r.status_code,
            "content_type": r.headers.get("Content-Type", ""),
            "charset": _charset_of(r.headers.get("Content-Type", "")),
            "bytes": len(r.content), "throttled": throttled,
            "dumped_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }, open(os.path.join(RAW, f"{tag}_meta.json"), "w", encoding="utf-8"),
            ensure_ascii=False, indent=2)
    flag = " [限流!]" if throttled else ""
    print(f"   {r.status_code:4d} {len(r.content):7d}B  {'':2s}{tag or url[:60]}{flag}")
    return text, r


def main() -> int:
    os.makedirs(RAW, exist_ok=True)
    cred = cs.load_credentials()
    cookies = cs.load_cookies()
    if cookies:
        s = cas_login.cookies_to_session(cookies)
        if cas_login.session_alive(s):
            print("[i] 复用已保存会话")
        else:
            print("[i] 会话失效，重新登录")
            s = cas_login.login(cred[0], cred[1]) if cred else None
            if not s:
                print("[FAIL] 无凭据")
                return 1
            cs.save_cookies(cas_login.session_to_cookies(s))
    elif cred:
        s = cas_login.login(cred[0], cred[1])
        cs.save_cookies(cas_login.session_to_cookies(s))
    else:
        print("[FAIL] 请先 set-credentials")
        return 1

    print("\n[1] 课程列表")
    text, _ = get(s, f"{SITE}/meol/lesson/blen.student.lesson.list.jsp", "h_01_lesson_list")
    courses = course_list.parse_lesson_list(text, f"{SITE}/meol/lesson/blen.student.lesson.list.jsp")
    print(f"   共 {len(courses)} 门课")
    for cid, name, _ in courses[:MAX_COURSES]:
        print(f"     - {cid} {name[:30]}")

    for i, (cid, name, url) in enumerate(courses[:MAX_COURSES]):
        print(f"\n[2.{i+1}] 课程 {cid} {name[:26]}")
        ctext, _ = get(s, url, f"h_10_course_{cid}")
        cdoc = LH.fromstring(ctext)
        # 左菜单里找作业列
        hw_links = []
        for a in cdoc.xpath("//a[@href]"):
            t = re.sub(r"\s+", " ", a.text_content()).strip()
            href = a.get("href") or ""
            if "course_column_preview_transfer.jsp" not in href:
                continue
            if HW_MENU_RE.search(t) and not NOT_HW_RE.search(t):
                hw_links.append((t, urllib.parse.urljoin(url, href)))
        seen_l = set()
        for t, u in hw_links:
            if u in seen_l:
                continue
            seen_l.add(u)
            col = re.search(r"columnId=(\d+)", u)
            tag = f"h_2{i}_col_{col.group(1) if col else 'x'}"
            print(f"   菜单「{t[:16]}」→ columnId={col.group(1) if col else '?'}")
            col_text, _ = get(s, u, tag)
            # 列页面里继续找作业详情
            cdoc2 = LH.fromstring(col_text)
            subs = []
            for a2 in cdoc2.xpath("//a[@href]"):
                t2 = re.sub(r"\s+", " ", a2.text_content()).strip()
                h2 = a2.get("href") or ""
                if re.search(r"(hwtask|hwtid|write\.jsp|hwStuSubmit|vwork|taskanswer)", h2, re.I) \
                        or re.search(r"(作业|实验报告|习题)", t2):
                    subs.append((t2, urllib.parse.urljoin(u, h2)))
            print(f"     列页里有 {len(subs)} 个候选作业链接")
            for j, (t2, u2) in enumerate(subs[:5]):
                print(f"       - {t2[:30]} → {u2[:100]}")
                get(s, u2, f"h_3{i}_{j}")
    print("\n[OK] 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
