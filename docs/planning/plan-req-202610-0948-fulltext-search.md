# 实施计划 · REQ-202610-0948 全文检索（README 全文索引，FTS）

> 需求：REQ-202610-0948（backlog M6-01）｜ 分支：`feat/req-202610-0948-fulltext-search`
> 依赖：M1-12（检索索引与查询计划）｜ 备注：本地镜像先行

## 1. 现状与缺口

- 现有 `vps/app/services/readme.py` 只负责 README 清洗与技术栈提取，清洗结果用于摘要 / 向量化后即丢弃；
- `my_repositories` / `trending_repositories` 只保存 `readme_summary`，没有 README 全文镜像；
- 语义搜索（M3-04）依赖向量，无法对 README 原文做精确关键词 / 短语检索；
- M1-12 的检索索引只存在于独立需求分支，当前集成分支缺少本地 SQLite 检索索引；
- 需求要求「本地镜像先行」：先在 VPS 本地 SQLite 建立 README 全文镜像与 FTS 索引，再向 edge / admin 暴露检索能力。

## 2. 方案总览

```
README 抓取（同步 / 摘要 / 独立补索引任务）
  → clean_readme 清洗
  → repo_readmes（VPS SQLite 全文镜像，source + repo_id 联合主键）
  → SQLite 触发器同步 repo_readme_fts（FTS5 trigram）
       ↓
POST /api/search/fulltext（VPS，X-Internal-Token）
  → bm25 排序 + snippet 摘要 + 水合仓库元信息
       ↓
POST /api/search/fulltext（edge，登录态）
  → 调 VPS → 按 D1 user_id 过滤 my 结果 → 返回 fts 结果
  → VPS 不可用 / 无命中时回退现有 D1 关键词检索
       ↓
admin 搜索页新增「全文检索 / 语义检索」切换，展示 README 命中片段
```

设计要点：

- **FTS5 + trigram**：trigram 分词对中英文子串检索都友好；1~2 字符查询无法命中 trigram，
  自动回退 `LIKE`，保证短词可用；
- **触发器同步**：`repo_readmes` 的 INSERT / UPDATE / DELETE 由 SQLite 触发器同步到 FTS 表，
  避免应用层漏写导致索引漂移；`rebuild` 接口用于灾备重建；
- **不新增外部依赖**：仅使用 SQLite 内置 FTS5；非 SQLite 环境自动降级为 LIKE；
- **本地镜像先行**：D1 不新增全文表；edge 只做鉴权 / 用户过滤与代理，全文数据留在 VPS；
- **复用 README 抓取**：摘要管线抓到 README 时顺带落镜像，避免重复请求 GitHub；
  另提供独立 `sync_readmes` 任务为历史数据补索引。

## 3. 数据模型（VPS SQLite）

### 3.1 `repo_readmes`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| source | TEXT PK | `my` / `trending` |
| repo_id | TEXT PK | `owner/repo` |
| content | TEXT | 清洗后的 README 全文（上限 `FTS_MAX_README_CHARS`） |
| content_hash | TEXT | SHA-256，用于增量判断 |
| char_count | INTEGER | 字符数 |
| fetched_at | DATETIME | 首次抓取时间 |
| updated_at | DATETIME | 最近更新时间 |

### 3.2 `repo_readme_fts`（FTS5 虚表）

```sql
CREATE VIRTUAL TABLE repo_readme_fts USING fts5(
  source UNINDEXED,
  repo_id UNINDEXED,
  content,
  tokenize='trigram'
);
```

`repo_readmes` 的增删改由 `repo_readmes_ai/ad/au` 触发器同步到 FTS 表。

