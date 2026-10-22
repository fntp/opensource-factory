# OpenFactory Edge API

「开源项目工厂 / OpenFactory」的边缘 API 层，运行在 **Cloudflare Workers** 上，为管理后台（admin 前端）提供：GitHub OAuth 登录、用户会话、以及仓库 / 趋势 / 推荐 / 分类 / 仪表盘 / 知识库导出等接口。

## 定位

```
┌────────────┐    credentials: 'include'    ┌──────────────────┐
│ admin 前端  │ ───────────────────────────▶ │  Cloudflare 边缘  │
│ (Pages/SPA)│ ◀─────────────────────────── │  Workers + Hono   │
└────────────┘        JSON API (CORS)       │   D1 (SQLite)     │
                                            └────────┬─────────┘
                                                     │ POST /api/tasks/sync
                                                     │ (X-Internal-Token)
                                                     ▼
                                            ┌──────────────────┐
                                            │  VPS Python 节点  │
                                            │ FastAPI + Celery │
                                            └──────────────────┘
```

- 边缘侧只做 API 与会话；重算力（爬取、Embedding、推荐打分）在 VPS 节点。
- 数据存储：Cloudflare D1（SQLite），schema 见 `migrations/`。
- 所有响应经 `hono/secure-headers` 的 `secureHeaders()` 补充 nosniff / frame / referrer / HSTS 等安全头（M5-08）。

## 目录结构

```
edge/
├── package.json          # 依赖与脚本（dev / deploy / typecheck / test:m2 / db:migrate:local）
├── tsconfig.json         # strict TypeScript 配置（@cloudflare/workers-types）
├── wrangler.toml         # Worker 名称、D1 绑定、vars（机密不在此处）
├── migrations/
│   ├── 0001_init.sql     # 初始 D1 schema（表 + 索引）
│   ├── 0002_trending_snapshots.sql  # 热榜按日快照（M2-05）
│   ├── 0007_trending_summary.sql  # 热榜摘要列（M2-04）
│   ├── 0008_trending_detail.sql  # 热榜详情：平台/Star 查询索引（摘要列见 0007）
│   ├── 0009_recommendation_feedback.sql  # 推荐反馈明细（M3-07）
│   ├── 0010_notifications.sql  # 站内通知表 + 去重/列表索引（M4-02）
│   ├── 0011_push_preferences.sql  # 推送偏好表（M4-06）
│   ├── 0011_security_hardening.sql  # 限流 / 登录尝试 / 安全事件（M5-05）
│   ├── 0012_worker_metrics.sql  # Workers 请求指标按日聚合（M5-03）
│   ├── 0013_duplicate_dismissals.sql  # 重复检测按用户忽略（M6-03）
│   ├── 0014_repo_health.sql  # 仓库健康度字段（M6-05）
│   └── 0015_license_compliance.sql  # License 识别字段（M6-06）
│   └── 0013_tag_suggestions.sql  # 自动打标建议表 + 幂等/列表索引（M7-01）
│   └── 0012_worker_metrics.sql  # Workers 请求指标按日聚合（M5-03）
│   ├── 0009_recommendation_feedback.sql # 推荐反馈明细（M3-07）
│   ├── 0013_duplicate_dismissals.sql    # 重复检测按用户忽略（M6-03）
│   └── 0014_category_suggestions.sql    # 自动分类建议（M7-02）
└── src/
    ├── index.ts          # Hono 入口：CORS、日志、/healthz、路由挂载、404/500
    ├── types.ts          # Env 绑定 + 数据库行 + API 响应实体
    ├── db.ts             # D1 查询辅助（first / all / run / count）
    ├── auth.ts           # 会话与 GitHub OAuth 辅助、cookie、redirect 校验
    ├── search/
    │   └── items.ts      # 搜索结果水合（语义搜索 / 相似推荐共用）
    ├── similar/
    │   └── helpers.ts    # 相似推荐参数归一化 + 关键词兜底打分（纯函数）
    ├── duplicates/
    │   └── helpers.ts    # 重复检测：地址 / 名称归一化、本地聚类、合并建议（纯函数）
    ├── dependencies/
    │   └── helpers.ts    # 依赖分析参数归一化 + D1 语言概览降级（纯函数）
    ├── category-suggestions/
    │   ├── rules.ts      # 业务线词表 + 本地打分兜底（纯函数，与 VPS 词表一致）
    │   └── helpers.ts    # 状态 / 参数归一化、稳定建议 id（纯函数）
    └── routes/
        ├── auth.ts       # /api/auth/*（login / callback / me / logout）
        ├── repos.ts      # /api/repos
        ├── trending.ts   # /api/trending（按日快照 / 日期 / 历史）
        ├── internal-trending.ts # /api/internal/trending/*（VPS 快照回写 / 保留清理）
        ├── recommend.ts  # /api/recommendations
        ├── categories.ts # /api/categories
        ├── tag-suggestions.ts # /api/tag-suggestions（列表 / 生成 / 采纳 / 忽略）
        ├── dashboard.ts  # /api/dashboard/stats
        ├── notifications.ts  # /api/notifications + /api/internal/notifications
        ├── push-preferences.ts # /api/push-preferences + /api/internal/push-preferences
        ├── sync.ts       # /api/sync
        ├── search.ts     # /api/search/semantic（语义三级降级）· /api/search/fulltext（README FTS）
        ├── tech-stack.ts # /api/tech-stack（语言 / 框架聚合 + 关系图，只读 D1）
        ├── export.ts     # /api/export/knowledge（Markdown / JSON / Obsidian 知识库导出）
        ├── monitoring.ts # /api/monitoring/*（总览 / 检查 / 告警确认 + /api/internal/analytics）
        ├── similar.ts    # /api/similar（相似项目：VPS 向量近邻 → D1 关键词兜底）
        ├── duplicates.ts # /api/duplicates/*（重复检测：VPS 规则 + 向量 → 本地兜底；按用户忽略）
        ├── analysis.ts   # /api/analysis/*（依赖分析：用户仓库 → VPS 聚合 → 本地语言概览）
        ├── category-suggestions.ts # /api/category-suggestions/*（生成 / 列表 / 采纳 / 忽略）
        └── internal-vectors.ts # /api/internal/vectors/*（VPS → Vectorize，X-Internal-Token）
```

