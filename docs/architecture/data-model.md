# 数据模型 · Data Model

> 文档编号：AR-02 ｜ 维护人：fntp ｜ 数据资产：[docs/assets/d1-schema.sql](../assets/d1-schema.sql)（与 `edge/migrations/0001_init.sql` 同步）

## 1. 总览

```
users ──< sessions
  │
  │ (user_id)
  ▼
my_repositories >──< repo_tags >──< tags
  │
  │ (category_id)
  ▼
categories（parent_id 自关联，无限级）

trending_repositories        （独立，公共数据）
recommendations              （user_id 可空 = 全局推荐）
  │ (recommendation_id)
  ▼
notifications                （站内通知，按用户隔离）
```

## 2. 核心表（需求原文，字段保持不变）

### 2.1 `my_repositories` 已收藏 / 自有仓库

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | `owner/repo` |
| platform | TEXT | `github` / `gitee` |
| name | TEXT | 仓库名 |
| description | TEXT | 简介 |
| html_url | TEXT | 仓库地址 |
| stars | INTEGER | Star 数 |
| language | TEXT | 主语言 |
| readme_summary | TEXT | VPS 大模型生成的项目摘要 |
| category_id | TEXT | 关联分类 |
| created_at | DATETIME | 收录时间 |

> 本仓库扩展列（不改变上述语义）：`user_id`、`owner`、`forks`、`updated_at`、`synced_at`。

### 2.2 `trending_repositories` 热榜项目

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | `owner/repo`（或平台内唯一 id） |
| platform | TEXT | `github` / `gitee` |
| name | TEXT | 项目名 |
| html_url | TEXT | 项目地址 |
| stars_today | INTEGER | 今日新增 Star |
| description | TEXT | 简介 |
| tech_stack | TEXT | 自动提取的技术栈 |
| crawled_at | DATE | 抓取日期 |

> 扩展列：`owner`、`language`、`stars`（总 Star）。

### 2.3 `categories` 分类

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | 分类 id |
| name | TEXT | 名称（如：支付系统 / 脚手架） |
| parent_id | TEXT | 父分类（NULL = 顶级），无限级 |

> 扩展列：`description`、`sort_order`。

## 3. 扩展表

### 3.1 `users` 用户

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | GitHub 数字 id（字符串化） |
| login / name / email / avatar_url | GitHub 资料 |
| created_at | 首次登录时间 |

### 3.2 `sessions` 会话

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 会话 token 的 SHA-256 哈希（不存明文） |
| user_id | 关联用户 |
| created_at / expires_at | 创建 / 过期时间 |

### 3.3 `tags` / `repo_tags` 标签

- `tags`：`id`、`name`（唯一）、`count`（冗余计数）；
- `repo_tags`：仓库与标签的多对多关联。

### 3.4 `recommendations` 推荐

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 推荐 id |
| user_id | 目标用户（NULL = 全局） |
| owner / name / description / language / stars / url | 推荐项目快照 |
| score REAL | 综合得分 0~1（相似度 × 0.8 + 热榜热度 × 0.2） |
| match_score REAL | 原始余弦相似度（M4-01 匹配度硬门槛；历史数据缺失时回退到 `score`） |
| quality_score REAL | 每日评估质量分 0~1（仓库质量 × 0.7 + 理由质量 × 0.3） |
| quality_detail TEXT | 评估明细 JSON（各分量、阈值、是否通过） |
| evaluation_run_id TEXT | 最近一次评估运行 id |
| evaluated_at DATETIME | 最近评估时间 |
| reason TEXT | 推荐理由（中文） |
| based_on TEXT | 依据（JSON 数组，如 `["AI/LLM","Python"]`） |
| status TEXT | `new` / `qualified` / `filtered` / `pushed` / `saved` / `dismissed` / `expired` |
| created_at | 生成时间 |

