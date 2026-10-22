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

trending_repositories        （最新状态，公共数据）
trending_snapshots           （按日快照 + 趋势字段）
summary_quality_samples      （摘要抽检样本，按批次留存）
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
| readme_summary | TEXT | VPS 大模型生成的项目摘要（`summarize_readmes` 批量任务写入，Ollama → DeepSeek → 截断降级） |
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
| readme_summary | TEXT | VPS 生成的中文摘要（`source=trending` 批量任务写入，Ollama → DeepSeek → 截断降级） |

> 扩展列：`owner`、`language`、`stars`（总 Star）、`readme_summary`（M2-04 中文摘要；为空时详情页回退 `description`）。
> 详情页收藏写入 `my_repositories`，字段映射见 REQ-202610-0915 实施计划；VPS 本地镜像在 `init_db()` 中对既有 SQLite 库幂等补列。

### 2.2.1 `trending_snapshots` 热榜按日快照（REQ-202610-0913 / M2-05）

> 同一仓库同一天只有一行，主键 `(snapshot_date, repo_id)` 保证重复抓取幂等；`trending_repositories` 继续作为「最新状态」表供旧接口兼容。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| snapshot_date | DATE PK | 快照日期（Asia/Shanghai 的任务日） |
| repo_id | TEXT PK | `owner/repo` |
| platform / owner / name / html_url / description / language / tech_stack | — | 项目元信息快照 |
| stars / stars_today | INTEGER | 总 Star / 今日新增 Star |
| rank | INTEGER | 全平台综合排名（按 stars_today、stars 降序，1 起） |
| language_rank | INTEGER | 同语言内排名 |
| star_delta | INTEGER | 对比上一有效快照的总 Star 增量 |
| rank_delta | INTEGER | 对比上一有效快照的排名变化（正数=上升） |
| appearances | INTEGER | 连续上榜天数（断档后重置为 1） |
| is_new | INTEGER | 1 = 首次上榜（回看 7 天内无基线） |
| trend | TEXT | `new` / `up` / `down` / `steady` |
| trending_pages | TEXT | 来源语言页 JSON 数组，用于追溯去重来源 |
| created_at / updated_at | DATETIME | 入库 / 更新时间 |

趋势口径：基线取该仓库在快照日之前最近一条快照（最多回看 7 天）；`rank_delta >= 3` 记为 `up`，`<= -3` 记为 `down`，其余 `steady`。

**保留策略（M2-08）**：默认保留 90 天（`TRENDING_RETENTION_DAYS`），每日 04:17（可配）由 Celery 任务 `cleanup_trending_data` 处理：

1. 把 `snapshot_date < today - retention_days` 的快照写成 `data/archives/trending-snapshots-<起>_<止>.jsonl.gz`（gzip JSONL，首行为格式头）；
2. 归档成功后在同一事务删除本地过期行，并调用 edge 内部接口删除 D1 同日期范围；
3. 归档失败时**不删除**任何行；归档文件按 `TRENDING_ARCHIVE_KEEP_DAYS`（默认 365 天）滚动清理。

> `trending_repositories` 只保留最新状态，不参与按日清理；详细操作见 `docs/guides/trending-retention.md`。

### 2.4 `categories` 分类

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

### 3.4 `summary_quality_samples` 摘要质量抽检样本

VPS 本地 SQLite 表（M2-04），不复制到 D1；用于留存样本、人工复核与质量统计。

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 样本 id（uuid hex） |
| batch_id | 生成批次（Celery task id 或补抽样批次号） |
| repo_id / repo_source | 仓库 id 与来源（`my` / `trending`） |
| summary / source / model | 摘要正文、生成来源（`ollama` / `deepseek` / `truncated`）与模型名 |
| max_chars | 生成时摘要长度上限 |
| score / verdict | 启发式质量分（0~100）与判定（`pass` / `fail`） |
| checks | 逐项检查明细（JSON 数组） |
| status | 人工复核状态：`pending` / `passed` / `failed` |
| reviewer / review_note / reviewed_at | 复核人与备注 |
| created_at | 留存时间 |

唯一约束：`(batch_id, repo_source, repo_id)`；同批次重跑时更新原样本，摘要变化则复核状态重置为 `pending`。

