# -*- coding: utf-8 -*-
"""配置：config/config.yaml + 环境变量覆盖。"""
import os
from dataclasses import dataclass, field

import yaml

# settings.py 位于 <proj>/src/buct_assistant/，往上三层才是项目根
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULTS = {
    "scan": {
        "interval_minutes": 20,
        "jitter_seconds": 120,
        # 实测：0.5s 间隔会被平台限流，1.0~1.6s 跑 20+ 请求没被拦
        "request_min_delay": 1.0,
        "request_max_delay": 1.6,
        "budget_per_scan": 150,
        "max_courses": 60,
        "max_assignments_per_course": 20,
        "morning_digest": "07:55",
        # 平台课程实例多年复用，老作业会一直留在列表里（实测最早到 2020 年）。
        # 逾期超过这么多天的一律不展示、不提醒。
        "hide_overdue_days": 80,
    },
    # 班级标识：物理实验类课程标题形如「国机2503-Thu1800-7 Thermal Conductivity」，
    # 第一个 "-" 之前那段是班级。在设置页填上自己的班级后，**不匹配的记录不再显示、
    # 也不提醒**；my_class 留空时等于不过滤。
    "class_filter": {
        "enabled": True,
        "my_class": "",                              # 例：国机2503（留空 = 不过滤）
        "courses": ["大学物理实验"],                 # 只对这些课程名生效
        "separator": "-",
    },
    "notify": {
        "dashboard_url": "http://127.0.0.1:8765",
        "max_notifications_per_cycle": 3,
        "overdue_digest_hour": 9,
        "include_content_in_notify": True,
        # 实测：158 条「未提交」里 143 条是别的班的实验时段等噪音，默认只提醒能提交的
        "new_requires_can_submit": True,
        "include_overdue": False,
        "ignore_title_patterns": [],
        # 一进入 24 小时窗口就立刻弹一条桌面通知（每份作业只弹一次）
        "instant_24h": True,
        # 每天固定时间弹一次「全部未提交作业 + 剩余时间」摘要
        "daily_digest": {
            "enabled": True,
            "time": "12:30",
            "scope": "all",          # all=所有未提交（仍会滤掉超期久远与其他班的）；submittable=只要能提交的
            "include_overdue": True, # 摘要里是否包含已逾期的
        },
        "desktop": {"enabled": True, "app_id": "北化作业助手", "sound": "Default"},
        "email": {"enabled": False, "smtp_host": "smtp.qq.com", "smtp_port": 465,
                  "smtp_user": "", "smtp_auth_code": "", "to": [],
                  "subject_prefix": "[北化作业] "},
        "wechat": {"enabled": False, "serverchan_sendkey": "", "pushplus_token": ""},
    },
    "web": {"host": "127.0.0.1", "port": 8765},
    "submit": {"enabled": True, "max_per_day": 3, "cooldown_minutes": 10},
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


@dataclass
class Settings:
    root: str = ROOT
    raw: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | None = None) -> "Settings":
        path = path or os.path.join(ROOT, "config", "config.yaml")
        user = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                user = yaml.safe_load(f) or {}
        # 环境变量优先（便于临时调试，不写入文件）
        if os.environ.get("BUCT_SMTP_AUTH_CODE"):
            user.setdefault("notify", {}).setdefault("email", {})[
                "smtp_auth_code"] = os.environ["BUCT_SMTP_AUTH_CODE"]
        return cls(raw=_merge(DEFAULTS, user))

    # ---- 路径 ----
    def p(self, *parts) -> str:
        return os.path.join(self.root, *parts)

    @property
    def data_dir(self) -> str:
        return self.p("data")

    @property
    def logs_dir(self) -> str:
        return self.p("logs")

    @property
    def calibration_dir(self) -> str:
        return self.p("calibration")

    @property
    def state_path(self) -> str:
        return os.path.join(self.data_dir, "state.json")

    @property
    def columns_path(self) -> str:
        return os.path.join(self.data_dir, "course_columns.json")

    @property
    def lock_path(self) -> str:
        return os.path.join(self.data_dir, "scan.lock")

    # ---- 快捷读取 ----
    @property
    def scan_cfg(self) -> dict:
        return self.raw["scan"]

    @property
    def notify_cfg(self) -> dict:
        return self.raw["notify"]

    @property
    def web_cfg(self) -> dict:
        return self.raw["web"]

    @property
    def submit_cfg(self) -> dict:
        return self.raw["submit"]

    @property
    def class_cfg(self) -> dict:
        return self.raw.get("class_filter", {}) or {}
