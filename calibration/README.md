# 技术事实基线（阶段 1 校准结果）

平台：北化在线 / THEOL，`course.buct.edu.cn`，JSP + Tomcat 集群（URL 里带 `;jsessionid=xxx.TM1/.TM2`）。
本文件记录**实测确证**的事实。平台改版时对比这里，能立刻定位变化点。
来源标记：`[实测]` 本次真实账号验证 ／ `[截图]` 来自界面截图 ／ `[推测]` 未验证。

---

## 1. 登录

| 项 | 结论 | 来源 |
| --- | --- | --- |
| 登录入口 | 首页右上角「登录」→ `/meol/homepage/common/sso_login.jsp` | [实测] |
| 跳转链 | `sso_login.jsp` → 302 `experimental-auth-endpoint.buct.edu.cn/cas/login` → 303 `portal.buct.edu.cn/cas/login` → 302 `portal.buct.edu.cn?timestamp=…` | [实测] |
| flowKey | cookie `COOKIE_INFO`（域 `.portal.buct.edu.cn`，URL 编码 JSON）里的 `data.flowKey`，**一次性** | [实测] |
| SM2 公钥 | `GET /cas/api/reset/rules` → `data.encrypt.publicKey`（65 字节未压缩点，base64） | [实测] |
| 登录接口 | `POST /cas/username-password/login`，JSON `{username, password, flowKey}` | [实测] |
| 密码加密 | 全角转半角 → SM2 **C1C3C2** → `base64(C1.x‖C1.y‖C3‖C2)`（不含 04 前缀） | [实测，登录成功] |
| 成功码 | `666666`，返回 `data.service` 为带 ticket 的回跳地址 | [实测，登录成功] |
| 登录成功判据 | 回跳最终落在受保护的 `/meol/personal.do` 且返回 200、页面无登录表单 | [实测] |

### 错误码

| code | 含义 | 处理 |
| --- | --- | --- |
| `170002` | 用户名或密码错误 | 不重试（避免触发锁定） |
| `999999` | password 字段格式非法（如非法 base64，原文 `Input byte array has wrong 4-byte ending unit`） | 说明加密实现写错了，改代码 |
| `180040` | flowKey 未找到 | 重新取 flowKey |
| `180046` / `180076` | flowKey 无效 / 已用 | 重取后重试一次 |
| `160001` / `160002` | 需 MFA / 需图形验证码 | 熔断，转人工 |
| `180028` / `180029` | 失败过多临时锁定 30 分钟 / 锁死 | 熔断，只提醒不抓取 |

> **`999999` 与 `170002` 的区分很有用**：能把「加密写错了」和「密码填错了」分开。
> 见 `tools/diag_login.py`。

### 老版直连登录已停用

`GET /meol/loginCheck.do?menuId=1063` 仍返回经典登录表单（字段 `logintoken`（13 位毫秒时间戳）/
`IPT_LOGINUSERNAME` / `IPT_LOGINPASSWORD`），但 `POST` 之后会落回登录页 —— **入口已停用**，
必须走 CAS。`python -m buct_assistant login --legacy` 会明确告知这一点。

---

## 2. 页面编码：**同一站点不同页面编码不同**

| 页面 | Content-Type |
| --- | --- |
| `/meol/index.do` | `text/html;charset=UTF-8` |
| `/meol/homepage/course/course_index.jsp` | `text/html;charset=gbk` |
| `/meol/loginCheck.do` | `text/html;charset=GBK` |
| `/meol/common/hw/student/*.jsp` | `charset=gbk` |

**绝不能全局假定 GBK。** 处理收口在 `platform/http_client.decode_page()`：
Content-Type → `<meta charset>` → 严格试 UTF-8、失败退 GBK。

---

## 3. 作业链路（全部实测打通）