## 本地开发

```bash
cd edge
npm install
npm run dev            # wrangler dev，默认 http://localhost:8787
curl http://localhost:8787/healthz   # → {"status":"ok"}
```

### D1 迁移（本地）

```bash
npm run db:migrate:local
```

如需在本地插入调试数据：

```bash
npx wrangler d1 execute opensource-factory --local --command "SELECT COUNT(*) FROM categories;"
```

### 检查与验收

```bash
npm run typecheck        # TypeScript 全量类型检查
npm run test:monitoring  # Workers 指标归一化 / 汇总 / 状态合并用例（7 个）
npm run test:trending    # 热榜查询 / 详情纯函数用例（11 个）
npm run test:m2 -- --strict \
  --report-md docs/planning/acceptance-m2-report.md \
  --report-json docs/planning/acceptance-m2-report.json
```

`test:m2` 会自动应用本地 D1 迁移、种入固定热榜数据集并启动 `wrangler dev`，覆盖 M2 列表 / 筛选 / 趋势 / 详情 / 收藏 / 摘要回写 / 快照 upsert / 保留清理 24 项断言。

## 部署步骤

1. 创建 D1 数据库并记下 `database_id`：

   ```bash
   npx wrangler d1 create opensource-factory
   ```

2. 将 `wrangler.toml` 中 `database_id = "REPLACE_WITH_D1_DATABASE_ID"` 替换为真实 id。
3. 创建 Vectorize 索引（维度与 VPS 的 `VECTORIZE_INDEX_DIM` 一致，BGE-M3 为 1024）：

   ```bash
   npx wrangler vectorize create opensource-factory-vectors --dimensions=1024 --metric=cosine
   ```

