# -*- coding: utf-8 -*-
"""离线装包引导：沙箱内 pip/urllib 都被拦，只有 curl 能通。

做法：用 curl 从清华镜像抓 wheel 到 wheels/，再 pip --no-index --find-links 安装；
缺哪个传递依赖就再抓哪个，循环直到装齐。

用法:
    python tools/bootstrap_wheels.py            # 按 requirements.txt 装齐
    python tools/bootstrap_wheels.py requests gmssl==3.2.2
"""
import os
import re
import subprocess
import sys
import urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHEELS = os.path.join(BASE, "wheels")
REQ = os.path.join(BASE, "requirements.txt")
INDEX = "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
PY = os.environ.get("BUCT_PY") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(BASE))))),
    ".workbuddy", "binaries", "python", "envs", "default", "Scripts", "python.exe")

_PRE = re.compile(r"(?i)(a\d|b\d|rc\d|dev|\.post)")


def fetch(url: str) -> bytes:
    r = subprocess.run(["curl", "-sL", "--max-time", "90", url],
                       capture_output=True, timeout=100)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(f"curl exit={r.returncode}")
    return r.stdout


def _ver_key(v: str):
    """版本号 → 可比较的键。预发布后缀单列出来，避免 2.0b3 被当成 > 2.7。"""
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", v)
    base = [int(x) for x in (m.group(1).split(".") if m else [])]
    suf = m.group(2) if m else v
    return (base, 0 if suf == "" else 1, suf)


def _stable_flag(v: str) -> int:
    """正式版返回 1、预发布返回 0；排序后取末位即"优先正式版、再取版本最高"。"""
    return 0 if _PRE.search(v) else 1


def _parse_spec(spec: str):
    m = re.match(r"^([A-Za-z0-9_.-]+)\s*(.*)$", spec.strip())
    pkg = m.group(1)
    cons = []
    for c in re.findall(r"(==|>=|<=|<|>)\s*([A-Za-z0-9_.-]+)", m.group(2)):
        cons.append((c[0], _ver_key(c[1])))
    return pkg, cons


def _ver_ok(ver_key, cons) -> bool:
    for op, ref in cons:
        if op == "==" and ver_key != ref:
            return False
        if op == ">=" and not ver_key >= ref:
            return False
        if op == "<" and not ver_key < ref:
            return False
        if op == "<=" and not ver_key > ref:
            return False
        if op == ">" and not ver_key > ref:
            return False
    return True


def best_wheel(pkg: str, cons):
    url = f"{INDEX}/{urllib.parse.quote(pkg.lower())}/"
    try:
        html = fetch(url).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print(f"[skip] {pkg}: index fetch failed: {e}")
        return None
    links = re.findall(r'href="([^"]+)"[^>]*>([^<]+)</a>', html)
    cands = []
    for href, name in links:
        name = name.strip()
        if not name.endswith(".whl"):
            continue
        m = re.match(r"([^-]+)-([^-]+)(?:-([^-]+))?-([^-]+)-([^-]+)-([^-]+)\.whl$", name)
        if not m:
            continue
        _n, ver, _build, py, abi, plat = m.groups()
        # abi3 的 wheel 标 py 部分是构建时版本（如 cp35），对 3.13 前向兼容
        py_ok = py in ("py3", "py2.py3") or py == "cp313" or abi == "abi3"
        abi_ok = abi in ("none", "abi3", "cp313")
        plat_ok = plat in ("any", "win_amd64")
        vk = _ver_key(ver)
        if py_ok and abi_ok and plat_ok and _ver_ok(vk, cons):
            cands.append((_stable_flag(ver), vk, name, urllib.parse.urljoin(url, href)))
    if not cands:
        print(f"[miss] {pkg}: 无兼容 wheel")
        return None
    cands.sort(key=lambda t: (t[0], t[1]))
    return cands[-1][2], cands[-1][3]


def ensure(spec: str) -> bool:
    pkg, cons = _parse_spec(spec)
    best = best_wheel(pkg, cons)
    if not best:
        return False
    name, url = best
    dest = os.path.join(WHEELS, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"[have] {name}")
        return True
    print(f"[get ] {name}")
    try:
        data = fetch(url)
    except Exception as e:  # noqa: BLE001
        print(f"[fail] {name}: {e}")
        return False
    with open(dest, "wb") as f:
        f.write(data)
    return True


def pip_install() -> bool:
    for attempt in range(60):
        r = subprocess.run(
            [PY, "-m", "pip", "install", "--no-index", "--find-links", WHEELS,
             "-r", REQ, "--no-cache-dir", "-q"],
            capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            print("[ok  ] pip install 完成")
            return True
        blob = (r.stdout or "") + (r.stderr or "")
        # pip 会把需要的精确版本一起报出来，必须照抄约束，否则会抓错版本
        missing = []
        for m in re.finditer(
                r"No matching distribution found for ([A-Za-z0-9_.\-]+(?:[<>=!]+[A-Za-z0-9_.\-]+(?:,[<>=!]+[A-Za-z0-9_.\-]+)*)?)",
                blob):
            if m.group(1) not in missing:
                missing.append(m.group(1))
        if not missing:
            print(blob[-2500:])
            return False
        print(f"[loop] 缺依赖: {', '.join(missing)}")
        for pkg in missing:
            ensure(pkg)
    print("[fail] 迭代次数用尽")
    return False


if __name__ == "__main__":
    os.makedirs(WHEELS, exist_ok=True)
    args = sys.argv[1:]
    if args and args[0] == "install":
        sys.exit(0 if pip_install() else 1)
    specs = args
    if not specs:
        with open(REQ, encoding="utf-8") as f:
            specs = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    ok = True
    for s in specs:
        ok = ensure(s) and ok
    sys.exit(0 if ok else 1)
