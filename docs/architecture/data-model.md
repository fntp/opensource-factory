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

worker_metrics               （D1：Workers 请求指标，按日 / 路由 / 方法 / 状态类聚合）
monitoring_alerts            （VPS：资源红线与健康检查告警）
monitoring_check_runs        （VPS：监控检查历史快照）
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

### 3.5 `notifications` 站内通知

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

### 3.8 `monitoring_alerts` / `monitoring_check_runs` 监控告警（VPS 本地表，M5-03）

> 仅存在于 VPS 本地镜像库，不进入 D1；由 Celery beat 每 5 分钟执行一次检查。

`monitoring_alerts`（告警记录）：

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 告警 id（UUID hex） |
| kind | `memory` / `disk` / `logs` / `health`（资源红线或健康检查失败） |
| severity | `warning` / `critical` |
| message / details | 中文摘要 / JSON 明细（当前值、阈值、检查项） |
| dedupe_key TEXT | 去重键（如 `memory:critical`、`health:redis`） |
| status | `open` / `acknowledged` / `resolved` |
| occurrences | 累计出现次数（冷却窗口内累加） |
| first_seen_at / last_seen_at | 首次 / 最近出现时间 |
| acknowledged_at / resolved_at | 确认 / 恢复时间（可空） |

同一 `dedupe_key` 只保留一条未关闭告警；`ALERT_COOLDOWN_MINUTES` 窗口内重复出现累加
`occurrences`，超出窗口重置为 1；条件消失时自动置 `resolved`。

`monitoring_check_runs`（检查历史）：

| 字段 | 说明 |
| --- | --- |
| id TEXT PK | 运行 id |
| status | `ok` / `warning` / `critical` |
| checks | JSON 数组：各项健康检查结果（数据库 / 运行目录 / Redis / edge / 模型预算） |
| resources | JSON 对象：内存、磁盘、负载、日志快照 |
| findings | JSON 数组：本次命中的阈值告警 |
| created_at | 检查时间 |

历史默认保留 `MONITOR_HISTORY_RETENTION_DAYS`（7）天，由每日清理任务删除。

### 3.9 `worker_metrics` Workers 请求指标（D1，迁移 `0012`）

> D1 表，edge 请求中间件按「日期 + 路由 + 方法 + 状态类」UPSERT，用于 Workers Analytics。

| 字段 | 说明 |
| --- | --- |
| metric_date TEXT | UTC 日期 `YYYY-MM-DD`（联合主键） |
| route TEXT | 归一化路由（数字 / UUID / 长 hex 折叠，最多 5 段；联合主键） |
| method TEXT | HTTP 方法（联合主键） |
| status_class TEXT | `2xx` / `3xx` / `4xx` / `5xx`（联合主键） |
| requests INTEGER | 请求数 |
| total_ms INTEGER | 累计耗时（毫秒） |
| max_ms INTEGER | 单次最大耗时 |
| updated_at TEXT | 更新时间 |

跳过 `OPTIONS` / `HEAD` 与 `/api/internal/*`；索引 `idx_worker_metrics_date (metric_date)` 供按日查询。

## 4. 索引策略

| 表 | 索引 | 用途 |
| --- | --- | --- |
| my_repositories | `(user_id)`、`(category_id)`、`(platform)` | 列表与筛选 |
| trending_repositories | `(stars_today DESC)`、`(crawled_at)` | 榜单查询 |
| trending_snapshots | `(snapshot_date, rank)`、`(snapshot_date, language)` | 按日榜单、日期/语言筛选 |
| sessions | `(user_id)`、`(expires_at)` | 会话校验与清理 |
| repo_tags | `(repo_id)`、`(tag_id)` | 反查 |
| summary_quality_samples | `(batch_id)`、唯一 `(batch_id, repo_source, repo_id)` | 抽检批次查询与去重 |
| recommendations | `(user_id, score DESC)` | 推荐列表 |
| crawl_alerts | `(dedupe_key)`、`(status)` | 告警去重与未确认列表 |
| recommendation_feedback | `(user_id, recommendation_id, action)` UNIQUE、`(user_id, created_at)`、`(user_id, repo_id)` | 反馈幂等 / 回流查询 |
| notifications | `(user_id, status, created_at DESC)` | 通知列表与未读数 |
| notifications | `(user_id, recommendation_id)` UNIQUE、`(user_id, dedupe_key)` UNIQUE | 物化幂等 / 去重 |
| monitoring_alerts | `(dedupe_key)`、`(status)` | 告警去重 / 未关闭列表 |
| worker_metrics | `(metric_date)`、主键 `(metric_date, route, method, status_class)` | Workers 指标按日聚合与 UPSERT |

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
