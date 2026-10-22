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
| repo_id TEXT | 稳定仓库 id（`owner/name`，M3-07 起） |
| owner / name / description / language / stars / url | 推荐项目快照 |
| score REAL | 综合得分 0~1（相似度 × 0.8 + 热榜热度 × 0.2） |
| reason TEXT | 推荐理由（中文） |
| based_on TEXT | 依据（JSON 数组，如 `["AI/LLM","Python"]`） |
| status TEXT | `new` / `saved` / `dismissed` / `pushed` / `expired`（VPS 每日任务未入选或已收藏） |
| created_at / updated_at | 生成 / 状态更新时间 |

### 3.5 `recommendation_feedback` 推荐反馈（M3-07）

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

## 4. 索引策略

| 表 | 索引 | 用途 |
| --- | --- | --- |
| my_repositories | `(user_id)`、`(category_id)`、`(platform)` | 列表与筛选 |
| trending_repositories | `(stars_today DESC)`、`(crawled_at)` | 榜单查询 |
| sessions | `(user_id)`、`(expires_at)` | 会话校验与清理 |
| repo_tags | `(repo_id)`、`(tag_id)` | 反查 |
| recommendations | `(user_id, score DESC)` | 推荐列表 |
| recommendation_feedback | `(user_id, recommendation_id, action)` UNIQUE、`(user_id, created_at)`、`(user_id, repo_id)` | 反馈幂等 / 回流查询 |

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

## 6. 一致性约定

- D1 为**主数据**；VPS 本地 SQLite 为算力镜像（允许重建）；
- 表结构变更流程：修改 `edge/migrations/` 新增迁移文件 → 同步 `docs/assets/d1-schema.sql` → 更新本文件；
- 字段命名一律 snake_case；时间统一 UTC 存储、展示时本地化。