### 3.5 `recommendations` 推荐

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 推荐 id |
| user_id | 目标用户（NULL = 全局） |
| repo_id TEXT | 稳定仓库 id（`owner/name`，M3-07 起） |
| owner / name / description / language / stars / url | 推荐项目快照 |
| score REAL | 综合得分 0~1（相似度 × 0.8 + 热榜热度 × 0.2） |
| match_score REAL | 原始余弦相似度（M4-01 匹配度硬门槛；历史数据缺失时回退到 `score`） |
| quality_score REAL | 每日评估质量分 0~1（仓库质量 × 0.7 + 理由质量 × 0.3） |
| quality_detail TEXT | 评估明细 JSON（各分量、阈值、是否通过） |
| evaluation_run_id TEXT | 最近一次评估运行 id |
| evaluated_at DATETIME | 最近评估时间 |
| bark_sent_at DATETIME | Bark 投递成功时间（M4-03；NULL = 待投递 / 投递失败） |
| bark_error TEXT | 最近一次 Bark 投递失败原因（截断 300 字符，成功后清空） |
| reason TEXT | 推荐理由（中文） |
| based_on TEXT | 依据（JSON 数组，如 `["AI/LLM","Python"]`） |
| status TEXT | `new` / `qualified` / `filtered` / `pushed` / `saved` / `dismissed` / `expired` |
| created_at / updated_at | 生成 / 状态更新时间 |

### 3.6 `recommendation_feedback` 推荐反馈（M3-07）

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 反馈 id |
| user_id | 反馈用户 |
| recommendation_id | 关联推荐 id |
| repo_id TEXT | 稳定仓库 id（`owner/name`） |
| action TEXT | `saved` / `dismissed` / `clicked` |
| reason TEXT | 忽略原因（仅 dismissed，≤200 字） |
| created_at | 反馈时间 |

唯一索引 `(user_id, recommendation_id, action)` 保证重复点击幂等；另按
`(user_id, created_at)`、`(user_id, repo_id)` 建索引，供 VPS 拉取反馈与排除候选。

> 本地 VPS 镜像同样保留 `reason` / `based_on`：`based_on` 为 JSON 数组字符串
> （如 `["相似度 87%","语言 Python","技术栈 FastAPI"]`），旧 SQLite 库由 `init_db()` 幂等补列；
> 生成逻辑见 `vps/app/services/recommend_reason.py`（纯规则，不调用 LLM）。

### 3.7 `crawl_alerts` / `crawl_page_stats` 抓取告警（VPS 本地表）

> 仅存在于 VPS 本地镜像库，不进入 D1；用于热榜抓取的容错基线与值班告警。

`crawl_page_stats`（按「平台 + 页面」记录上次成功条数）：

| 字段 | 说明 |
| --- | --- |
| page_key TEXT PK | `平台:页面`，如 `github:python` |
| platform / page | `github` / `gitee`；`all` 或语言 slug |
| last_count | 上次成功解析条数（结构变更判定基线） |
| last_status_code / last_rows / last_parsed | 最近一次抓取的 HTTP 状态与解析诊断 |
| last_ok_at / last_error | 上次成功时间 / 最近错误 |
| updated_at | 更新时间 |

`crawl_alerts`（告警记录）：

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 告警 id |
| platform / page | 来源平台与页面 |
| kind | `fetch_failed` / `structure_change` / `count_drop` / `all_failed` |
| severity | `warning` / `error` |
| message / details | 中文摘要 / JSON 诊断明细 |
| dedupe_key | `平台:页面:类型`，冷却窗口内合并 |
| status | `open` / `acknowledged` |
| occurrences | 累计出现次数 |
| first_seen_at / last_seen_at / acknowledged_at | 首次 / 最近 / 确认时间 |

### 3.8 `notifications` 站内通知（M4-02）

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

### 3.9 `recommendation_evaluation_runs` 评估运行（M4-01）

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 运行 id |
| user_id | 目标用户（NULL = 全量评估） |
| status TEXT | `running` / `completed` / `failed` |
| match_threshold / quality_threshold REAL | 本次运行使用的门槛 |
| total / qualified / filtered / skipped / failed INTEGER | 运行计数 |
| error TEXT | 失败原因（截断） |
| created_at / finished_at | 开始 / 结束时间 |

### 3.10 `telegram_deliveries` Telegram 送达记录（M4-04，VPS 本地）

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 送达记录 id |
| chat_id TEXT | 目标会话（接口输出时脱敏） |
| kind TEXT | `digest` / `test` |
| status TEXT | `pending` / `sent` / `failed` |
| item_count INTEGER | 摘要包含的推荐数 |
| message_count INTEGER | 实际发送的消息条数 |
| message_id TEXT | 第一条消息的 Telegram `message_id` |
| dedupe_key TEXT | 幂等键（`telegram:digest:<date>:<user>:<chat>`） |
| error TEXT | 失败原因（截断、已脱敏） |
| created_at / finished_at | 开始 / 结束时间 |