## 4. 接口

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/api/search/fulltext` | POST | `X-Internal-Token` | 全文检索：query / scope / topK / offset |
| `/api/search/fulltext/status` | GET | `X-Internal-Token` | 索引覆盖率、来源分布、最近更新时间 |
| `/api/search/fulltext/rebuild` | POST | `X-Internal-Token` | 全量重建 FTS 索引 |
| `/api/tasks/sync-readmes` | POST | `X-Internal-Token` | 入队 README 镜像补索引任务 |
| edge `/api/search/fulltext` | POST | 登录态 | 代理 VPS 全文检索并按用户过滤 |

## 5. 配置

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `FTS_ENABLED` | `true` | 全文检索开关 |
| `FTS_DEFAULT_TOP_K` | `10` | 默认返回条数 |
| `FTS_MAX_TOP_K` | `50` | 最大返回条数 |
| `FTS_SNIPPET_TOKENS` | `32` | 命中片段 token 数 |
| `FTS_MAX_README_CHARS` | `50000` | 单篇 README 入库上限 |
| `FTS_SYNC_BATCH_SIZE` | `10` | 补索引任务每批提交条数 |
| `FTS_SYNC_MAX_PER_RUN` | `200` | 单次补索引上限 |
| `FTS_AUTO_INDEX` | `true` | 摘要 / 同步后自动落镜像 |
| `FTS_SYNC_HOUR` / `FTS_SYNC_MINUTE` | `4` / `47` | 每日补索引时刻（Asia/Shanghai） |

## 6. 测试与验收

| 层 | 用例 |
| --- | --- |
| vps 服务 | FTS 建表、触发器同步、中文 / 英文检索、2 字短词 LIKE 回退、scope 过滤、排序与 snippet、索引重建、状态统计 |
| vps 任务 | `sync_readmes` 抓取 / 跳过 / 强制刷新 / 失败降级；摘要管线落镜像 |
| vps API | `/api/search/fulltext` 契约、参数校验、内部令牌鉴权、状态 / 重建接口 |
| edge | 全文路由参数归一化、VPS 不可用回退、用户过滤 |
| admin | 模式标签、全文 / 语义切换、命中片段展示 |
| 一致性 | `REQUIRED_ENV_KEYS` / 两份 env 模板 / 文档同步；`test_deploy_assets` 全绿 |

验收标准：

1. README 入库后可通过中文 / 英文关键词检索到对应仓库，返回片段包含命中词；
2. `my` / `trending` / `all` scope 过滤正确；
3. 1~2 字短词自动回退 LIKE，不返回 500；
4. 索引状态可观测，支持全量重建；
5. VPS / edge / admin 检查全绿。

## 7. 风险与后续

- **中文短词**：trigram 要求 ≥3 字符，1~2 字查询走 LIKE，数据量大时较慢；M6-10 可增加搜索建议与热词；
- **磁盘占用**：FTS 表会复制一份 README 文本，按 5 万字符上限与现有仓库规模估算在百 MB 级，纳入 15G 预算；
- **单用户镜像**：VPS `my_repositories` 暂无 `user_id`，用户隔离由 edge 的 D1 过滤承担；
- **索引漂移**：触发器覆盖常规写入；批量导入 / 手工改库后调用 rebuild；
- **M1-12**：本需求补齐本地 SQLite 检索索引（stars / category+stars），edge D1 复合索引随 M1-12 分支后续合并。

## 8. 实施记录（2026-10-22）

- VPS：新增 `app/services/fulltext.py`、`RepoReadme` 模型与 `repo_readmes` / `repo_readme_fts` 触发器；
  `db.init_db()` 幂等建 FTS 表并补 `idx_my_repositories_stars` / `idx_my_repositories_category_stars`；
- VPS API：`POST /api/search/fulltext`、`GET /api/search/fulltext/status`、
  `POST /api/search/fulltext/rebuild`、`POST /api/tasks/sync-readmes`；
- 任务：摘要管线顺带落 README 镜像；新增 `sync_readmes` Celery 任务与每日 04:47 beat；
- edge：新增 `POST /api/search/fulltext` 代理，按 D1 `user_id` 过滤 `my` 结果，VPS 不可用时回退关键词；
- admin：搜索页新增「语义检索 / 全文检索」切换与 README 命中片段展示；
- 检查：`vps` 256 用例、`edge` typecheck、`admin` lint / build / 92 用例全绿。
