# 自动化执行记录 — 北化在线作业助手每日摘要

## 2026-09-24 20:03

- 执行命令：`python -m buct_assistant once`（工作目录 buct-homework-assistant）。
- 结果：本次运行**未发出新通知**，因当天摘要已于 20:02:35 发送成功（`digest_sent_date=2026-09-24`，符合"每天一次"去重设计）。
- 当日摘要：标题 `[每日提醒] 16 个作业尚未提交`，board + desktop 双通道均 ok，记录留存于 `data/board_feed.jsonl` 的 `tier=digest` 条目。
- ⚠️ 扫描失败：课程列表解析到 0 门课，错误页为平台 `Permission Denied!`、`UserName: guest` → **保存的登录会话已失效，需要重新登录**。摘要内容来自 `data/state.json` 缓存（最近一次成功扫描 2026-09-24 03:28），新作业可能漏计。
- 排查要点（复用）：`data/board_feed.jsonl` 里有完整通知正文，可直接还原标题与各条剩余时间；`logs/app.log` 记录 digest 发送结果；`calibration/errors/lesson-empty-*.html` 是扫描现场快照，解码用 gbk。

## 2026-09-25 12:30

- 执行命令：`python -m buct_assistant once`，退出码 0，本次**正常发出新通知**（`digest_sent_date=2026-09-25`，board + desktop 双通道均 ok）。
- 摘要：标题 `[每日提醒] 16 个作业尚未提交`，正文 16 条按剩余时间升序（先逾期后剩余），尾部截断显示"…另有 1 个"。
- ⚠️ 扫描连续第二天失败：课程数 0，错误页仍是 `Permission Denied! / UserName: guest`（现场快照 `calibration/errors/lesson-empty-20260925-123044.html`）→ **登录会话仍未修复，摘要基于 `data/state.json` 缓存（264 条，last_seen 2026-09-24T03:28）**，新作业/新 DDL 可能漏计。需用户重新登录后跑一次以刷新缓存。
- 缓存作业里存在 ddl 属 2025 年的陈旧条目（如 36494:71968），说明缓存未清理，逾期天数可能被放大。

## 2026-09-26 17:11

- 执行命令：`python -m buct_assistant once`，退出码 0。本次运行**未发出新通知**——当天摘要已于 17:10:01 由前一次运行发送成功（`digest_sent_date=2026-09-26`，board + desktop 均 ok），本次被"每天一次"去重拦截。
- 当日摘要：标题 `[每日提醒] 16 个作业尚未提交`，正文 16 条按剩余时间升序，尾部"…另有 1 个"。正文可从 `data/board_feed.jsonl` 最新 `tier=digest` 条目完整还原。
- ⚠️ 扫描连续第三天失败：课程数 0，错误页仍为 `Permission Denied! / UserName: guest`（快照 `calibration/errors/lesson-empty-20260926-171103.html`）→ **登录会话始终未修复，摘要基于 `data/state.json` 缓存（264 条，最后一次成功扫描停留在 2026-09-24T03:28）**，新作业与新 DDL 可能全部漏计。需用户重新登录后跑一次以刷新缓存。
- 另注意 `logs/app.log` 显示 09-26 全天每小时都有自动运行（00:34–04:37 及 17:10），若这些也是自动化任务，建议合并/降频，避免无谓请求。

## 2026-09-27 12:30

- 执行命令：`python -m buct_assistant once`，退出码 0，本次**正常发出新通知**（`digest_sent_date=2026-09-27`，board + desktop 双通道均 ok）。
- 摘要：标题 `[每日提醒] 16 个作业尚未提交`，正文 16 条按剩余时间升序（先逾期后剩余），尾部截断"…另有 1 个"。正文可从 `data/board_feed.jsonl` 最新 `tier=digest` 条目（共 5 条）完整还原。
- ⚠️ 扫描连续第四天失败：课程数 0，现场快照 `calibration/errors/lesson-empty-20260927-123039.html`（判定与前三日一致，仍是 guest 会话失效）→ **摘要基于 `data/state.json` 缓存（264 条，最后成功扫描仍为 2026-09-24T03:28，已 stale 3 天）**，新作业与新 DDL 全部漏计。**必须让用户重新登录刷新缓存，否则摘要会长久停留在旧数据上。**

## 2026-09-28 12:30