4. 应用远端迁移：

   ```bash
   npx wrangler d1 migrations apply opensource-factory --remote
   ```

5. 设置机密（不要写进 wrangler.toml / 代码 / 提交）：

   ```bash
   npx wrangler secret put GITHUB_CLIENT_SECRET   # GitHub OAuth App 的 Client Secret
   npx wrangler secret put SESSION_SECRET         # 会话/签名用随机串
   npx wrangler secret put INTERNAL_TOKEN         # 可选：边缘 ↔ VPS 节点内部令牌
   ```

6. 配置 `wrangler.toml` 的 `[vars]`：`ALLOWED_ORIGIN`（前端地址）、`GITHUB_CLIENT_ID`、`VPS_NODE_URL`。
7. 部署：

   ```bash
   npm run deploy
   ```

## 环境变量与 secrets

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `DB` | D1 绑定 | 主数据库，绑定名 `DB` |
| `VECTORIZE` | Vectorize 绑定 | 向量索引，绑定名 `VECTORIZE`；未绑定时内部向量接口返回 503 |
| `VECTORIZE` | Vectorize 绑定 | 向量索引，绑定名 `VECTORIZE`；未配置时内部向量接口返回 503 |
| `ALLOWED_ORIGIN` | vars | 允许的前端 origin，CORS 精确回显（带 `Access-Control-Allow-Credentials: true`） |
| `GITHUB_CLIENT_ID` | vars | GitHub OAuth App Client ID；留空时 `/api/auth/github/login` 返回 501 |
| `VPS_NODE_URL` | vars | VPS 节点地址；留空时 `/api/sync` 返回 202 accepted 而不转发 |
| `GITHUB_CLIENT_SECRET` | **secret** | `wrangler secret put GITHUB_CLIENT_SECRET` |
| `SESSION_SECRET` | **secret** | `wrangler secret put SESSION_SECRET` |
| `INTERNAL_TOKEN` | secret（可选） | 边缘 ↔ VPS 内部调用令牌（边缘 → VPS 调度、VPS → 边缘摘要回写共用） |
| `INTERNAL_TOKEN_PREVIOUS` | secret（可选） | 令牌轮换过渡位：与 `INTERNAL_TOKEN` 同时被接受，验证完成后清空 |
| `RATE_LIMIT_ENABLED` | vars | 默认 `true`；`0` / `false` / `off` / `no` 关闭限流 |
| `RATE_LIMIT_READ_PER_MINUTE` | vars | 读请求每分钟上限（默认 300） |
| `RATE_LIMIT_WRITE_PER_MINUTE` | vars | 写请求每分钟上限（默认 60） |
| `RATE_LIMIT_AUTH_PER_MINUTE` | vars | 认证接口每分钟上限（默认 10） |
| `LOGIN_MAX_FAILURES` | vars | 登录失败阈值（默认 10 次 / 15 分钟） |
| `LOGIN_FAILURE_WINDOW_SECONDS` | vars | 登录失败统计窗口（默认 900 秒） |
| `LOGIN_LOCKOUT_SECONDS` | vars | 登录锁定时长（默认 900 秒） |

## 接口约定

前端 fetch 一律使用 `credentials: 'include'`。所有错误返回 `{"error": "<code>"}` JSON。

### 认证

| 方法/路径 | 说明 |
| --- | --- |
| `GET /api/auth/github/login?redirect=` | 302 → GitHub 授权页；设置 `of_oauth_state` cookie；`redirect` 会被回传并在 callback 校验 |
| `GET /api/auth/github/callback` | 校验 state → 换 token → upsert 用户 → 建会话（`of_session` cookie）→ 跳转 `redirect`（仅允许 `/` 开头或 ALLOWED_ORIGIN 同源，否则回退 ALLOWED_ORIGIN） |
| `GET /api/auth/me` | 200 `AuthUser` 或 401 |
| `POST /api/auth/logout` | 204，清除会话 |

`AuthUser`：`{id, login, name, email, avatarUrl}`

