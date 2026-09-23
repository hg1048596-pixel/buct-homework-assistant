# -*- coding: utf-8 -*-
"""平台端点常量。改版时只改这里。"""
BASE = "https://course.buct.edu.cn"

LOGIN_ENTRY = f"{BASE}/meol/homepage/common/sso_login.jsp"
LOGOUT = f"{BASE}/meol/homepage/V8/include/logout.jsp"
PERSONAL = f"{BASE}/meol/personal.do"
LESSON_LIST = f"{BASE}/meol/lesson/blen.student.lesson.list.jsp"
REMINDER_V8 = f"{BASE}/meol/welcomepage/student/interaction_reminder_v8.jsp"

# 作业链路（2026-09 实测确证）
#   课程列表 → 课程页 → 左菜单「课程作业」→ course_column_preview_transfer.jsp
#     → 302 → /meol/common/hw/student/hwtask.jsp?tagbug=client&strStyle=xxx  （作业列表）
#       → write.jsp?hwtid=X   （查看作业任务页：元数据 + 作业内容 + 提交表单）
COURSE_PAGE = f"{BASE}/meol/jpk/course/layout/newpage/index.jsp"
COLUMN_TRANSFER = f"{BASE}/meol/jpk/course/course_column_preview_transfer.jsp"
COURSE_COLUMN_URL = f"{BASE}/meol/jpk/course/layout/newpage/course_column_preview_transfer.jsp"

HW_LIST = f"{BASE}/meol/common/hw/student/hwtask.jsp"
HW_VIEW = f"{BASE}/meol/common/hw/student/hwtask.view.jsp"
HW_WRITE = f"{BASE}/meol/common/hw/student/write.jsp"
HW_SUBMIT = f"{BASE}/meol/common/hw/student/write.do.jsp"
HW_TASKANSWER = f"{BASE}/meol/common/hw/student/taskanswer.jsp"
HW_STAT = f"{BASE}/meol/common/hw/student/hwtask.stat.jsp"
SER_UPLOAD = f"{BASE}/meol/servlet/SerUpload"

# 实测：write.do.jsp 的表单字段
SUBMIT_FIELD_HWTID = "hwtid"
SUBMIT_FIELD_HWAID = "hwaid"
SUBMIT_FIELD_BODY = "IPT_BODY"   # GBK 编码
# 实测：UEditor 走 SerUpload，上传字段名 upfile，action 见服务端 config
UPLOAD_FIELD = "upfile"


def course_page(course_id: str) -> str:
    return f"{COURSE_PAGE}?courseId={course_id}"


def hw_list(str_style: str = "new03") -> str:
    return f"{HW_LIST}?tagbug=client&strStyle={str_style}"


def hw_write(hwtid: str) -> str:
    return f"{HW_WRITE}?hwtid={hwtid}"

ALLOWED_HOSTS = {
    "course.buct.edu.cn",
    "portal.buct.edu.cn",
    "experimental-auth-endpoint.buct.edu.cn",
}
