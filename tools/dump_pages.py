# -*- coding: utf-8 -*-
"""阶段 1 校准工具：登录后把关键页面原始字节 dump 到 calibration/raw/。

保存的是响应原始字节（平台是 GBK，不做解码），另写同名 _meta.json 记录请求信息。
"""
import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from buct_assistant.cas import cas_login  # noqa: E402
from buct_assistant.platform.http_client import _charset_of, decode_page  # noqa: E402
from buct_assistant.security import credential_store as cs  # noqa: E402

RAW = os.path.join(BASE, "calibration", "raw")

COURSE = "https://course.buct.edu.cn"

# 三门已知课程（来自用户截图）+ 基础页
TARGETS = [
    ("00_index", "https://course.buct.edu.cn/meol/index.do"),
    ("01_personal", cas_login.PERSONAL_URL),
    ("02_lesson_list", f"{COURSE}/meol/lesson/blen.student.lesson.list.jsp"),
    ("03_logincheck", f"{COURSE}/meol/loginCheck.do?menuId=1063"),
    ("04_vworkpage_lid23483", f"{COURSE}/meol/jpk/course/vworkpage/index.jsp?lId=23483"),
    ("05_vworkpage_lid81135", f"{COURSE}/meol/jpk/course/vworkpage/index.jsp?lId=81135"),
    ("06_vworkpage_courseid19155", f"{COURSE}/meol/jpk/course/vworkpage/index.jsp?courseId=19155"),
    ("07_course_index19155", f"{COURSE}/meol/homepage/course/course_index.jsp?courseId=19155"),
]


def dump(session, tag: str, url: str) -> None:
    r = session.get(url, timeout=30)
    ctype = r.headers.get("Content-Type", "")
    text = decode_page(r.content, ctype)
    path = os.path.join(RAW, f"{tag}.html")
    with open(path, "wb") as f:
        f.write(r.content)
    meta = {
        "tag": tag,
        "url": url,
        "final_url": r.url,
        "status": r.status_code,
        "content_type": ctype,
        "charset": _charset_of(ctype),
        "bytes": len(r.content),
        "elapsed_ms": int(r.elapsed.total_seconds() * 1000),
        "dumped_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "throttled": "访问过于频繁" in text,
    }
    with open(os.path.join(RAW, f"{tag}_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    flag = " [限流]" if meta["throttled"] else ""
    print(f"[dump] {tag}: {r.status_code}, {len(r.content)}B, charset={meta['charset']}{flag}")


def follow_hw_links(session, max_follow: int = 12) -> None:
    """从三门课的 vworkpage 里找作业相关链接，各 dump 一层。"""
    import re

    seen = set()
    n = 0
    for tag in ("04_vworkpage_lid23483", "05_vworkpage_lid81135", "06_vworkpage_courseid19155"):
        path = os.path.join(RAW, f"{tag}.html")
        if not os.path.exists(path):
            continue
        html = decode_page(open(path, "rb").read())
        for href in re.findall(r'href="([^"]+)"', html):
            if not re.search(r"(hwtask|vwork|homework|write)", href, re.I):
                continue
            full = href if href.startswith("http") else urllib.parse.urljoin(COURSE + "/meol/", href)
            if full in seen or "logout" in full:
                continue
            seen.add(full)
            n += 1
            if n > max_follow:
                return
            dump(session, f"10_follow{n:02d}", full)


def main() -> int:
    os.makedirs(RAW, exist_ok=True)
    cred = cs.load_credentials()
    if not cred:
        print("[FAIL] 请先运行: python -m buct_assistant set-credentials")
        return 1
    print("[1/3] CAS 登录 ...")
    try:
        s = cas_login.login(cred[0], cred[1])
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] 登录失败: {e}")
        return 1
    cs.save_cookies(cas_login.session_to_cookies(s))

    print("[2/3] dump 基础页面 ...")
    for tag, url in TARGETS:
        try:
            dump(s, tag, url)
        except Exception as e:  # noqa: BLE001
            print(f"[fail] {tag}: {e}")

    print("[3/3] 跟随作业相关链接 ...")
    try:
        follow_hw_links(s)
    except Exception as e:  # noqa: BLE001
        print(f"[fail] follow: {e}")

    print(f"\n[OK] 完成，文件在 {RAW}")
    print("下一步：请核对各 html 用 GBK 解码是否无乱码，并按方案做浏览器 F12 抓包。")
    return 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402

    sys.exit(main())
