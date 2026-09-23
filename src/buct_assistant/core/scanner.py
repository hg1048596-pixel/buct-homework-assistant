# -*- coding: utf-8 -*-
"""扫描编排（2026-09 实测链路）。

  1 GET 课程列表 blen.student.lesson.list.jsp → [(courseId, 课程名)]
  2 每门课：GET 课程页 index.jsp?courseId=X → 左菜单「课程作业」得到 columnId
     （链接是相对 newpage 目录写的，务必按 newpage 的 URL 解析基准）
  3 GET course_column_preview_transfer.jsp?columnId=Y
     → 302 → hwtask.jsp?tagbug=client&strStyle=xxx  这就是作业列表
  4 未提交且可提交的作业：GET write.jsp?hwtid=Z 取作业要求正文

columnId 会缓存到 data/course_columns.json，第二轮起每门课只要 1 个请求。
"""
import datetime
import hashlib
import json
import os
import re
import urllib.parse
from dataclasses import dataclass, field

from lxml import html as LH

from ..platform import course_list, homework as hwmod, urls
from ..platform.http_client import BudgetExceeded, PlatformSession, SessionExpired, Throttled
from ..platform.models import TZ, Course, Homework
from ..platform.parse_drift import ParseDriftError, dump_incident

HW_COLUMN_RE = re.compile(r"(课程作业|提交作业)")


@dataclass
class ScanResult:
    courses: list[Course] = field(default_factory=list)
    homeworks: list[Homework] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # 正常但值得知道的（如某课没有作业栏）
    throttled: bool = False
    session_expired: bool = False                    # 课程列表返回登录页 → 需要重登
    pages: int = 0
    finished_at: str = ""

    @property
    def unsubmitted(self) -> list[Homework]:
        return [h for h in self.homeworks if h.unsubmitted]


def load_columns(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_columns(path: str, cache: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def find_hw_column(html: str) -> str:
    """在课程页里找「课程作业」列的 URL。"""
    doc = LH.fromstring(html)
    for a in doc.xpath("//a"):
        href = a.get("href") or ""
        if "course_column_preview_transfer.jsp" not in href:
            continue
        text = re.sub(r"\s+", " ", a.text_content()).strip()
        if HW_COLUMN_RE.search(text):
            # 链接按 newpage 目录为基准写，不能用课程页自己的 URL 当基准
            return urllib.parse.urljoin(urls.COURSE_COLUMN_URL, href)
    return ""


def scan(ps: PlatformSession, log, err_dir: str, columns_path: str,
         max_courses: int = 60, dump_on_drift: bool = True,
         known_content: dict | None = None) -> ScanResult:
    """known_content: {key: 上次已抓到要求正文的作业键}，用于跳过重复的详情请求。"""
    res = ScanResult()
    cache = load_columns(columns_path)
    cache_dirty = False
    try:
        log.info("拉取课程列表 ...")
        text = ps.get_text(urls.LESSON_LIST)
        courses_raw = course_list.parse_lesson_list(text, urls.LESSON_LIST)
        log.info(f"课程数: {len(courses_raw)}")
    except (Throttled, SessionExpired) as e:
        res.throttled = isinstance(e, Throttled)
        res.errors.append(str(e))
        return res

    if not courses_raw:
        # 解析到 0 门课绝不等于没有课：页面多半是登录页（会话失效）或结构变化
        if "IPT_LOGINPASSWORD" in text or "统一身份认证" in text or "/cas/login" in text:
            res.session_expired = True
            res.errors.append("课程列表返回登录页——会话已失效，将自动重新登录后重试")
            return res
        path = dump_incident(text, "lesson-empty", err_dir)
        res.errors.append(f"课程列表解析到 0 门课（现场已存 {path}）")
        return res

    for cid, name, _entry in courses_raw[:max_courses]:
        course = Course(course_id=cid, name=name)
        res.courses.append(course)
        try:
            # 实测：必须先访问课程页建立会话上下文，列页才不会报「错误！」
            # （2026-09-23 走缓存直进列页时，30 门课全部拿到错误页，对照实验已确认）
            page = ps.get_text(urls.course_page(cid))
            col_url = find_hw_column(page)
            if not col_url:
                if cache.get(cid):
                    col_url = cache[cid]      # 上次成功过的列页，再试一次
                    res.notes.append(f"{name}: 课程页没有「课程作业」菜单，沿用上次的列页")
                else:
                    res.notes.append(f"{name}: 没有「课程作业」菜单，改用列表页直取")
                    col_url = urls.hw_list()

            list_html = ps.get_text(col_url)   # 会跳到 hwtask.jsp
            if "valuelist" not in list_html:
                raise ParseDriftError(f"{name}: 作业列表里没有 valuelist 表格",
                                      list_html, tag=f"list-{cid}")
            rows = hwmod.parse_hwtask_list(list_html, cid, name, col_url)
            log.info(f"  {name[:20]}：{len(rows)} 个作业")

            for hw in rows:
                content_hash = hashlib.sha1(
                    (hw.title + "|" + hw.ddl_raw).encode("utf-8", "replace")).hexdigest()
                # 只对「未提交且能提交」的拉详情；上次已经抓过同样标题+截止时间的就跳过
                if (hw.unsubmitted and hw.can_submit
                        and (known_content or {}).get(hw.key) != content_hash):
                    try:
                        detail = ps.get_text(urls.hw_write(hw.hwtid))
                        d = hwmod.parse_vworkpage(detail, cid, name, urls.hw_write(hw.hwtid))
                        if d:
                            hw.content_html = d.content_html
                            hw.content_text = d.content_text
                            hw.scoring_method = d.scoring_method or hw.scoring_method
                            if d.ddl and not hw.ddl:
                                hw.ddl, hw.ddl_raw = d.ddl, d.ddl_raw
                    except (Throttled, BudgetExceeded):
                        raise
                    except Exception as e:  # noqa: BLE001
                        res.errors.append(f"{name}/{hw.title[:16]}: 详情抓取失败 {e}")
                res.homeworks.append(hw)

            ps.note_success()
        except Throttled as e:
            res.throttled = True
            res.errors.append(f"{name}: {e}")
            break
        except BudgetExceeded as e:
            res.errors.append(f"{name}: {e}")
            break
        except SessionExpired as e:
            res.errors.append(f"{name}: {e}")
            break
        except ParseDriftError as e:
            if dump_on_drift:
                path = dump_incident(e.html, e.tag, err_dir)
                e.msg += f"（现场已存 {path}）"
            res.errors.append(e.msg)
            log.warning(e.msg)
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"{name}: {type(e).__name__}: {e}")
            log.warning(f"{name}: {e}")

    if cache_dirty:
        save_columns(columns_path, cache)
    res.pages = ps.used
    res.finished_at = datetime.datetime.now(TZ).isoformat(timespec="seconds")
    return res