### 数据接口

| 方法/路径 | 返回 |
| --- | --- |
| `GET /api/repos?q=&categoryId=` | `RepoItem[]`（会话用户自己的仓库；`q` 模糊匹配名称/描述/摘要，`categoryId` 过滤分类；每项内嵌 `health`） |
| `POST /api/repos/summaries` | 内部接口：VPS 批量回写 README 摘要，body `{items:[{repoId,summary}]}`，返回 `{total,updated,skipped}` |
| `GET /api/repos/health?status=` | `{summary, items}`（当前用户仓库健康度；`status=active\|attention\|stale\|archived\|unknown` 可选） |
| `POST /api/repos/health` | 内部接口：VPS 批量回写健康度，body `{items:[{repoId,status,score,lastPushAt,openIssues,archived,checkedAt}]}`，返回 `{total,updated,skipped}` |
| `POST /api/repos/health/refresh` | 202 `{status:"queued",taskId}`；转发 VPS 刷新健康度，VPS 未配置时 `{status:"accepted",note}` |
| `GET /api/licenses/catalog` | `{categories, licenses}`（公开的 License 目录与分级口径，M6-06） |
| `GET /api/licenses/summary?scope=my` | `{total, known, unknown, riskCounts, licenses, checked, unchecked}`（当前用户收藏库的 License / 风险分布） |
| `GET /api/tag-suggestions` | 打标建议列表（登录态；`status=pending\|accepted\|dismissed\|all`、`repoId`、`limit`、`offset`；返回 `summary` 汇总） |
| `POST /api/tag-suggestions/generate` | 基于摘要生成建议（登录态；`repoIds?` / `limit?` / `perRepo?`；VPS 优先，本地规则兜底，返回 `source` / `saved`） |
| `POST /api/tag-suggestions/accept` | 采纳建议（`ids` 或 `repoId + tags`；写 `tags` / `repo_tags`，已存在标签不重复计数） |
| `POST /api/tag-suggestions/dismiss` | 忽略建议（`ids`；重复生成不覆盖 dismissed / accepted 状态） |
| `GET /api/trending?date=&language=&limit=20` | `TrendingRepo[]`（公开；优先读按日快照，按 `rank` 升序，默认最近一天，可按日期 / 语言筛选；返回 `rank` / `rankChange` / `trend`，无快照时回退最新状态表，含 `summary`） |
| `GET /api/trending/dates?limit=30` | `[{date, count}]`（可用快照日期，倒序） |
| `GET /api/trending/languages?date=` | `{date, languages: [{language, count}]}`（指定日期的语言分布） |
| `GET /api/trending/history?repoId=&days=30` | `TrendingRepo[]`（单仓库 Star / 排名历史） |
| `GET /api/trending/:owner/:name` | `TrendingRepoDetail`（公开；登录时回显 `isFavorited`；不存在 404） |
| `POST /api/trending/:owner/:name/favorite` | `{favorited:true, created, repoId}`（需登录；幂等，他人同 id 资产返回 409） |
| `DELETE /api/trending/:owner/:name/favorite` | `{favorited:false, removed, repoId}`（需登录） |
| `POST /api/trending/summaries` | 内部接口：VPS 批量回写热榜摘要，body `{items:[{repoId,summary}]}`，返回 `{total,updated,skipped}` |
| `POST /api/internal/trending/snapshots` | 内部：VPS 批量 upsert 快照（`X-Internal-Token`，单批 ≤ 500） |
| `GET /api/internal/trending/retention` | 内部：D1 快照总数与最早 / 最新日期（`X-Internal-Token`） |
| `POST /api/internal/trending/retention/cleanup` | 内部：按 `{beforeDate, dryRun?}` 删除过期快照（`X-Internal-Token`，M2-08） |
| `GET /api/recommendations` | `Recommendation[]`（用户私有 + 全局，按 `score` 降序；需登录） |
| `GET /api/notifications?status=&limit=&offset=` | `NotificationsPayload`（`all`/`unread`/`read`，limit ≤100；需登录；惰性物化 `pushed` 推荐） |
| `GET /api/notifications/unread-count` | `{unread:number}`（侧边栏徽标） |
| `POST /api/notifications/:id/read` | 单条标记已读（幂等；404 = 不存在或已忽略） |
| `POST /api/notifications/read-all` | `{updated,unread:0}` |
| `POST /api/notifications/:id/dismiss` | 忽略通知，并同步关联推荐状态为 `dismissed` |
| `GET /api/push-preferences` | `{preferences,isDefault,availableChannels}`（未保存返回默认值；需登录） |
| `PUT /api/push-preferences` | 保存推送偏好（时间 / 时区 / 阈值 / 通道开关；需登录） |
| `GET /api/internal/push-preferences` | 全部推送偏好（`X-Internal-Token`；`?userId=` 查单个） |
| `GET /api/categories` | `CategoriesPayload` |
| `GET /api/dashboard/stats` | `DashboardStats` |
| `POST /api/sync` | 202 `{"status":"queued"}`（已配置 VPS）或 `{"status":"accepted","note":"vps node not configured"}` |
| `POST /api/search/semantic` | `SearchResponse`：body `{query, topK?, scope?}`；mode 为 `vectorize` / `local` / `keyword`；`my` 结果仅当前用户；响应可带 `understanding`（查询理解结果），关键词兜底用其扩展词做多词 OR LIKE |
| `GET /api/tech-stack` | `TechStackResponse`（需登录）：`{summary, languages, frameworks, graph:{nodes,links}, generatedAt}`；语言 / 框架按当前用户仓库聚合，图谱保留 Top 8 × 16 |
| `GET /api/export/knowledge/summary` | 导出统计（需登录）：`{totalRepos, withSummary, categoryCount, tagCount, totalStars, generatedAt}` |
| `GET /api/export/knowledge?format=&includeSummary=&groupBy=` | 生成知识库附件（需登录）：`format=markdown\|json\|obsidian`，附件名见 `docs/guides/knowledge-export.md` |
| `GET /api/monitoring/overview?days=7` | 监控总览（需登录）：`{status, generatedAt, edge, workers, workersError, vps, vpsError}`；合并 VPS 实时状态与 Workers 每日聚合，VPS 不可用时降级返回 Workers 部分 |
| `POST /api/monitoring/check` | 触发 VPS 一次检查（需登录；VPS 未配置返回 503） |
| `POST /api/monitoring/alerts/:id/ack` | 确认 VPS 告警（需登录） |
| `GET /api/internal/analytics?days=7` | Workers 请求指标聚合（`X-Internal-Token`；`days` 1~30） |
| `POST /api/search/fulltext` | `SearchResponse`：body `{query, topK?, scope?, offset?}`；mode 为 `fts` / `like`（VPS FTS5，短词 LIKE 回退）/ `keyword`（VPS 不可用降级）；`my` 结果按 D1 `user_id` 过滤；条目可带 `snippet` / `matchedTerms`（M6-01） |
| `GET /api/similar` | `SimilarResponse`：query `source=my\|trending` / `repoId` / `topK` / `scope` / `minScore` / `excludeSaved`；mode 为 `local`（VPS 向量近邻）/ `keyword`（D1 同语言 + 技术栈兜底）；`source=my` 需登录且只返回当前用户仓库 |
| `POST /api/duplicates/scan` | `DuplicateScanResponse`：body `{scope, minScore?, maxClusters?}`；mode 为 `vps` / `hybrid` / `local`；返回簇、成员信号、保留项与字段合并建议；需登录，`my` 成员二次校验归属 |
| `POST /api/duplicates/dismiss` | 忽略重复簇，body `{clusterId, repoIds?, reason?}`；按 `user_id + cluster_key` 幂等 |
| `GET /api/duplicates/dismissed` | `{count, items:[{clusterId, repoIds, reason, createdAt}]}`（当前用户） |
| `DELETE /api/duplicates/dismiss/:clusterId` | 取消忽略，返回 `{removed, clusterId}` |
| `GET /api/analysis/dependencies` | 依赖分析：query `top`；按当前用户仓库 id 调 VPS 聚合，mode 为 `vps` / `local`（D1 语言概览降级）；需登录 |
| `POST /api/analysis/dependencies/refresh` | 扫描当前用户仓库依赖清单；VPS 不可达返回 `{status:"unavailable"}`，需登录 |
| `GET /api/category-suggestions` | `{items,summary,categories}`：query `status=pending\|accepted\|dismissed\|all` / `repoId` / `limit` / `offset`；需登录 |
| `POST /api/category-suggestions/generate` | body `{repoIds?, limit?, perRepo?, minScore?}`；返回 `{generatedAt,scanned,suggested,skipped,source}`；VPS 规则引擎失败时 edge 本地兜底 |
| `POST /api/category-suggestions/accept` | body `{ids[]}` 或 `{repoId,categoryName}`；自动建分类并写回 `my_repositories.category_id`，返回 `{accepted,categoriesCreated,items}` |
| `POST /api/category-suggestions/dismiss` | body `{ids[]}`；返回 `{dismissed}`，已忽略建议不会被重复生成覆盖 |
| `GET /healthz` | `{"status":"ok"}` |

