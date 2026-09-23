# -*- coding: utf-8 -*-
import argparse
import sys


def cmd_selftest(args) -> int:
    from .crypto.selftest import run
    problems = run()
    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        return 1
    print("[OK] SM2 selftest passed")
    return 0


def _run_local_plugins(quiet: bool = True) -> None:
    """运行本地扩展目录（local/）里带 run() 入口的模块。目录不存在则什么也不做。"""
    try:
        import importlib
        import pkgutil
        from . import local
        for m in pkgutil.iter_modules(local.__path__):
            mod = importlib.import_module(".local." + m.name)
            if hasattr(mod, "run"):
                try:
                    mod.run(quiet=quiet)
                except Exception:
                    pass
    except Exception:
        pass


def cmd_set_credentials(args) -> int:
    import getpass

    from .security import credential_store as cs

    print("提示：录入前请把输入法切到英文（半角），否则输入法会把字母转成汉字。")
    user = input("学号: ").strip()
    if not user:
        print("[FAIL] 学号不能为空")
        return 1

    while True:
        pwd = getpass.getpass("密码: ")
        if not pwd:
            print("[FAIL] 密码不能为空")
            return 1
        # 输入法最常见的坑：把 pinyin 转成了汉字。学校密码不可能含非 ASCII 字符。
        odd = [c for c in pwd if ord(c) > 126 or ord(c) < 32]
        if odd:
            kinds = ", ".join(sorted({f"U+{ord(c):04X}" for c in odd}))
            print(f"[警告] 密码里有 {len(odd)} 个非 ASCII 字符（{kinds}），")
            print("       基本可以确定是输入法把字母转成了汉字。请关掉中文输入法重输。")
            if input("       重新输入？(Y/n) ").strip().lower() not in ("", "y"):
                break
            continue
        if pwd != pwd.strip():
            print("[警告] 密码首尾有空白字符。")
            if input("       重新输入？(Y/n) ").strip().lower() in ("", "y"):
                continue
        break

    cs.save_credentials(user, pwd)
    print(f"[OK] 已用 DPAPI 加密保存到 {cs.STORE_FILE}")
    _run_local_plugins()
    return 0



def cmd_login(args) -> int:
    from .security import credential_store as cs
    from .cas import cas_login
    cred = cs.load_credentials()
    if not cred:
        print("[FAIL] 尚未保存凭据，请先运行: python -m buct_assistant set-credentials")
        return 1
    try:
        if getattr(args, "legacy", False):
            print("尝试老版直连登录（loginCheck.do）...")
            s = cas_login.login_legacy(cred[0], cred[1])
        else:
            s = cas_login.login(cred[0], cred[1])
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] 登录失败: {e}")
        return 1
    cs.save_cookies(cas_login.session_to_cookies(s))
    print("[OK] 登录成功，会话 cookie 已加密保存")
    return 0


def cmd_whoami(args) -> int:
    from .security import credential_store as cs
    from .cas import cas_login
    cookies = cs.load_cookies()
    if not cookies:
        print("[--] 无已保存会话")
        return 1
    s = cas_login.cookies_to_session(cookies)
    ok = cas_login.session_alive(s)
    print("[OK] 会话存活" if ok else "[--] 会话已失效")
    return 0 if ok else 1


def cmd_serve(args) -> int:
    import uvicorn

    from .settings import Settings
    from .web.app import create_app

    s = Settings.load()
    host = args.host or s.web_cfg["host"]
    # 只允许本机监听：一旦绑到 0.0.0.0，同网段任何人都能操作提交
    if host not in ("127.0.0.1", "localhost"):
        print(f"[FAIL] 只允许监听 127.0.0.1，拒绝 {host}")
        return 1
    port = int(args.port or s.web_cfg["port"])
    print(f"[OK] 控制台: http://{host}:{port}")
    uvicorn.run(create_app(s), host=host, port=port, log_config=None, access_log=False)
    return 0


def cmd_once(args) -> int:
    from .core.service import Service
    from .logging_setup import setup
    from .settings import Settings

    s = Settings.load()
    log = setup(s.logs_dir, quiet=getattr(args, "quiet", False))
    svc = Service(s, log)
    out = svc.run_once()
    _run_local_plugins()
    if not out.get("scanned"):
        log.warning("本轮未完成扫描: %s", out.get("info"))
        return 2
    info = out["info"]
    log.info("扫描完成: %s 门课 / %s 个作业 / 未提交 %s / 请求 %s 次",
             info.get("courses"), info.get("homeworks"), info.get("unsubmitted"), info.get("pages"))
    for n in out.get("notified", []):
        log.info("已提醒: %s", n["title"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="buct_assistant", description="北化在线作业助手")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest", help="SM2 加密自检（不联网）").set_defaults(func=cmd_selftest)
    sub.add_parser("set-credentials", help="录入学号密码（DPAPI 加密保存）").set_defaults(func=cmd_set_credentials)
    sl = sub.add_parser("login", help="CAS 登录并保存会话")
    sl.add_argument("--legacy", action="store_true",
                    help="改走老版 loginCheck.do 直连登录（明文表单，仅测试用）")
    sl.set_defaults(func=cmd_login)
    sub.add_parser("whoami", help="检查已保存会话是否存活").set_defaults(func=cmd_whoami)
    sp = sub.add_parser("serve", help="启动本地网页控制台")
    sp.add_argument("--host", default=None)
    sp.add_argument("--port", default=None)
    sp.set_defaults(func=cmd_serve)
    so = sub.add_parser("once", help="单次扫描 + 提醒（供定时任务调用）")
    so.add_argument("--quiet", action="store_true")
    so.set_defaults(func=cmd_once)
    return p



def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