- 执行命令：`python -m buct_assistant once`，退出码 0。本次**正常发出新通知**（`digest_sent_date=2026-09-28`，`{'board':'ok','desktop':'ok'}`）。
- 摘要：标题 `[每日提醒] 16 个作业尚未提交`，正文 16 条按剩余时间升序（先逾期后剩余），尾部截断"…另有 1 个"。正文可从 `data/board_feed.jsonl` 最新 `tier=digest` 条目完整还原（文件共 181 行）。
- ⚠️ 扫描连续第五天失败：课程数 0，现场快照 `calibration/errors/lesson-empty-20260928-123031.html`（gbk 解码后仍是 `Permission Denied！/ UserName: guest`），当天 09:18/10:25/11:26/12:27/12:30 多次运行全部同样失败。
- 缓存新鲜度：`data/state.json` 264 条 homeworks，`last_seen` 分布为 2026-09-24（216 条）/ 2026-09-23（48 条），即**最后成功扫描仍停在 2026-09-24T03:28，已 stale 4 天**。`login.last_login_ok` 被刷成 09-28（误导性字段，实际仍为 guest 会话）。缓存里还混有 ddl 属 2025-12-07 的陈旧条目，逾期天数被放大。
- 结论：摘要的数字与条目完全来自旧缓存，新作业/新 DDL 全部漏计。**唯一解法：用户重新登录后再跑一次 `once` 刷新缓存**；否则该自动化每天只会重复同一条旧摘要。

## 2026-09-29 20:12

- 执行命令：`python -m buct_assistant once`（工作目录 buct-homework-assistant），退出码 0。本次**正常发出新通知**（`digest_sent_date=2026-09-29`，`{'board':'ok','desktop':'ok'}`）。
- 摘要：标题 `[每日提醒] 16 个作业尚未提交`，正文 16 条按剩余时间升序（7 条逾期 + 8 条剩余，尾部"…另有 1 个"）。正文可从 `data/board_feed.jsonl` 最新 `tier=digest` 条目完整还原。
- ⚠️ 扫描连续第六天失败：课程数 0，快照 `calibration/errors/lesson-empty-20260929-201258.html`（gbk 解码仍为 `Permission Denied！/ UserName: guest`）。
- 缓存新鲜度：`data/state.json` 264 条，`last_seen` 分布 2026-09-24（216）/2026-09-23（48），**最后成功扫描仍停在 2026-09-24T03:28，已 stale 5 天**。`login.last_login_ok` 被刷成 09-29（误导字段，实际仍是 guest）。
- 结论不变：新作业/新 DDL 全部漏计，摘要每天重复同一份旧数据。**必须让用户重新登录后跑一次 `once`**。本次未修改任何项目文件。

## 2026-09-30 16:40

- 执行命令：`python -m buct_assistant once`，退出码 0。本次运行**未发出新通知**——当天摘要已于 16:39:37 由前一次运行发送成功（`digest_sent_date=2026-09-30`，`{'board':'ok','desktop':'ok'}`），本次被"每天一次"去重拦截。
- 当日摘要：标题 `[每日提醒] 16 个作业尚未提交`，正文 16 条按剩余时间升序（8 条逾期 + 7 条剩余，尾部"…另有 1 个"），正文可由 `data/board_feed.jsonl` 最新 `tier=digest` 条目完整还原。
- ⚠️ 扫描连续第七天失败：课程数 0，快照 `calibration/errors/lesson-empty-20260930-164028.html`（gbk 解码仍见 `isguest=true` / guest 拒绝）。
- 缓存新鲜度：`data/state.json` 264 条，`last_seen` 分布 2026-09-24（216）/2026-09-23（48），**最后成功扫描停在 2026-09-24T03:28，已 stale 6 天**。`login.last_login_ok` 被刷成 09-30（误导字段，仍是 guest）。
- 结论不变：摘要的数字与条目全部来自旧缓存，新作业/新 DDL 漏计。**必须让用户重新登录后跑一次 `once`**。本次未修改任何项目文件。

## 2026-10-02 20:15

- 执行命令：`python -m buct_assistant once`，退出码 0。本次**正常发出新通知**（`digest_sent_date=2026-10-02`，`{'board':'ok','desktop':'ok'}`）。
- 摘要：标题 `[每日提醒] 16 个作业尚未提交`，正文 16 条按剩余时间升序（11 条逾期 + 4 条剩余，尾部"…另有 1 个"）。正文可由 `data/board_feed.jsonl` 最新 `tier=digest` 条目（共 9 条）完整还原。
- ⚠️ 扫描连续第八天失败：课程数 0，快照 `calibration/errors/lesson-empty-20261002-201503.html`（gbk 解码仍为 `Permission Denied` / `UserName:` / `isguest`）。
- 缓存新鲜度：`data/state.json` 264 条，`last_seen` 分布 2026-09-24（216）/2026-09-23（48），**最后成功扫描仍停在 2026-09-24T03:28，已 stale 8 天**。`login.last_login_ok` 被刷成 10-02（误导字段，实际仍是 guest 会话）。
- 结论不变：摘要的数字与条目全部来自旧缓存，新作业/新 DDL 漏计。**必须让用户重新登录后跑一次 `once`**，否则此自动化只是每天重复同一份陈旧摘要。本次未手工修改任何文件。
