# -*- coding: utf-8 -*-
"""领域模型。"""
import datetime
from dataclasses import dataclass, field

TZ = datetime.timezone(datetime.timedelta(hours=8))


@dataclass
class Course:
    course_id: str
    name: str
    teacher: str = ""
    url: str = ""


@dataclass
class Homework:
    course_id: str
    course_name: str
    hwtid: str
    title: str
    ddl: datetime.datetime | None = None
    ddl_raw: str = ""
    score_raw: str = ""
    publisher: str = ""
    scoring_method: str = ""
    unsubmitted: bool = True
    can_submit: bool = False
    confidence: str = "high"
    content_html: str = ""
    content_text: str = ""
    layout: str = "vworkpage"
    url: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.datetime.now(TZ).isoformat(timespec="seconds"))

    @property
    def key(self) -> str:
        return f"{self.course_id}:{self.hwtid}"

    def remaining(self, now: datetime.datetime | None = None) -> datetime.timedelta | None:
        if not self.ddl:
            return None
        now = now or datetime.datetime.now(TZ)
        return self.ddl - now

    def is_overdue(self, now: datetime.datetime | None = None) -> bool:
        left = self.remaining(now)
        return left is not None and left.total_seconds() < 0

    def content_hash_source(self) -> str:
        return f"{self.title}|{self.ddl_raw}|{self.content_text[:2000]}"
