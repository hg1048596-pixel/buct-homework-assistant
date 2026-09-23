# -*- coding: utf-8 -*-
"""带会话抓一页并打印结构，用于快速确认导航。用法: python tools/inspect_url.py <url> [tag]"""
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from lxml import html as LH  # noqa: E402

from buct_assistant.cas import cas_login  # noqa: E402
from buct_assistant.platform.http_client import _charset_of, decode_page  # noqa: E402
from buct_assistant.security import credential_store as cs  # noqa: E402

RAW = os.path.join(BASE, "calibration", "raw")


def main() -> int:
    url = sys.argv[1]
    tag = sys.argv[2] if len(sys.argv) > 2 else None
    s = cas_login.cookies_to_session(cs.load_cookies())
    if not cas_login.session_alive(s):
        cred = cs.load_credentials()
        s = cas_login.login(cred[0], cred[1])
        cs.save_cookies(cas_login.session_to_cookies(s))
    time.sleep(1.0)
    r = s.get(url, timeout=30)
    text = decode_page(r.content, r.headers.get("Content-Type", ""))
    print(f"URL: {url}\n→ {r.status_code} {len(r.content)}B charset={_charset_of(r.headers.get('Content-Type',''))} final={r.url}")
    if "访问过于频繁" in text:
        print("[限流!]")
    if tag:
        open(os.path.join(RAW, f"{tag}.html"), "wb").write(r.content)
        json.dump({"tag": tag, "url": url, "final_url": r.url, "status": r.status_code,
                   "content_type": r.headers.get("Content-Type", ""), "bytes": len(r.content)},
                  open(os.path.join(RAW, f"{tag}_meta.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

    doc = LH.fromstring(text)
    t = doc.xpath("//title/text()")
    print("标题:", t[0].strip() if t else "—")

    print("\n-- iframe/frame --")
    for f in doc.xpath("//iframe|//frame"):
        print(f"   name={f.get('name')!r} src={(f.get('src') or '')[:120]!r}")

    print("\n-- 含 作业/columnId/hwtask 的链接 --")
    seen = set()
    for a in doc.xpath("//a"):
        txt = re.sub(r"\s+", " ", a.text_content()).strip()
        href = a.get("href") or ""
        onc = a.get("onclick") or ""
        blob = href + " " + onc
        if not blob.strip():
            continue
        if re.search(r"(作业|columnId|hwtask|vwork|hwStuSubmit|write\.jsp)", txt + blob):
            k = (txt, href[:120])
            if k in seen:
                continue
            seen.add(k)
            print(f"   [{txt[:18]}] href={href[:90]!r} onclick={onc[:80]!r}")

    print("\n-- JS 里的 jsp/do 线索 --")
    js = " ".join(doc.xpath("//script[not(@src)]/text()"))
    for u in sorted(set(re.findall(r"[\"']([^\"']{3,110}(?:\.jsp|\.do)[^\"']{0,80})[\"']", js)))[:25]:
        print("   ", u)
    return 0


if __name__ == "__main__":
    sys.exit(main())
