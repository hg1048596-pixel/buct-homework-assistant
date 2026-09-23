# -*- coding: utf-8 -*-
"""微信推送：Server酱（sctapi.ftqq.com）与 PushPlus，可同时开。"""
import requests

from .base import Notifier, NotifyMessage

UA = {"User-Agent": "buct-homework-assistant/0.1"}
TIMEOUT = 20


class WeChatNotifier(Notifier):
    name = "wechat"

    def _enabled_sc(self) -> bool:
        return bool(self.cfg.get("enabled") and self.cfg.get("serverchan_sendkey"))

    def _enabled_pp(self) -> bool:
        return bool(self.cfg.get("enabled") and self.cfg.get("pushplus_token"))

    def enabled(self) -> bool:
        return self._enabled_sc() or self._enabled_pp()

    def send(self, msg: NotifyMessage) -> None:
        errors = []
        if self._enabled_sc():
            try:
                key = self.cfg["serverchan_sendkey"]
                r = requests.post(
                    f"https://sctapi.ftqq.com/{key}.send",
                    data={"title": msg.title[:32], "desp": msg.body}, headers=UA, timeout=TIMEOUT)
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001
                errors.append(f"Server酱: {e}")
        if self._enabled_pp():
            try:
                r = requests.post(
                    "https://www.pushplus.plus/send",
                    json={"token": self.cfg["pushplus_token"], "title": msg.title[:100],
                          "content": msg.body, "template": "markdown"},
                    headers=UA, timeout=TIMEOUT)
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001
                errors.append(f"PushPlus: {e}")
        if errors and not (self._enabled_sc() and self._enabled_pp() and len(errors) < 2):
            raise RuntimeError("; ".join(errors))