```
GET /meol/lesson/blen.student.lesson.list.jsp
    课程链接藏在 onclick 里：onclick="window.open('../homepage/course/course_index.jsp?courseId=29997','manage_course')"
    → 56 门课
 └ GET /meol/jpk/course/layout/newpage/index.jsp?courseId=X        （课程页，含左上菜单）
     菜单项 href 形如 ../../course_column_preview_transfer.jsp?tagbug=client&columnId=Y
     ⚠ 相对路径的基准是 /meol/jpk/course/layout/newpage/，不是课程页自身所在目录
        （course_index.jsp?courseId=X 与 newpage/index.jsp?courseId=X 内容完全相同）
        「课程作业」→ columnId=179799（19155）、234749（23185）、367658（29997）
    └ GET /meol/jpk/course/course_column_preview_transfer.jsp?tagbug=client&columnId=Y
         → 302 → /meol/common/hw/student/hwtask.jsp?tagbug=client&strStyle=xxx
         ⚠ hwtask.jsp 不带课程参数，**课程由会话上下文决定**，必须先访问课程页/列页
         ⚠ strStyle 每门课不同（实测有 new03 与 new05），解析不要依赖它
       └ GET /meol/common/hw/student/write.jsp?hwtid=Z            （查看作业任务页，见下）
```

### 作业列表 `hwtask.jsp` 的表格

`table.valuelist`，表头实测为：
**标题 | 截止时间 | 分数 | 发布人 | 统计信息 | 提交作业 | 查看结果 | 优秀作品**

| 列 | 含义 | 用途 |
| --- | --- | --- |
| td[0] | 标题，`<a href="hwtask.view.jsp?hwtid=…">` | 取 hwtid |
| td[1] | 截止时间，格式 `YYYY年M月D日 HH:MM:SS` | 取 DDL |
| td[2] | 分数 | 成绩 |
| td[3] | 发布人 | — |
| td[4] | 统计信息，链接 `hwtask.stat.jsp` | — |
| **td[5]** | **提交作业**，有链接（`write.jsp?hwtid=`）= **现在可以提交** | can_submit |
| **td[6]** | **查看结果**，有链接（`taskanswer.jsp?hwtid=`）= **已经交过**；或直接写着「未提交」 | submitted |
| td[7] | 优秀作品 | — |

判定规则（已实现）：
`can_submit` = td[5] 有链接；`submitted` = td[6] 有 `taskanswer` 链接或文本「已提交/已交」；
`unsubmitted` = td[6] 写着「未提交」，或（无 taskanswer 链接且可提交）。

### 提交页 `write.jsp?hwtid=Z`（标题「查看作业任务」）

```html
<form name="form1" action="write.do.jsp" method="post">
  <input type="hidden" name="hwtid" value="76948">
  <input type="hidden" name="hwaid" value="NA">
  <table class="infotable">
    <tr><th>标题：</th><td>《传感器》实验报告（补交）</td></tr>
    <tr><th>截止时间：</th><td>2026年11月29日 23:59:00</td></tr>
    <tr><th>评分方式:</th><td>打分制:3.0分</td></tr>
    <tr><th>作业内容：</th><td>
        <input id="310_content" name="310_content" value="<转义后的HTML要求正文>">
        <iframe id="_rtf_content310" src="/meol/common/ueditor/content.html?name=310">
    </td></tr>
    <tr><th>请输入你的答案</th><td>
        <div id="ueditor_div_IPT_BODY">
          <script id="ue_IPT_BODY" name="IPT_BODY" type="text/plain"></script>
        </div>
        <script>UE.getEditor("ue_IPT_BODY",{ textarea:"IPT_BODY",
                 serverUrl:"/meol/servlet/SerUpload" })</script>
    </td></tr>
  </table>
  <input type="button" value="提交" onclick="chk()">
  <input type="button" value="取消" onclick="history.back()">
</form>
```

- 编辑器是 **UEditor**（不是 CKEditor），实例 id `ue_IPT_BODY`，**字段名 `IPT_BODY`**
- 提交按钮 `onclick="chk()"`，`chk()` 里：`getNullEditorContent("IPT_BODY")` 校验非空 →
  `document.form1.submit()`；某些作业前面还有一句
  `if(!confirm("该作业不允许重复提交,确定提交作业吗？")) return false;`