JSON 形状（前端契约，勿改字段名）：

```ts
RepoItem        { id, fullName, description, summary, language, stars, forks, category, tags: string[], updatedAt, url,
                  health: RepoHealth, license?: LicenseInfo | null }
RepoHealth      { status, label, score, lastPushAt, daysSincePush, openIssues, archived, reasons: string[], checkedAt }
TrendingRepo    { id, owner, name, description, summary, language, stars, starsToday, url,
                  snapshotDate, rank, rankChange, trend,
                  languageRank?, starDelta?, rankDelta?, appearances?, isNew?, license?: LicenseInfo | null }
TrendingRepoDetail { ...TrendingRepo, platform, techStack: string[], summary, summarySource, crawledAt, isFavorited }
Recommendation  { id, owner, name, description, language, stars, score, reason, basedOn: string[], url }
CategoriesPayload { categories: [{id, name, count, description}], tags: [{name, count}] }
DashboardStats  { totalRepos, trendingToday, pendingRecommendations, categoryCount }
```

### 内部向量接口（VPS → Vectorize）

仅接受携带 `X-Internal-Token` 的内部调用；`INTERNAL_TOKEN` 未配置时一律 503，避免裸奔。单次批量上限：upsert / delete 1000 条、check 100 条；对 Vectorize 瞬时错误自动重试 3 次（约 200ms / 400ms 退避）。

