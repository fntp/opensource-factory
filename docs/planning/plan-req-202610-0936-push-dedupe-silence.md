# 实施计划 · REQ-202610-0936 推送去重与静默策略（M4-07）

> 需求：REQ-202610-0936（backlog M4-07）｜ 分支：`feat/req-202610-0936-push-dedupe-silence`
> 依赖：M4-02 站内通知中心（REQ-202610-0931）；同时以 M4-01 每日评估（REQ-202610-0930）产出的
> `qualified` 推荐作为推送输入 ｜ 范围：`vps/` + 文档
> 目标：在「推荐进入 pushed」与「通道真正下发」之间加一道统一策略闸门，避免重复打扰和夜间打扰。

## 1. 现状与缺口

- M4-01 每日评估产出 `qualified` / `filtered`；`daily_push` 每天 09:00 把 `qualified` 批量标记为 `pushed`；
- M4-02 站内通知中心按 `recommendations.status='pushed'` 惰性物化通知，但只保证「同一条推荐不重复生成通知」；
- M4-03 / M4-04 / M4-05 各通道分别按自己的幂等键发送，**没有跨通道、跨天的统一去重账本**；
- 没有静默时段（免打扰）配置：一旦定时任务落在夜间或用户休息时间，仍会直接推送；
- 没有单用户每日推送上限，批量 `qualified` 较多时可能一次推送十几条。

## 2. 方案总览

```
qualified 推荐
  → daily_push（09:00 / 静默结束后重试）
      → 读取 PUSH_* 策略配置
      → 静默时段？ → 保留 qualified，记录 deferred，等待重试任务
      → 去重窗口内已推送过同仓库？ → 标记 expired，记录 skipped
      → 今日已达单用户上限？ → 保留 qualified，记录 skipped
      → 标记 pushed + 写 push_events(prepared)
  → 站内通知中心 / Bark / Telegram / Email 只消费 pushed
```

关键点：**静默与去重都收敛在 `daily_push` 这一个入口**。通道只消费 `pushed`，因此无需逐通道重复实现；
通道侧如做二次重试，可调用 `POST /api/push/policy/check` 做发送前复核。

## 3. 策略口径

| 规则 | 默认值 | 说明 |
| --- | --- | --- |
| `PUSH_POLICY_ENABLED` | `true` | 总开关；关闭时 `daily_push` 保持旧行为 |
| `PUSH_QUIET_HOURS_START` | `22:00` | 静默开始（用户时区，`HH:MM`；留空 / 与结束相同表示不静默） |
| `PUSH_QUIET_HOURS_END` | `08:00` | 静默结束；支持跨午夜窗口 |
| `PUSH_TIMEZONE` | `Asia/Shanghai` | 静默时段解释所用 IANA 时区 |
| `PUSH_DAILY_LIMIT` | `3` | 每用户每日最多推送条数（按仓库去重计数；0 表示不限） |
| `PUSH_DEDUPE_DAYS` | `7` | 同一用户同一仓库的去重窗口（天；0 表示只做当日幂等） |
| `PUSH_DEDUPE_CROSS_CHANNEL` | `true` | `true` 时跨通道去重；`false` 时仅同通道去重 |
| `PUSH_RETRY_INTERVAL_MINUTES` | `30` | 静默结束后的重试任务间隔 |

边界：

- 静默窗口跨午夜（如 22:00–08:00）时，`22:00 ≤ t` 或 `t < 08:00` 均视为静默；
- 静默期间**不改变推荐状态**，只记录 deferred；重试任务在窗口结束后继续；
- 去重命中时把推荐标记为 `expired`，避免每天重复进入候选；
- 每日上限按「当日已 prepared / sent 的去重仓库数」计算，失败（failed）不占额度；
- 站内通知属于被动拉取，仍受 `daily_push` 的状态闸门约束，因此同样遵守静默与上限。

## 4. 数据模型（VPS 本地 SQLite）

新增 `push_events` 统一推送账本：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | 事件 id（UUID hex） |
| user_id | TEXT | 用户 id |
| repo_id | TEXT | 仓库 id（`owner/repo`） |
| recommendation_id | TEXT | 关联推荐 id（可空） |
| channel | TEXT | `inapp` / `bark` / `telegram` / `email` |
| status | TEXT | `prepared` / `sent` / `failed` / `skipped` |
| dedupe_key | TEXT | 去重键 `user_id:repo_id` |
| event_key | TEXT UNIQUE | 幂等键 `user_id:repo_id:channel:YYYY-MM-DD` |
| reason | TEXT | 跳过 / 失败原因（`quiet_hours` / `duplicate_repo` / `daily_limit` 等） |
| created_at / updated_at / sent_at | DATETIME | 记录时间 |