- **作业要求正文**在 `input[name="{n}_content"]` 的 `value` 属性里（转义 HTML）。
  只读表格文本取不到（`text_content` 不含属性值），必须读属性。

### 提交请求

```
POST https://course.buct.edu.cn/meol/common/hw/student/write.do.jsp
Content-Type: application/x-www-form-urlencoded   （正文按 GBK 编码）
hwtid=<Z>&hwaid=<NA 或真实值>&IPT_BODY=<HTML>
成功判据：HTTP 302
```
`hwaid` 每次从 write.jsp 现场读取，不要复用旧值。

### 附件上传

```
GET  /meol/servlet/SerUpload?action=config            → 返回 UEditor 配置 JSON
POST /meol/servlet/SerUpload?action=uploadfile        multipart，字段名 upfile
```

实测返回：
```json
{"original":"upload-probe.pdf","size":590,"state":"SUCCESS","title":"upload-probe.pdf",
 "type":"pdf","url":"/meol/common/ckeditor/openfile.jsp?id=DBCP…HG","icon":"pdf"}
```

- **服务端接受 PDF**（配置里的 `fileAllowFiles` 只列了图片/视频，那只是客户端限制）。
  实测上传成功，且 `GET` 该 URL 返回 `200 / application/pdf / Content-Disposition: attachment`，
  字节数与本地完全一致 —— 附件链路可闭环。
- 禁止的扩展名（`fileForbitFiles`）：`.js .java .css .php .html .jsp .asp .class`
- 插入正文的 HTML 用 `<p><a href="{url}" target="_blank">{文件名}</a></p>` 即可（老师点开可下载）。

---

## 4. 平台限流（实测）

- 触发文案：**「你的访问过于频繁,请稍后再试」**
- 实测：**0.5 秒间隔会触发**（早期连续无间隔请求时立刻命中）；
  改为 **每次请求间隔 1.0–1.6 秒** 后，一口气跑 56 门课 / 128 个请求**全程未被限流**，
  耗时约 3 分 08 秒。
- 当前实现：命中即中止本轮 + 指数退避 5s→300s；单轮请求预算 150。

---

## 5. 数据实况（首次全量扫描，2026-09-23）

- 56 门课 / 216 个作业记录 / 未提交 158 条 / 请求 128 次 / 无误报漂移
- **平台课程实例多年复用，老作业一直留在列表里**：216 条里 179 条逾期超过 80 天，
  最早的到 2020 年（2394 天前）。逾期分布：

  | 逾期 | 条数 |
  | --- | --- |
  | 0–7 天 | 13 |
  | 7–30 天 | 8 |
  | 30–80 天 | 0 |
  | 80–180 天 | 76 |
  | 180–400 天 | 51 |
  | >400 天 | 52 |

  → 配置 `scan.hide_overdue_days: 80`（默认）**一律不展示、不提醒**。
  开启后：216 条 → 显示 37 条（未提交 25 / 已提交 12 / 其中已逾期 10），隐藏 179 条。
- ⚠ 仍显示的那 10 条逾期里，《大学物理实验(I)》的若干条其实是**其他班的实验时段**
  （形如 `生工2503-Thursday9:45-1Kelvin_Bridge`），不是本人作业。
  → 提醒默认只考虑 `can_submit=True`（`notify.new_requires_can_submit`），
  逾期汇总默认关闭（`notify.include_overdue`）。加上 80 天规则后，真正要盯的只有 15 条。

---

## 6. 仍未实测的部分

- 附件插入正文后老师端看到的实际效果（需真实提交一次才能确认，留给用户执行）
- 重复提交（`hwaid` 非 NA）时的行为
- 在线测试（`stu_qtest_navigate.jsp`）—— 按设计**不做任何代做**，只提醒
