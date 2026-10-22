# 实施计划 · REQ-202610-0933 Telegram 通道（M4-04）

> 需求：REQ-202610-0933（backlog M4-04）｜ 分支：`feat/req-202610-0933-telegram-channel`
> 依赖：M4-02 站内通知中心（REQ-202610-0931）｜ 范围：`vps/` + 文档
> 目标：把每日评估后进入 `pushed` 的高质量推荐，以中文摘要消息推送到 Telegram。

## 1. 现状与缺口

- M4-01 每日评估（REQ-202610-0930）已产出 `qualified` / `filtered`，`daily_push` 在 09:00 把 `qualified` 标记为 `pushed`；
- M4-02 站内通知中心负责 D1 `notifications` 与 admin 页面，**不负责站外通道**；
- 现有 VPS 没有任何站外推送通道，也没有 Telegram 配置、发送服务、失败重试与送达记录。

## 2. 方案总览

```
Celery beat 09:05（daily_push 之后）
→ send_telegram_digest
→ 读取最近 TELEGRAM_DIGEST_WINDOW_HOURS 小时内 status=pushed 的推荐
→ 关联 trending_repositories 补全标题 / 简介 / 链接 / 今日 Star
→ 生成中文 HTML 摘要（按 4096 字符安全分片）
→ Telegram Bot API sendMessage（超时 / 429 / 5xx 指数退避重试）
→ 写 telegram_deliveries（pending / sent / failed，按日期 + chat 幂等）
```

手工入口：

- `POST /api/tasks/send-telegram-digest?user_id=&limit=&force=`：入队一次摘要推送；
- `POST /api/notifications/telegram/test`：同步发送一条连通性测试消息；
- `GET /api/notifications/telegram/status`：返回是否启用 / 已配置、脱敏 chat id 与最近一次送达。

## 3. 配置（全部走 `.env`，不进入客户端）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TELEGRAM_ENABLED` | `false` | 总开关；关闭时任务直接跳过，不发请求 |
| `TELEGRAM_BOT_TOKEN` | 空 | BotFather 颁发的 Bot Token（机密） |
| `TELEGRAM_CHAT_ID` | 空 | 接收消息的私聊 / 群组 id |
| `TELEGRAM_API_BASE` | `https://api.telegram.org` | Bot API 地址（可指向自建反代） |
| `TELEGRAM_TIMEOUT_SECONDS` | `10` | 单次 HTTP 超时 |
| `TELEGRAM_MAX_RETRIES` | `3` | 网络 / 429 / 5xx 的最大重试次数 |
| `TELEGRAM_RETRY_BASE_SECONDS` | `0.5` | 指数退避基数（429 优先用 `retry_after`） |
| `TELEGRAM_DAILY_LIMIT` | `10` | 单条摘要最多包含的推荐数 |
| `TELEGRAM_DIGEST_WINDOW_HOURS` | `24` | 摘要只取最近 N 小时进入 `pushed` 的推荐 |

## 4. 数据模型（VPS 本地 SQLite）

新增 `telegram_deliveries`：

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 送达记录 id |
| chat_id TEXT | 目标会话（API 输出时脱敏） |
| kind TEXT | `digest` / `test` |
| status TEXT | `pending` / `sent` / `failed` |
| item_count INTEGER | 摘要包含的推荐数 |
| message_count INTEGER | 实际发送的消息条数 |
| message_id TEXT | 第一条消息的 Telegram message_id |
| dedupe_key TEXT | 幂等键（日期 + 用户 + chat） |
| error TEXT | 失败原因（截断、已脱敏） |
| created_at / finished_at | 开始 / 结束时间 |

M4-08「推送记录与回执」落地后可在本表基础上扩展为全通道统一记录。

## 5. 实现要点

### 5.1 发送服务（`vps/app/services/telegram.py`）

- `TelegramClient`：构造时校验 token / chat id；URL 只在内部拼接，错误信息统一脱敏；
- `send_text`：按 4096 字符分片，逐片 `sendMessage`（`parse_mode=HTML`、关闭预览）；
- 重试：网络异常 / 5xx / 429 指数退避；429 读取 `parameters.retry_after`（上限 60s）；4xx 立即失败；
- `build_digest_messages`：按条目分块，保证不截断 HTML 标签；标题、理由、链接均做 HTML 转义；
- `send_digest`：校验开关 / 配置 → 按窗口与状态取数 → 幂等检查 → 生成消息 → 发送 → 写送达记录；
- 空结果、未启用、未配置均返回结构化状态，不抛异常、不误报失败。

### 5.2 任务与接口

- `app.tasks.jobs.send_telegram_digest`：薄封装，异常降级为结构化结果；
- `app.tasks.celery_app`：beat 每日 09:05 执行；
- `app/api/notifications.py`：状态 / 测试消息接口，统一 `X-Internal-Token`；
- `app/api/tasks.py`：摘要入队接口。

### 5.3 测试（全部离线）

- 纯函数：HTML 转义、消息分片、摘要条目构造；
- `httpx.MockTransport`：成功、429 重试、5xx 重试耗尽、400 不重试、网络异常脱敏；
- 服务：未启用 / 未配置 / 空数据 / 正常发送 / 幂等跳过 / force 重发 / 失败记录；
- API：状态字段、测试消息、内部令牌鉴权；任务：eager 模式下调用服务并返回结果。

## 6. 文件清单

- `vps/app/services/telegram.py`（新增）
- `vps/app/api/notifications.py`（新增）
- `vps/app/models.py`、`vps/app/config.py`、`vps/app/runtime.py`、`vps/app/schemas.py`、`vps/app/main.py`
- `vps/app/api/tasks.py`、`vps/app/tasks/jobs.py`、`vps/app/tasks/celery_app.py`
- `vps/tests/test_telegram.py`（新增）
- `vps/.env.example`、`deploy/env/openfactory.env.example`
- `vps/README.md`、`docs/architecture/overview.md`、`docs/architecture/data-model.md`、
  `docs/requirements/backlog.md`、`docs/requirements/open-questions.md`、`docs/planning/task-planning.md`

## 7. 验证计划

- `cd vps && bacs-heavy .venv/bin/pytest -q`；
- `python -m compileall vps/app`、`git diff --check`；
- 本需求不改 edge / admin，按项目惯例不重复跑其构建，文档中注明。

## 8. 风险与边界

- Telegram Bot Token 属于机密：只存 `.env`，状态接口不返回，错误信息脱敏；
- 单用户口径：`TELEGRAM_CHAT_ID` 为单会话；多用户 / 多会话偏好由 M4-06 承接；
- 去重与静默策略的完整口径由 M4-07 承接，本需求只做「同一天同一会话不重复发送」的最小幂等；
- 送达回执（已读 / 失败重投）由 M4-08 承接，本需求记录发送结果；
- 群组 chat id 为负数、Bot 需先被拉入群并可发言，部署时人工确认。
