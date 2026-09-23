# -*- coding: utf-8 -*-
"""解析漂移：页面上有表格却解析不出作业时抛这个，并落盘现场 HTML。

原则：解析到 0 条 ≠ 没有作业。必须能区分「真没作业」和「解析规则失效」。
"""
import datetime
import os


class ParseDriftError(Exception):
    def __init__(self, msg: str, html: str = "", tag: str = "unknown"):
        self.msg = msg
        self.html = html
        self.tag = tag
        super().__init__(msg)


def dump_incident(html: str, tag: str, err_dir: str) -> str:
    """把出问题的页面原样落盘，便于事后比对。返回文件路径。"""
    os.makedirs(err_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(err_dir, f"{tag}-{ts}.html")
    with open(path, "wb") as f:
        f.write(html.encode("gbk", errors="replace"))
    return path
