# -*- coding: utf-8 -*-
"""Windows 桌面通知（winotify / Toast）。

「弹完就退出进程」是这套设计的一部分：Windows 的 Toast 一旦弹出就归系统管，
进程退出后通知仍留在通知中心（Action Center），点它还能回到控制台。
所以定时任务只需要短命地跑一次 `buct_assistant once` 即可。
"""
from .base import Notifier, NotifyMessage

MAX_MSG = 180          # 单条作业提醒：保持短
MAX_MSG_DIGEST = 1100  # 每日摘要要列一堆作业，不能用同一个上限
MAX_TITLE = 64


def _clip(s: str, n: int = MAX_MSG) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


class DesktopNotifier(Notifier):
    name = "desktop"

    def send(self, msg: NotifyMessage) -> None:
        from winotify import Notification, audio

        limit = MAX_MSG_DIGEST if msg.tier == "digest" else MAX_MSG
        duration = "long" if (msg.urgent or msg.tier == "digest") else "short"
        toast = Notification(app_id=self.cfg.get("app_id", "北化作业助手"),
                             title=_clip(msg.title, MAX_TITLE),
                             msg=_clip(msg.body, limit),
                             duration=duration)
        icon = self.cfg.get("icon")
        if icon:
            toast.set_icon(icon)
        sound = self.cfg.get("sound")
        if sound:
            toast.set_audio(getattr(audio, sound, audio.Default), loop=False)
        if msg.url:
            toast.add_actions(label=self.cfg.get("action_label", "打开看板"), launch=msg.url)
        # show() 之后不做任何清理动作 —— 让通知留在系统通知中心
        toast.show()
