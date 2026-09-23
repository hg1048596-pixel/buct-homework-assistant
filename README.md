# 北化在线作业助手

对接北京化工大学「北化在线」教学平台（https://course.buct.edu.cn/）的本地助手：
抓取未提交作业（含要求正文、DDL、剩余时间）→ 四渠道提醒 → 你把内容交给它 → **你确认后**才提交。

> 非官方工具，仅限本人账号、个人自用。使用后果自负。

## 环境要求

- Windows 10 / 11
- **需要先安装 [WorkBuddy](https://www.workbuddy.cn/)（装在默认位置即可）**。
  本项目的所有 `.bat` 脚本和任务计划都依赖 WorkBuddy 托管的 Python：
  `%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe`，
  路径在脚本里用 `%USERPROFILE%` 写死，所以不需要另外安装 Python，
  但没有 WorkBuddy 就没有这个解释器，脚本会直接报“找不到文件”。
- 不想装 WorkBuddy 的话：自己装 Python 3.11+ 并建一个 venv，把
  `scripts\*.bat` 开头的 `set "PY=..."` / `set "PYW=..."` 改成你的解释器路径即可。
  （`.bat` 由 `tools/make_bats.py` 生成，改完生成器重新跑一遍也行。）

## 快速开始

1. 双击 `scripts\setup_env.bat` —— 安装依赖并跑 SM2 自检
2. 双击 `scripts\set_credentials.bat` —— 录入学号密码（DPAPI 加密，只存本机）
3. 双击 `scripts\login_dump.bat` —— 登录并 dump 页面到 `calibration\raw\`（阶段 1 校准）
4. 双击 `scripts\run_console.bat` —— 启动网页控制台 http://127.0.0.1:8765
5. 双击 `scripts\stop_console.bat` —— 停止正在运行的助手（控制台与后台进程）

## 目录

| 目录 | 用途 |
| --- | --- |
| `src/buct_assistant/` | 源码 |
| `scripts/` | 双击即用的 .bat |
| `tools/` | 校准与诊断工具（dump / CAS 探测 / 看板 diff） |
| `calibration/` | 阶段 1 dump 的页面与「技术事实基线」 |
| `data/` | state.json、提交草稿 outbox、审计日志 |
| `wheels/` | 离线依赖包（沙箱内 pip 联网受限，改用 curl 下载后本地安装） |
| `%LOCALAPPDATA%\buct-assistant\` | 加密后的凭据与会话 cookie（不在项目目录内） |

## 命令行

```bat
python -m buct_assistant selftest           :: SM2 加密自检（不联网）
python -m buct_assistant set-credentials    :: 录入凭据
python -m buct_assistant login              :: CAS 登录并保存会话
python -m buct_assistant whoami             :: 检查会话是否存活
python -m buct_assistant once               :: 跑一次「扫描 + 提醒」后退出（定时任务用这个）
python -m buct_assistant serve              :: 启动网页控制台
```

## 通知行为

### 三种通知

| 时机 | 内容 | 开关位置 |
| --- | --- | --- |
| 作业**一进入 24 小时窗口** | 该作业的课程、标题、截止时间、剩余时间 | 设置页 → 「一进入 24 小时窗口就立刻弹通知」 |
| 每天 **12:30** | **所有未提交作业 + 各自剩余时间**的摘要 | 设置页 → 「每日摘要」+ 时间 |
| 发现新作业 | 新增作业合并成一条 | 设置页 → 通知渠道总开关 |

渠道（Windows 桌面通知 / 邮件 / 微信推送）与上面每一条规则都**可以在设置页单独开关**，
也可以改摘要时间和范围（所有未提交 / 只看还能提交的）、是否包含逾期项。
设置页还有「测试一条通知」「测试每日摘要」两个按钮，用来确认能弹出来。

### 「弹完就退出，通知仍然保留」

这是有意设计的：Windows 的 Toast 一旦弹出就归系统管，**进程退出后通知仍留在通知中心**
（Action Center / 右下角通知面板），点它还能打开控制台。所以定时任务只需要短命地跑一次
`once`，发完通知就退出，不需要常驻进程。

### 每日摘要不会漏发

摘要用的是「**到点后的第一次运行就补发、每天只发一次**」，而不是「必须正好在 12:30 那一刻
进程活着」。所以定时任务哪怕晚了几十分钟、或者那一次被平台限流了，摘要照样会发出来，
而且不会因为重复运行而重复打扰。

## 用 WorkBuddy 自动化任务管理启动与关闭

程序本身不需要常驻。**启动与关闭都交给 WorkBuddy 的自动化任务**即可：
建一条定时自动化，让它周期性执行 `python -m buct_assistant once`——
跑完自己就退出了，不存在「关闭」这一步。这样有两个好处：不需要开机自启、
不需要常驻后台，也不会因为控制台忘了关而一直在跑。

已内置两条自动化（可在 WorkBuddy 里随时改时间或停用）：

| 自动化 | 频率 | 作用 |
| --- | --- | --- |
| 北化作业助手 · 定期扫描与系统通知 | 每小时 | 作业跨入 24 小时窗口时弹通知（最迟 1 小时内送达） |
| 北化作业助手 · 每日 12:30 未提交作业摘要 | 每天 12:30 | 弹出「所有未提交作业 + 剩余时间」的摘要 |

两条都只是跑 `once`，跑完自己退出，不存在"关闭"这一步。

如果你想改用 Windows 任务计划程序，双击 `scripts\install_task.bat` 也行（每 30 分钟一次）；
两者靠 `data\scan.lock` 互斥，不会重复跑；摘要本身也有"每天只发一次"的保护，不会重复打扰。

## 安全边界

工具**不做**这些事：在线测验/考试代做、刷课时、绕过验证码或 MFA、对抗平台封禁、
批量一键提交、访问他人账号。

提交必须经过四重闸门：dry-run 逐字预览 → 手工键入作业标题前 4 字解锁 → 一次性 CSRF token
→ 提交前重新拉取确认该作业仍未提交。

## 平台事实（2026-09 实测）

- 登录已改为 `portal.buct.edu.cn` 统一身份认证 CAS + **SM2 口令加密**（老 `loginCheck.do` 已废弃）
- 平台页面为 **GBK** 编码，JSP 架构
- 课程作业页为 `jpk/course/vworkpage/index.jsp`（参数可能是 `lId=` 或 `courseId=`）
- 平台有频率限制，命中会返回「你的访问过于频繁,请稍后再试」