### 3.5 `recommendation_evaluation_runs` 评估运行（M4-01）

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 运行 id |
| user_id | 目标用户（NULL = 全量评估） |
| status TEXT | `running` / `completed` / `failed` |
| match_threshold / quality_threshold REAL | 本次运行使用的门槛 |
| total / qualified / filtered / skipped / failed INTEGER | 运行计数 |
| error TEXT | 失败原因（截断） |
| created_at / finished_at | 开始 / 结束时间 |

### 3.6 `notifications` 站内通知

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 通知 id |
| user_id | 接收用户 |
| type TEXT | 通知类型（`recommendation` / `system`） |
| title / body | 标题与正文 |
| url | 跳转地址（通常为仓库 URL） |
| repo_id / recommendation_id | 关联仓库 / 推荐（可空） |
| dedupe_key TEXT | 去重键，同一用户内唯一 |
| score / reason / language / stars | 推荐快照，便于列表直接渲染 |
| status TEXT | `unread` / `read` / `dismissed` |
| payload TEXT | 扩展 JSON（如 `{basedOn: string[]}`） |
| created_at / read_at | 生成 / 阅读时间 |

**生成规则**：`GET /api/notifications` 与 `/unread-count` 触发惰性物化——把当前用户（含全局）`recommendations.status = 'pushed'` 且尚未通知的记录写入 `notifications`，由唯一索引 `(user_id, recommendation_id)` / `(user_id, dedupe_key)` 保证幂等。通知忽略时同步把关联推荐置为 `dismissed`。

### 3.7 `push_preferences` 推送偏好（M4-06）

| 字段 | 说明 |
| --- | --- |
| user_id TEXT PK | 用户 id |
| enabled INTEGER | 是否启用每日推送（0 / 1） |
| time_of_day TEXT | 推送时间 `HH:MM`（用户本地时区） |
| timezone TEXT | IANA 时区，默认 `Asia/Shanghai` |
| min_score REAL | 匹配度阈值（0~1，默认 0.35） |
| min_quality_score REAL | 质量分阈值（0~1，默认 0.55） |
| channel_inapp / channel_bark / channel_telegram / channel_email INTEGER | 通道开关（0 / 1） |
| updated_at TEXT | 最近保存时间（ISO 8601） |

**默认值**：未保存过偏好的用户按默认值处理（启用、09:00、Asia/Shanghai、匹配度 0.35、质量分 0.55、仅站内通知开启）。VPS 推送任务通过内部接口读取偏好，读取失败时回退默认值，不阻塞推送。

## 4. 索引策略

| 表 | 索引 | 用途 |
| --- | --- | --- |
| my_repositories | `(user_id)`、`(category_id)`、`(platform)` | 列表与筛选 |
| trending_repositories | `(stars_today DESC)`、`(crawled_at)` | 榜单查询 |
| sessions | `(user_id)`、`(expires_at)` | 会话校验与清理 |
| repo_tags | `(repo_id)`、`(tag_id)` | 反查 |
| recommendations | `(user_id, score DESC)`、`(evaluation_run_id)` | 推荐列表 / 评估批次查询 |
| notifications | `(user_id, status, created_at DESC)` | 通知列表与未读数 |
| notifications | `(user_id, recommendation_id)` UNIQUE、`(user_id, dedupe_key)` UNIQUE | 物化幂等 / 去重 |

## 5. 向量数据（M3）

### 5.1 本地向量表（VPS SQLite）

向量由 VPS 生成并持久化在本地，D1 不存向量；M3-03 负责把本地向量同步到 Cloudflare Vectorize。

`repo_vectors`（联合主键 `source + repo_id`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| source | TEXT PK | `my`（收藏库）/ `trending`（热榜） |
| repo_id | TEXT PK | 仓库 id（`owner/repo`） |
| model | TEXT | 编码模型名（`EMBEDDING_MODEL`） |
| backend | TEXT | `sentence-transformers` / `flagembedding` / `hash` |
| dim | INTEGER | 向量维度（hash 兜底 256，BGE-M3 1024） |
| text_hash | TEXT | 参与编码文本的 SHA-256（增量判断） |
| vector | TEXT | JSON 数组（保留 6 位小数） |
| created_at / updated_at | DATETIME | 生成 / 更新时间 |

