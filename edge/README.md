# OpenFactory Edge API

「开源项目工厂 / OpenFactory」的边缘 API 层，运行在 **Cloudflare Workers** 上，为管理后台（admin 前端）提供：GitHub OAuth 登录、用户会话、以及仓库 / 趋势 / 推荐 / 分类 / 仪表盘等只读接口。

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

## 目录结构

```
edge/
├── package.json          # 依赖与脚本（dev / deploy / typecheck / db:migrate:local）
├── tsconfig.json         # strict TypeScript 配置（@cloudflare/workers-types）
├── wrangler.toml         # Worker 名称、D1 绑定、vars（机密不在此处）
├── migrations/
│   ├── 0001_init.sql     # 初始 D1 schema（表 + 索引）
│   ├── 0002_trending_snapshots.sql  # 热榜按日快照（M2-05）
│   ├── 0007_trending_summary.sql  # 热榜摘要列（M2-04）
│   └── 0008_trending_detail.sql  # 热榜详情：readme_summary + 平台/Star 索引
└── src/
    ├── index.ts          # Hono 入口：CORS、日志、/healthz、路由挂载、404/500
    ├── types.ts          # Env 绑定 + 数据库行 + API 响应实体
    ├── db.ts             # D1 查询辅助（first / all / run / count）
    ├── auth.ts           # 会话与 GitHub OAuth 辅助、cookie、redirect 校验
    └── routes/
        ├── auth.ts       # /api/auth/*（login / callback / me / logout）
        ├── repos.ts      # /api/repos
        ├── trending.ts   # /api/trending（按日快照 / 日期 / 历史）
        ├── internal-trending.ts # /api/internal/trending/*（VPS 快照回写 / 保留清理）
        ├── recommend.ts  # /api/recommendations
        ├── categories.ts # /api/categories
        ├── dashboard.ts  # /api/dashboard/stats
        └── sync.ts       # /api/sync
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

## 部署步骤

1. 创建 D1 数据库并记下 `database_id`：

   ```bash
   npx wrangler d1 create opensource-factory
   ```

2. 将 `wrangler.toml` 中 `database_id = "REPLACE_WITH_D1_DATABASE_ID"` 替换为真实 id。
3. 应用远端迁移：

   ```bash
   npx wrangler d1 migrations apply opensource-factory --remote
   ```

4. 设置机密（不要写进 wrangler.toml / 代码 / 提交）：

   ```bash
   npx wrangler secret put GITHUB_CLIENT_SECRET   # GitHub OAuth App 的 Client Secret
   npx wrangler secret put SESSION_SECRET         # 会话/签名用随机串
   npx wrangler secret put INTERNAL_TOKEN         # 可选：边缘 → VPS 节点内部令牌
   ```

5. 配置 `wrangler.toml` 的 `[vars]`：`ALLOWED_ORIGIN`（前端地址）、`GITHUB_CLIENT_ID`、`VPS_NODE_URL`。
6. 部署：

   ```bash
   npm run deploy
   ```

## 环境变量与 secrets

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `DB` | D1 绑定 | 主数据库，绑定名 `DB` |
| `ALLOWED_ORIGIN` | vars | 允许的前端 origin，CORS 精确回显（带 `Access-Control-Allow-Credentials: true`） |
| `GITHUB_CLIENT_ID` | vars | GitHub OAuth App Client ID；留空时 `/api/auth/github/login` 返回 501 |
| `VPS_NODE_URL` | vars | VPS 节点地址；留空时 `/api/sync` 返回 202 accepted 而不转发 |
| `GITHUB_CLIENT_SECRET` | **secret** | `wrangler secret put GITHUB_CLIENT_SECRET` |
| `SESSION_SECRET` | **secret** | `wrangler secret put SESSION_SECRET` |
| `INTERNAL_TOKEN` | secret（可选） | 边缘 ↔ VPS 内部调用令牌（边缘 → VPS 调度、VPS → 边缘摘要回写共用） |

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
| `GET /api/repos?q=&categoryId=` | `RepoItem[]`（会话用户自己的仓库；`q` 模糊匹配名称/描述/摘要，`categoryId` 过滤分类） |
| `POST /api/repos/summaries` | 内部接口：VPS 批量回写 README 摘要，body `{items:[{repoId,summary}]}`，返回 `{total,updated,skipped}` |
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
| `GET /api/categories` | `CategoriesPayload` |
| `GET /api/dashboard/stats` | `DashboardStats` |
| `POST /api/sync` | 202 `{"status":"queued"}`（已配置 VPS）或 `{"status":"accepted","note":"vps node not configured"}` |
| `GET /healthz` | `{"status":"ok"}` |

JSON 形状（前端契约，勿改字段名）：

```ts
RepoItem        { id, fullName, description, summary, language, stars, forks, category, tags: string[], updatedAt, url }
TrendingRepo    { id, owner, name, description, summary, language, stars, starsToday, url,
                  snapshotDate, rank, rankChange, trend,
                  languageRank?, starDelta?, rankDelta?, appearances?, isNew? }
TrendingRepoDetail { ...TrendingRepo, platform, techStack: string[], summary, summarySource, crawledAt, isFavorited }
Recommendation  { id, owner, name, description, language, stars, score, reason, basedOn: string[], url }
CategoriesPayload { categories: [{id, name, count, description}], tags: [{name, count}] }
DashboardStats  { totalRepos, trendingToday, pendingRecommendations, categoryCount }
```

### 与 VPS 节点的约定

`POST /api/sync` 转发到 `${VPS_NODE_URL}/api/tasks/sync`，请求头 `X-Internal-Token: <INTERNAL_TOKEN>`，body 为 `{requestedBy, requestedAt}`；VPS 侧应校验内部令牌并以 2xx 表示已入队。

摘要回写方向相反：VPS 配置 `EDGE_BASE_URL` 后，批量任务调用 `POST {edge}/api/repos/summaries` 或 `POST {edge}/api/trending/summaries`，同样携带 `X-Internal-Token`；边缘侧逐条更新 `my_repositories.readme_summary` / `trending_repositories.readme_summary`，单批最多 500 条。热榜摘要列由 `0007_trending_summary.sql` 迁移添加。

反向（VPS → edge）：热榜任务每日写快照后调用 `POST /api/internal/trending/snapshots`，body 为 `{snapshotDate, items:[{repoId, name, htmlUrl, ...趋势字段}]}`。未配置 `INTERNAL_TOKEN` 时该接口返回 503（默认关闭），令牌不匹配返回 401；单批最多 500 条，按 `(snapshot_date, repo_id)` upsert。

保留清理（M2-08）：VPS 每日归档本地过期快照后调用 `POST /api/internal/trending/retention/cleanup`，body 为 `{beforeDate: "YYYY-MM-DD", dryRun?: boolean}`，删除 `trending_snapshots.snapshot_date < beforeDate` 的行；`dryRun=true` 只返回将删除的行数。D1 只是展示镜像，权威归档在 VPS `TRENDING_ARCHIVE_DIR`。

### 会话与安全

- 会话 token 为 32 字节随机值，D1 中仅存 sha-256 摘要；有效期 30 天。
- cookie：`of_session` / `of_oauth_state`，`HttpOnly; SameSite=Lax`，HTTPS 下附加 `Secure`。
- OAuth `state` 双重校验（cookie + 查询参数比对）防 CSRF。
- 任何密钥仅存于 Worker secrets，绝不进入前端代码或仓库。