| 方法/路径 | 说明 |
| --- | --- |
| `POST /api/internal/vectors/upsert` | `{items:[{id,values,metadata}]}` → `{total,upserted,skipped,mutationId}`；非法向量跳过，同批维度必须一致 |
| `POST /api/internal/vectors/check` | `{ids:[...]}` → `{total,found,missing}`（`getByIds`） |
| `POST /api/internal/vectors/delete` | `{ids:[...]}` → `{total,deleted,mutationId}`（`deleteByIds`） |
| `GET /api/internal/vectors/stats` | `{vectorCount,dimensions,processedUpToDatetime,processedUpToMutation}`（`describe`） |

### 与 VPS 节点的约定

`POST /api/sync` 转发到 `${VPS_NODE_URL}/api/tasks/sync`，请求头 `X-Internal-Token: <INTERNAL_TOKEN>`，body 为 `{requestedBy, requestedAt}`；VPS 侧应校验内部令牌并以 2xx 表示已入队。

摘要回写方向相反：VPS 配置 `EDGE_BASE_URL` 后，批量任务调用 `POST {edge}/api/repos/summaries` 或 `POST {edge}/api/trending/summaries`，同样携带 `X-Internal-Token`；边缘侧逐条更新 `my_repositories.readme_summary` / `trending_repositories.readme_summary`，单批最多 500 条。热榜摘要列由 `0007_trending_summary.sql` 迁移添加。

