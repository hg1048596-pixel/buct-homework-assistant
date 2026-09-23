# -*- coding: utf-8 -*-
"""班级标识识别与过滤。

物理实验类课程的作业标题形如：
    国机2503-Thu1800-7 Thermal Conductivity <May 7
    化工2505-Wed9:45-1Kelvin_Bridge <Sep16+7
    机智A2510-Thu1445-7 Thermal Conductivity <May ...
前半段（第一个 "-" 之前）就是班级标识。一门课里会混进全年级各班的实验时段，
只需保留自己班的那些。

班级码的形态：1~3 个汉字 + 可选 1 个字母 + 4 位数字
（国机2503 / 化工2505 / 机智A2510 / 材数C2501）。
不符合这个形态的（如「《传感器》实验报告」）一律**不做过滤**，避免误杀。
"""
import re

CLASS_RE = re.compile(r"^[\u4e00-\u9fff]{1,3}[A-Za-z]?\d{4}$")


def extract_class(title: str, separator: str = "-") -> str:
    """从标题里取出班级标识；取不到返回空串。"""
    head = (title or "").split(separator or "-")[0].strip()
    return head if CLASS_RE.match(head) else ""


def applies(course_name: str, cfg: dict) -> bool:
    pats = cfg.get("courses") or []
    return any(p and p in (course_name or "") for p in pats)


def decide(course_name: str, title: str, cfg: dict) -> tuple[bool, str]:
    """返回 (是否应该显示, 识别出的班级码)。

    未启用、未填自己的班级、课程不在适用范围、识别不出班级码 —— 任一成立都放行。
    """
    code = extract_class(title, (cfg or {}).get("separator", "-"))
    if not (cfg or {}).get("enabled"):
        return True, code
    if not code or not applies(course_name, cfg):
        return True, code
    mine = str(cfg.get("my_class") or "").strip()
    if not mine:
        return True, code
    # 允许只填前几位（当作前缀匹配），比如填「机智A251」也能匹配 机智A2510
    return (code == mine or code.startswith(mine)), code
