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
│   ├── 0001_init.sql          # 初始 D1 schema（表 + 索引）
│   └── 0003_search_indexes.sql # 检索复合索引（REQ-202610-0904）
├── scripts/
│   └── search-bench.mjs       # 查询计划核对 + P95 基准
└── src/
    ├── index.ts          # Hono 入口：CORS、日志、/healthz、路由挂载、404/500
    ├── types.ts          # Env 绑定 + 数据库行 + API 响应实体
    ├── db.ts             # D1 查询辅助（first / all / run / count）
    ├── auth.ts           # 会话与 GitHub OAuth 辅助、cookie、redirect 校验
    └── routes/
        ├── auth.ts       # /api/auth/*（login / callback / me / logout）
        ├── repos.ts      # /api/repos
        ├── trending.ts   # /api/trending
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

### 检索性能基线（M1-12）

```bash
npm run perf:search   # 20k 行灌入 + EXPLAIN QUERY PLAN 断言 + P95 基准
```

脚本加载 `migrations/` 的真实 SQL，要求四类查询命中复合索引、无临时排序，
且 P95 < 300ms（spec §6）。方法与远端 D1 复测步骤见
[`docs/guides/search-performance.md`](../docs/guides/search-performance.md)。

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
| `INTERNAL_TOKEN` | secret（可选） | 边缘调用 VPS 的 `X-Internal-Token` |

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
| `GET /api/repos?q=&categoryId=&limit=&offset=` | `RepoItem[]`（会话用户自己的仓库；`q` 模糊匹配名称/ID/描述，`categoryId` 过滤分类；`limit` 默认 100、上限 200） |
| `GET /api/trending?limit=20` | `TrendingRepo[]`（公开；按 `stars_today` 降序，limit 上限 100） |
| `GET /api/recommendations` | `Recommendation[]`（用户私有 + 全局，按 `score` 降序；需登录） |
| `GET /api/categories` | `CategoriesPayload` |
| `GET /api/dashboard/stats` | `DashboardStats` |
| `POST /api/sync` | 202 `{"status":"queued"}`（已配置 VPS）或 `{"status":"accepted","note":"vps node not configured"}` |
| `GET /healthz` | `{"status":"ok"}` |

JSON 形状（前端契约，勿改字段名）：

```ts
RepoItem        { id, fullName, description, language, stars, forks, category, tags: string[], updatedAt, url }
TrendingRepo    { id, owner, name, description, language, stars, starsToday, url }
Recommendation  { id, owner, name, description, language, stars, score, reason, basedOn: string[], url }
CategoriesPayload { categories: [{id, name, count, description}], tags: [{name, count}] }
DashboardStats  { totalRepos, trendingToday, pendingRecommendations, categoryCount }
```

### 与 VPS 节点的约定

`POST /api/sync` 转发到 `${VPS_NODE_URL}/api/tasks/sync`，请求头 `X-Internal-Token: <INTERNAL_TOKEN>`，body 为 `{requestedBy, requestedAt}`；VPS 侧应校验内部令牌并以 2xx 表示已入队。

### 会话与安全

- 会话 token 为 32 字节随机值，D1 中仅存 sha-256 摘要；有效期 30 天。
- cookie：`of_session` / `of_oauth_state`，`HttpOnly; SameSite=Lax`，HTTPS 下附加 `Secure`。
- OAuth `state` 双重校验（cookie + 查询参数比对）防 CSRF。
- 任何密钥仅存于 Worker secrets，绝不进入前端代码或仓库。
