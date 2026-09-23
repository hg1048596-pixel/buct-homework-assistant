# -*- coding: utf-8 -*-
"""通知渠道基类。"""
import abc
import datetime
from dataclasses import dataclass, field

from ..platform.models import TZ


@dataclass
class NotifyMessage:
    title: str
    body: str = ""          # 纯文本（桌面通知、微信用）
    html: str = ""          # 邮件用
    url: str = ""           # 点击跳转
    urgent: bool = False
    tier: str = ""          # new / d24 / d6 / d1 / overdue / submitted
    keys: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(TZ).isoformat(timespec="seconds"))


class Notifier(abc.ABC):
    name = "base"

    def __init__(self, cfg: dict, log):
        self.cfg = cfg or {}
        self.log = log

    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled"))

    @abc.abstractmethod
    def send(self, msg: NotifyMessage) -> None:
        ...