> 本表为 M4-04 的通道级记录；M4-08「推送记录与回执」落地后可扩展为全通道统一表。

### 3.11 `email_deliveries` Email 送达记录（M4-05）

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 送达记录 id（UUID hex） |
| recipient TEXT | 收件人（多个逗号分隔；接口输出时脱敏） |
| kind TEXT | `digest`（每日摘要）/ `test`（连通性测试） |
| status TEXT | `sent` / `failed` |
| item_count INTEGER | 摘要包含的推荐条数（测试邮件为 0） |
| subject TEXT | 邮件主题 |
| message_id TEXT | SMTP Message-ID |
| dedupe_key TEXT | 幂等键：`email:digest:<日期>:<排序后的收件人>` |
| error TEXT | 失败原因（已替换密码 / 用户名，截断 300 字符） |
| created_at / finished_at | 创建 / 完成时间 |

### 3.12 `push_preferences` 推送偏好（M4-06）

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
| trending_snapshots | `(snapshot_date, rank)`、`(snapshot_date, language)` | 按日榜单、日期/语言筛选 |
| sessions | `(user_id)`、`(expires_at)` | 会话校验与清理 |
| repo_tags | `(repo_id)`、`(tag_id)` | 反查 |
| summary_quality_samples | `(batch_id)`、唯一 `(batch_id, repo_source, repo_id)` | 抽检批次查询与去重 |
| recommendations | `(user_id, score DESC)`、`(evaluation_run_id)` | 推荐列表 / 评估批次查询 |
| crawl_alerts | `(dedupe_key)`、`(status)` | 告警去重与未确认列表 |
| recommendation_feedback | `(user_id, recommendation_id, action)` UNIQUE、`(user_id, created_at)`、`(user_id, repo_id)` | 反馈幂等 / 回流查询 |
| notifications | `(user_id, status, created_at DESC)` | 通知列表与未读数 |
| notifications | `(user_id, recommendation_id)` UNIQUE、`(user_id, dedupe_key)` UNIQUE | 物化幂等 / 去重 |
| telegram_deliveries | `(dedupe_key, status)`、`(dedupe_key)` | 当日幂等与送达记录查询 |
| email_deliveries | `(dedupe_key, status)` | 每日摘要幂等校验 / 送达排查 |

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
| 模型 | BGE-M3（本地推理；M3-01 选型 int8 量化） |
| 维度 | 1024（`VECTORIZE_INDEX_DIM` 可配，0 表示不校验） |
| 指标 | cosine |
| 向量 ID | `v1_` + `sha256("{source}:{repo_id}")[:32]`，固定 35 字符、跨运行稳定 |
| 元数据 | `repo_id`、`source`（`my` / `trending`）、`text_hash`、`model`、`dim`、`language` |
| 同步方向 | VPS `repo_vectors` → edge 内部接口 → Vectorize（批量 upsert / 重试 / 对账） |

同步状态保存在 VPS 本地库（不镜像到 D1）：

| 表 | 关键字段 | 用途 |
| --- | --- | --- |
| `vector_index_state` | `(source, repo_id)` 主键、`vector_id`、`text_hash`、`model`、`backend`、`dim`、`status`、`attempts`、`last_error`、`synced_at`、`checked_at` | 增量判断与失败重试依据 |
| `vector_index_runs` | `id`、`mode`、`scope`、`status`、`total/processed/upserted/deleted/skipped/failed/dim_skipped/checked/missing/stale/repaired`、`batches`、`cursor_source`、`cursor_repo_id`、`error` | 每次同步 / 对账的可观测记录与断点续跑游标 |

增量判定：`text_hash + model + backend + dim` 任一变化或上次状态非 `synced` 时重新 upsert；`full` 模式忽略状态全量重传。

## 6. 一致性约定

- D1 为**主数据**；VPS 本地 SQLite 为算力镜像（允许重建）；
- 表结构变更流程：修改 `edge/migrations/` 新增迁移文件 → 同步 `docs/assets/d1-schema.sql` → 更新本文件；
- 字段命名一律 snake_case；时间统一 UTC 存储、展示时本地化。