索引：`(user_id, repo_id, updated_at)`、`(user_id, updated_at)`、`event_key` 唯一。

## 5. 实现要点

### 5.1 策略服务（`vps/app/services/push_policy.py`）

- 纯函数：`parse_clock` / `resolve_timezone` / `is_quiet_hours` / `next_allowed_at` /
  `build_dedupe_key` / `build_event_key`，便于单测与复用；
- `evaluate_push`：按「开关 → 静默 → 去重 → 每日上限」顺序返回结构化决策
  `{allowed, reason, quietHours, nextAllowedAt, dedupeKey, existingEventId}`；
- `record_push_event`：按 `event_key` 幂等 upsert，状态只升不降（`skipped < prepared < failed < sent`）；
- `filter_push_candidates`：批量预演（不写库），供 API / 任务复用；
- `policy_status`：输出配置、当前是否静默、下次可推送时间、今日计数与最近事件。

### 5.2 任务接入（`vps/app/tasks/jobs.py`）

- `daily_push` 改为逐条评估：静默 → 全部保留 `qualified` 并返回 `silenced`；去重 → `expired`；
  超限 → 保留 `qualified`；通过 → `pushed` + `push_events(prepared)`；
- 新增 `retry_deferred_push` 任务与 beat 计划：每 `PUSH_RETRY_INTERVAL_MINUTES` 分钟检查一次，
  仅在非静默且有 `qualified` 时执行，避免静默结束后要等到次日；
- 返回结构化统计 `pushed / skipped / deferred / skippedReasons / nextAllowedAt`。

### 5.3 接口（`vps/app/api/push_policy.py`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/push/policy/status` | GET | 策略配置、静默状态、今日计数、最近事件 |
| `/api/push/policy/check` | POST | 对单个候选做发送前预演（不写库） |
| `/api/push/policy/events` | POST | 记录一次通道投递事件（`sent` / `failed` / `skipped`） |
| `/api/push/policy/events` | GET | 查询最近事件（按用户 / 通道 / 状态过滤） |

全部接口复用 `require_internal_token`，与 `/api/tasks/*` 一致。

### 5.4 测试（全部离线）

- 纯函数：`HH:MM` 解析、跨午夜静默、时区、去重键 / 事件键；
- 服务：去重窗口命中 / 过期、跨通道 / 同通道、每日上限、失败不占额度、事件幂等；
- 任务：静默时 deferred、去重时 expired、超限保留 qualified、正常标记 pushed；
- API：状态字段、check 预演、事件写入 / 查询、内部令牌鉴权；
- 旧库兼容：`create_all` 建新表，重复初始化幂等。

## 6. 文件清单

- `vps/app/services/push_policy.py`（新增）
- `vps/app/api/push_policy.py`（新增）
- `vps/app/models.py`、`vps/app/config.py`、`vps/app/runtime.py`、`vps/app/schemas.py`、`vps/app/main.py`
- `vps/app/tasks/jobs.py`、`vps/app/tasks/celery_app.py`
- `vps/tests/test_push_policy.py`（新增）
- `vps/.env.example`、`deploy/env/openfactory.env.example`
- `vps/README.md`、`docs/architecture/overview.md`、`docs/architecture/data-model.md`、
  `docs/requirements/backlog.md`、`docs/planning/task-planning.md`

## 7. 验证计划

- `cd vps && bacs-heavy .venv/bin/pytest -q`；
- `python -m compileall vps/app`、`git diff --check`；
- 本需求不改 edge / admin，按项目惯例不重复跑其构建，文档中注明。

## 8. 风险与边界

- 静默时段当前为全局配置；M4-06 推送偏好落地后可按用户时区 / 时间覆盖（接口保持兼容）；
- `push_events` 是策略账本，不是完整送达回执；M4-08 可在其基础上扩展全通道回执；
- 每日上限按「仓库」计数，同一仓库多通道只算一次，避免通道叠加放大打扰；
- 时区数据依赖系统 tzdata；非法时区回退 `Asia/Shanghai`，不阻塞任务；
- 静默重试任务只处理 `qualified`，不会重新激活 `expired` / `dismissed` / `saved`。