`vectorization_runs`（运行记录，支持断点续跑）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | 运行 id（UUID hex） |
| scope | TEXT | `my` / `trending` / `all` |
| status | TEXT | `running` / `completed` / `failed` |
| model / backend / dim | — | 本次运行使用的编码配置 |
| force / limit / batch_size | — | 运行参数 |
| total / processed / vectorized / skipped / failed | INTEGER | 计数 |
| cursor_source / cursor_repo_id | TEXT | 已提交批次的游标 |
| error | TEXT | 失败原因 |
| created_at / updated_at / finished_at | DATETIME | 时间 |

### 5.2 Vectorize 目标索引（M3-03）

| 项 | 值 |
| --- | --- |
| 模型 | BGE-M3（本地推理；M3-01 完成后可能切换量化模型） |
| 维度 | 1024（以实际 `EMBEDDING_MODEL` 输出为准，与 `VECTORIZE_INDEX_DIM` 对齐） |
| 指标 | cosine |
| 向量 ID | `v1_ + sha256("{source}:{repo_id}")[:32]`（固定 35 字符） |
| 元数据 | `source`（`my` / `trending`）、`repo_id`、`text_hash`、`model`、`dim` |
| 同步方向 | VPS `repo_vectors` → edge 写入 Vectorize（批量 upsert / 重试 / 对账） |
| 增量依据 | `repo_vectors.text_hash` 与 `vector_sync_state.text_hash` 比对 |

### 5.3 同步状态表（VPS SQLite）

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `vector_sync_state` | `source, repo_id, vector_id, text_hash, status, attempts, last_error, synced_at, checked_at` | 逐条同步状态；`status` 为 `pending/synced/failed/dim_mismatch` |
| `vector_sync_runs` | `id, kind, scope, status, total, processed, synced, skipped, failed, deleted, checked, missing, repaired, orphan_scan` | 每次同步 / 对账运行统计与游标 |

`vector_sync_runs.status`：`running/completed/partial/failed`；`kind`：`sync/reconcile`。

### 5.4 推送事件账本（M4-07）

`push_events` 是推送去重 / 静默 / 日限额的统一账本，位于 VPS 本地 SQLite；站内通知与各推送通道共用同一口径。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | 事件 id（UUID hex） |
| user_id | TEXT | 用户 id |
| repo_id | TEXT | 仓库 id（`owner/repo`） |
| recommendation_id | TEXT | 关联推荐 id（可空） |
| channel | TEXT | `inapp` / `bark` / `telegram` / `email` |
| status | TEXT | `prepared` / `sent` / `failed` / `skipped` |
| dedupe_key | TEXT | 去重键 `user_id:repo_id` |
| event_key | TEXT UNIQUE | 幂等键 `user_id:repo_id:channel:YYYY-MM-DD`（用户本地日） |
| reason | TEXT | 事件原因（`daily_push` / `duplicate_repo` / `daily_limit` 等） |
| created_at / updated_at / sent_at | DATETIME | 创建 / 更新 / 送达时间（UTC） |

索引：`(user_id, repo_id, updated_at)`、`(user_id, updated_at)`、`event_key` 唯一。

约定：

- `prepared` / `sent` 视为占用去重窗口与每日额度；`failed` / `skipped` 不占额度；
- 同一 `event_key` 幂等写入，状态只升不降（`skipped < prepared < failed < sent`）；
- 去重窗口按 `PUSH_DEDUPE_DAYS`（默认 7 天）计算，`PUSH_DEDUPE_CROSS_CHANNEL=true` 时跨通道生效；
- 每日上限按用户本地自然日的去重仓库数计算，避免同一仓库多通道重复计数。

## 6. 一致性约定

- D1 为**主数据**；VPS 本地 SQLite 为算力镜像（允许重建）；
- 表结构变更流程：修改 `edge/migrations/` 新增迁移文件 → 同步 `docs/assets/d1-schema.sql` → 更新本文件；
- 字段命名一律 snake_case；时间统一 UTC 存储、展示时本地化。
