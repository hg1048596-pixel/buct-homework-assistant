# -*- coding: utf-8 -*-
"""看板渠道：进程内事件总线，供网页控制台的 SSE 订阅。"""
import asyncio
import json
import os
from collections import deque

from .base import Notifier, NotifyMessage


class Board:
    """内存事件总线 + 落盘 feed（重启后能恢复最近事件）。"""

    def __init__(self, feed_path: str, max_feed: int = 200):
        self.feed_path = feed_path
        self.events: deque = deque(maxlen=max_feed)
        self._subs: list[asyncio.Queue] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.feed_path):
            return
        try:
            with open(self.feed_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.events.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass

    def _append_file(self, event: dict) -> None:
        os.makedirs(os.path.dirname(self.feed_path), exist_ok=True)
        with open(self.feed_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def publish(self, event: dict) -> None:
        self.events.append(event)
        try:
            self._append_file(event)
        except OSError:
            pass
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subs:
            self._subs.remove(q)

    def recent(self, n: int = 50) -> list[dict]:
        return list(self.events)[-n:]


class BoardNotifier(Notifier):
    name = "board"

    def __init__(self, board: Board, cfg: dict, log):
        super().__init__(cfg, log)
        self.board = board

    def send(self, msg: NotifyMessage) -> None:
        self.board.publish({
            "kind": "notify", "tier": msg.tier, "title": msg.title,
            "body": msg.body, "keys": msg.keys, "created_at": msg.created_at})
