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

> 扩展列：`owner`、`language`、`stars`（总 Star）；VPS 本地镜像在 `init_db()` 中对既有 SQLite 库幂等补列。

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
| score REAL | 匹配度 0~1 |
| reason TEXT | 推荐理由（中文） |
| based_on TEXT | 依据（JSON 数组，如 `["AI/LLM","Python"]`） |
| status TEXT | `new` / `saved` / `dismissed` / `pushed` |
| created_at | 生成时间 |

## 4. 索引策略

| 表 | 索引 | 用途 |
| --- | --- | --- |
| my_repositories | `(user_id)`、`(category_id)`、`(platform)` | 列表与筛选 |
| trending_repositories | `(stars_today DESC)`、`(crawled_at)` | 榜单查询 |
| sessions | `(user_id)`、`(expires_at)` | 会话校验与清理 |
| repo_tags | `(repo_id)`、`(tag_id)` | 反查 |
| recommendations | `(user_id, score DESC)` | 推荐列表 |

## 5. 向量数据（Vectorize，M3）

| 项 | 值 |
| --- | --- |
| 模型 | BGE-M3（本地推理） |
| 维度 | 1024 |
| 指标 | cosine |
| 元数据 | `repo_id`、`source`（`my` / `trending`）、`language` |
| 同步方向 | VPS 生成 → edge 写入 Vectorize（批量 upsert） |

## 6. 一致性约定

- D1 为**主数据**；VPS 本地 SQLite 为算力镜像（允许重建）；
- 表结构变更流程：修改 `edge/migrations/` 新增迁移文件 → 同步 `docs/assets/d1-schema.sql` → 更新本文件；
- 字段命名一律 snake_case；时间统一 UTC 存储、展示时本地化。
