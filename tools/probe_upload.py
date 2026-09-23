# -*- coding: utf-8 -*-
"""实测附件上传：服务端 fileAllowFiles 里没有 .pdf，必须验证到底收不收。

用法: python tools/probe_upload.py [文件名] [扩展名]
默认上传一个自动生成的合法单页 PDF。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from buct_assistant.cas import cas_login  # noqa: E402
from buct_assistant.platform import submit  # noqa: E402
from buct_assistant.platform.http_client import PlatformSession  # noqa: E402
from buct_assistant.security import credential_store as cs  # noqa: E402


def make_minimal_pdf(path: str, text: str = "BUCT upload probe") -> None:
    """手写一个结构合法的单页 PDF（含正确的 xref 偏移）。"""
    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 240 80] "
                b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>")
    stream = f"BT /F1 12 Tf 20 40 Td ({text}) Tj ET".encode("ascii")
    objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n"
            f"{xref_at}\n%%EOF\n").encode()
    with open(path, "wb") as f:
        f.write(bytes(out))


def main() -> int:
    tmp_dir = os.path.join(BASE, "data")
    os.makedirs(tmp_dir, exist_ok=True)
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg and os.path.exists(arg):
        path, name = arg, os.path.basename(arg)
    else:
        ext = sys.argv[2] if len(sys.argv) > 2 else ".pdf"
        name = f"upload-probe{ext}"
        path = os.path.join(tmp_dir, "_probe" + ext)
        if ext == ".pdf":
            make_minimal_pdf(path)
        else:
            with open(path, "wb") as f:
                f.write(b"buct upload probe\n")
    size = os.path.getsize(path)
    print(f"待上传: {name} ({size} B)")

    s = cas_login.cookies_to_session(cs.load_cookies())
    if not cas_login.session_alive(s):
        c = cs.load_credentials()
        s = cas_login.login(c[0], c[1])
        cs.save_cookies(cas_login.session_to_cookies(s))
    ps = PlatformSession(s)

    print("POST /meol/servlet/SerUpload?action=uploadfile  (字段 upfile)")
    res = submit.upload_file(ps, path, remote_name=name)
    print(f"  ok={res.ok}")
    if res.url:
        print(f"  url={res.url}")
    if res.err:
        print(f"  err={res.err}")
    print(f"  原始返回: {res.raw}")
    if res.ok:
        print("\n[结论] 服务端接受该类型附件。")
    else:
        print("\n[结论] 被拒绝 —— 需要换上传方式或改格式（比如打包成图片/压缩包）。")
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