反向（VPS → edge）：热榜任务每日写快照后调用 `POST /api/internal/trending/snapshots`，body 为 `{snapshotDate, items:[{repoId, name, htmlUrl, ...趋势字段}]}`。未配置 `INTERNAL_TOKEN` 时该接口返回 503（默认关闭），令牌不匹配返回 401；单批最多 500 条，按 `(snapshot_date, repo_id)` upsert。

保留清理（M2-08）：VPS 每日归档本地过期快照后调用 `POST /api/internal/trending/retention/cleanup`，body 为 `{beforeDate: "YYYY-MM-DD", dryRun?: boolean}`，删除 `trending_snapshots.snapshot_date < beforeDate` 的行；`dryRun=true` 只返回将删除的行数。D1 只是展示镜像，权威归档在 VPS `TRENDING_ARCHIVE_DIR`。
### 内部向量接口（VPS → Vectorize）

仅供 VPS 节点调用，全部要求 `X-Internal-Token`（未配置 `INTERNAL_TOKEN` 时返回 503，令牌不符返回 401）：

| 方法/路径 | 说明 |
| --- | --- |
| `POST /api/internal/vectors/upsert` | body `{vectors: [{id, values, metadata}]}`，1~1000 条/批 |
| `POST /api/internal/vectors/check` | body `{ids: string[]}`，≤100 个；返回 `{vectors: [{id, metadata}]}` |
| `POST /api/internal/vectors/delete` | body `{ids: string[]}`，≤1000 个 |
| `GET /api/internal/vectors/stats` | 索引统计 |
| `GET /api/internal/vectors/list?count=&cursor=` | 分页列出 ID；绑定不支持时返回 501（VPS 对账自动降级） |

### 内部推荐接口（VPS → D1，M3-07）

同样要求 `X-Internal-Token`（未配置 503 / 不匹配 401）：

| 方法/路径 | 说明 |
| --- | --- |
| `POST /api/internal/recommendations/upsert` | body `{userId, items: [...]}`，≤500 条；按 id upsert，`saved` / `dismissed` 状态不被生成任务覆盖 |
| `GET /api/internal/recommendations/feedback?userId=` | 返回 `{savedRepoIds, dismissedRepoIds, clickedRepoIds}`，合并反馈表与推荐状态 |

### Workers 请求指标（M5-03）

`src/index.ts` 在 `/api/*` 上挂载轻量中间件：请求结束后按
`metric_date + route + method + status_class` 对 `worker_metrics` 做 UPSERT，
累计 `requests` / `total_ms` / `max_ms`。路由先经 `normalizeRoute` 归一化
（数字、UUID、长 hex 折叠，最多 5 段），并跳过 `OPTIONS` / `HEAD` 与 `/api/internal/*`，
控制基数、避免自观测放大。指标写入使用 `waitUntil`，不阻塞响应。

### 会话与安全

- 会话 token 为 32 字节随机值，D1 中仅存 sha-256 摘要；有效期 30 天。
- cookie：`of_session` / `of_oauth_state`，`HttpOnly; SameSite=Lax`，HTTPS 下附加 `Secure`。
- OAuth `state` 双重校验（cookie + 查询参数比对）防 CSRF。
- 接口限流：按 auth / write / read 分桶，已登录按用户 id、匿名按 IP 哈希；超限 429 + `Retry-After`，D1 异常 fail-open。
- 登录防护：失败窗口内达到 `LOGIN_MAX_FAILURES` 后按 IP 哈希锁定 `LOGIN_LOCKOUT_SECONDS`，成功登录清零。
- 内部令牌支持双令牌轮换（`INTERNAL_TOKEN` + `INTERNAL_TOKEN_PREVIOUS`），运维接口：`GET /api/internal/security/status`、`POST /api/internal/security/cleanup`。
- 任何密钥仅存于 Worker secrets，绝不进入前端代码或仓库；状态接口只返回 12 位指纹，不回显明文。
