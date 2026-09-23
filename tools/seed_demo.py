# -*- coding: utf-8 -*-
"""往 state.json 里塞几条演示数据，方便先看界面；随时可清空。

    python tools/seed_demo.py           # 写入演示数据
    python tools/seed_demo.py --clear   # 清空演示数据
"""
import datetime
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from buct_assistant.core.state import StateStore  # noqa: E402
from buct_assistant.platform.models import TZ  # noqa: E402
from buct_assistant.settings import Settings  # noqa: E402

DEMO_PREFIX = "demo-"


def demo_records():
    now = datetime.datetime.now(TZ)
    specs = [
        ("大学物理实验(II)", "传感器(1) 实验报告", 3.5 * 3600,
         "请按照相应实验数据处理要求来进行数据处理和分析，撰写实验报告，"
         "完成的实验报告需要扫描制作成一个PDF文档，将文档命名为：“班级-姓名-实验项目名称”的格式。"),
        ("电气工程基础实验(I)", "实验1 常用直流测量仪器仪表", 30 * 3600,
         "预习部分：阅读实验指导书第一章，写出常用直流测量仪器仪表的使用要点。"),
        ("高等数学A(II)", "第三周作业 7-28 至 7-42", 5 * 24 * 3600,
         "习题 7-28, 7-29, 7-30, 7-33, 7-34, 7-35, 7-36, 7-38, 7-39, 7-40, 7-41, 7-42"),
        ("大学英语II", "Unit 3 Writing Task", -2 * 3600,
         "Write a 300-word essay on the topic given in class."),
    ]
    out = []
    for i, (course, title, delta, content) in enumerate(specs):
        ddl = now + datetime.timedelta(seconds=delta)
        out.append({
            "course_id": f"{DEMO_PREFIX}{i}",
            "course_name": course,
            "hwtid": f"9000{i}",
            "title": title,
            "ddl": ddl.isoformat(timespec="seconds"),
            "ddl_raw": f"{ddl.year}年{ddl.month}月{ddl.day}日 {ddl:%H:%M:%S}",
            "first_seen": now.isoformat(timespec="seconds"),
            "last_seen": now.isoformat(timespec="seconds"),
            "content_hash": f"demo{i}",
            "notified": {},
            "submit_state": "IDLE",
            "confidence": "high",
            "unsubmitted": True,
            "can_submit": True,
            "score_raw": "",
            "scoring_method": "打分制(100.00)",
            "layout": "vworkpage",
            "url": "（演示数据，非真实页面）",
            "content_text": content,
        })
    return out


def main() -> int:
    s = Settings.load()
    st = StateStore(s.state_path)
    demo_keys = [k for k in st.data["homeworks"] if k.startswith(DEMO_PREFIX)]

    if "--clear" in sys.argv:
        for k in demo_keys:
            del st.data["homeworks"][k]
        st.save()
        print(f"[OK] 已清空 {len(demo_keys)} 条演示数据")
        return 0

    for rec in demo_records():
        st.data["homeworks"][f"{rec['course_id']}:{rec['hwtid']}"] = rec
    st.save()
    print("[OK] 已写入 4 条演示数据（课程名列标着 demo- 前缀的 key）")
    print("     清空：python tools/seed_demo.py --clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
