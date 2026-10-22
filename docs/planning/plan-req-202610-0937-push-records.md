# 实施计划 · REQ-202610-0937 推送记录与回执（M4-08）

> 需求：REQ-202610-0937（backlog M4-08）｜ 分支：`feat/req-202610-0937-push-records`
> 依赖：M4-03 Bark（REQ-202610-0932）、M4-04 Telegram（REQ-202610-0933）、M4-05 Email（REQ-202610-0934）
> 范围：`vps/` + 文档；目标：把三个站外通道的投递结果收敛为一张统一记录表，并提供送达回执写入与查询能力。

## 1. 现状与缺口

- Bark：只把结果写回 `recommendations.bark_sent_at` / `bark_error`，没有独立投递记录；
- Telegram：`telegram_deliveries` 记录 `pending / sent / failed`，无回执；
- Email：`email_deliveries` 记录 `sent / failed`，无回执；
- 三个通道字段、状态口径不一致，无法在一个页面 / 接口里查看「今天推了什么、送到没有、为什么失败」；
- 没有接收 SMTP / Bot / Bark 服务商回执的入口，失败后也无法人工补记送达状态。

## 2. 方案总览

```
Bark dispatch ─┐
Telegram send ─┼─→ push_records 服务 ─→ push_deliveries（统一投递记录）
Email send ────┘                          └─→ push_receipts（回执流水）
                                                    ↑
SMTP / Bot / Bark 服务商回调 ──→ POST /api/push/receipts（X-Internal-Token）
人工补记送达 / 失败 ───────────→ 同一接口（source=manual）
```

查询接口：

- `GET /api/push/records`：按通道 / 状态 / 类型 / 时间 / 关键字过滤，分页返回；
- `GET /api/push/records/stats`：总量、分通道 / 分状态计数、回执计数与送达率；
- `GET /api/push/records/{id}`：单条记录 + 回执时间线；
- `POST /api/push/receipts`：写入回执（幂等，支持 `accepted / delivered / bounced / failed`）。

## 3. 数据模型（VPS 本地 SQLite）

### 3.1 `push_deliveries`

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 统一投递记录 id |
| channel TEXT | `bark` / `telegram` / `email` |
| kind TEXT | `digest` / `test` / `single` |
| target TEXT | 原始目标（API 输出时脱敏；Bark 存 group 名，不存 device key） |
| target_type TEXT | `chat` / `email` / `group` |
| status TEXT | `pending` / `sent` / `delivered` / `failed` / `skipped` |
| item_count INTEGER | 推送条目数 |
| message_count INTEGER | 实际消息条数 |
| message_id TEXT | 服务商消息 id（Email Message-ID / Telegram message_id） |
| subject TEXT | 邮件主题 / Bark 标题 |
| dedupe_key TEXT | 通道幂等键，便于和通道表对账 |
| receipt_status TEXT | 最新回执状态：`accepted` / `delivered` / `bounced` / `failed` |
| receipt_detail TEXT | 最新回执说明（脱敏、截断） |
| error TEXT | 发送失败原因（脱敏、截断） |
| attempts INTEGER | 尝试次数（当前固定为 1，预留给重投） |
| source_id TEXT | 通道表 id：`telegram_deliveries.id` / `email_deliveries.id`；Bark 为推荐 id |
| user_id TEXT | 关联用户，便于后续按用户筛选 |
| created_at / sent_at / finished_at / delivered_at | 生命周期时间 |

索引：`channel`、`status`、`created_at`、`dedupe_key`、`source_id`。

### 3.2 `push_receipts`

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 回执 id |
| delivery_id TEXT | 关联 `push_deliveries.id` |
| channel TEXT | 冗余通道，便于按通道统计 |
| status TEXT | `accepted` / `delivered` / `bounced` / `failed` |
| source TEXT | `provider` / `manual` / `system` |
| external_id TEXT | 服务商回执 id，用于幂等 |
| detail TEXT | 回执说明（脱敏、截断） |
| occurred_at DATETIME | 回执发生时间（服务商时间优先） |
| created_at DATETIME | 落库时间 |

索引：`delivery_id`、`status`、`external_id`。

## 4. 状态与回执规则

- 发送成功 → `sent`；发送失败 → `failed`；dry-run / 去重跳过 → `skipped`；
- `accepted` 回执把 `pending` 提升为 `sent`；
- `delivered` 回执把记录提升为 `delivered` 并写 `delivered_at`；
- `bounced` / `failed` 回执把 `sent` 降为 `failed`（保留原发送错误，回执详情单独字段）；
- 已 `delivered` 的记录不被迟到的 `accepted` / `bounced` 回执降级，但回执流水仍完整保留；
- 同一 `delivery_id + external_id + status` 重复回调只落一条，返回已有回执（幂等）。

## 5. 通道接入

- Bark：`dispatch_bark_notifications` 每条推荐写一条 `single` 记录（成功 / 失败 / dry-run）；
  `send_bark_test` 写 `test` 记录；
- Telegram：`_create_delivery` 同步创建统一记录，`_finish_delivery` 回写状态、消息数与 message_id；
- Email：`_record_delivery` 同步写统一记录（收件人原值仅落库，接口输出脱敏）；
- 回执写入时同步通道表状态：Email / Telegram 的 `sent|failed` 跟随回执更新，避免两套状态打架。

## 6. 安全与脱敏

- 所有 `/api/push/*` 接口沿用 `X-Internal-Token`；
- API 输出：邮箱保留首字符与域名，chat id / 其它目标保留首尾各 2~4 位；
- 不记录 Bark device key、Telegram bot token、SMTP 密码；
- 错误与回执详情统一截断（≤500 字），避免把服务商响应中的凭据写进库。

## 7. 测试计划（全部离线）

- 脱敏函数：邮箱 / chat id / 空目标；
- 服务：创建 / 列表过滤 / 分页 / 统计 / 详情；
- 回执：accepted → sent、delivered → delivered、bounced → failed、迟到回执不降级、重复回调幂等；
- 通道接入：Bark dispatch 成功 / 失败 / dry-run、Telegram 摘要、Email 摘要均生成统一记录；
- API：列表、统计、详情、回执写入、内部令牌鉴权、404。

## 8. 文件清单

- `vps/app/models.py`（新增 `PushDelivery` / `PushReceipt`）
- `vps/app/services/push_records.py`（新增）
- `vps/app/services/bark.py`、`telegram.py`、`email_channel.py`（接入统一记录）
- `vps/app/api/push.py`、`vps/app/schemas.py`
- `vps/tests/test_push_records.py`（新增）
- `docs/architecture/overview.md`、`docs/architecture/data-model.md`
- `docs/requirements/backlog.md`、`docs/planning/task-planning.md`、`vps/README.md`

## 9. 验证

- `cd vps && bacs-heavy .venv/bin/pytest -q`
- `python -m compileall -q vps/app`、`git diff --check`
- 本需求不改 edge / admin，按项目惯例不重复跑其构建。

## 10. 边界

- 服务商真实回执需要各自控制台配置 webhook 指向 `POST /api/push/receipts`，本需求提供统一入口与幂等语义，不实现具体服务商签名适配；
- Bark / Telegram 官方 API 不提供逐条送达回执，默认只有发送结果，送达状态可由人工或后续适配器补记；
- 历史 `telegram_deliveries` / `email_deliveries` 不回填，统一记录从本版本起生效；
- 多用户推送偏好、去重与静默分别由 M4-06 / M4-07 承接，本需求只做记录与回执。
