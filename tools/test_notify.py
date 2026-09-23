# -*- coding: utf-8 -*-
"""测试各提醒渠道是否配置正确。

    python tools/test_notify.py            # 用配置里的渠道各发一条测试消息
    python tools/test_notify.py desktop    # 只测桌面通知
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from buct_assistant.logging_setup import setup  # noqa: E402
from buct_assistant.notify.base import NotifyMessage  # noqa: E402
from buct_assistant.notify.desktop import DesktopNotifier  # noqa: E402
from buct_assistant.notify.email import EmailNotifier  # noqa: E402
from buct_assistant.notify.wechat import WeChatNotifier  # noqa: E402
from buct_assistant.settings import Settings  # noqa: E402

MSG = NotifyMessage(
    title="[测试] 北化作业助手渠道连通性测试",
    body="这是一条测试消息。\n课程：大学物理实验(II)\n作业：传感器(1) 实验报告\n截止：2026年9月27日 23:59:00",
    urgent=False, tier="d6", url="http://127.0.0.1:8765/dashboard")


def main() -> int:
    s = Settings.load()
    log = setup(s.logs_dir, quiet=False)
    nc = s.notify_cfg
    wanted = [a.lower() for a in sys.argv[1:]]

    all_notifiers = [
        ("desktop", DesktopNotifier(nc.get("desktop", {}), log)),
        ("email", EmailNotifier(nc.get("email", {}), log)),
        ("wechat", WeChatNotifier(nc.get("wechat", {}), log)),
        ("board", None),
    ]
    failed = 0
    for name, n in all_notifiers:
        if wanted and name not in wanted:
            continue
        if n is None:
            print(f"[skip] {name}: 需通过控制台看板查看")
            continue
        if not n.enabled():
            print(f"[skip] {name}: 未启用或缺配置")
            continue
        try:
            n.send(MSG)
            print(f"[OK  ] {name}: 已发送")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[FAIL] {name}: {type(e).__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
