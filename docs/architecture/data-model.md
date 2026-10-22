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
| score REAL | 匹配度 0~1 |
| reason TEXT | 推荐理由（中文） |
| based_on TEXT | 依据（JSON 数组，如 `["AI/LLM","Python"]`） |
| status TEXT | `new` / `qualified` / `filtered` / `pushed` / `saved` / `dismissed` / `expired` |
| created_at | 生成时间 |

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

## 4. 索引策略

| 表 | 索引 | 用途 |
| --- | --- | --- |
| my_repositories | `(user_id)`、`(category_id)`、`(platform)` | 列表与筛选 |
| trending_repositories | `(stars_today DESC)`、`(crawled_at)` | 榜单查询 |
| sessions | `(user_id)`、`(expires_at)` | 会话校验与清理 |
| repo_tags | `(repo_id)`、`(tag_id)` | 反查 |
| recommendations | `(user_id, score DESC)` | 推荐列表 |
| notifications | `(user_id, status, created_at DESC)` | 通知列表与未读数 |
| notifications | `(user_id, recommendation_id)` UNIQUE、`(user_id, dedupe_key)` UNIQUE | 物化幂等 / 去重 |

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
