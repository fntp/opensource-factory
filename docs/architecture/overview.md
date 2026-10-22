# 架构总览 · Architecture Overview

> 文档编号：AR-01 ｜ 维护人：fntp ｜ 变更架构时同步更新

## 1. 总体架构

```
                      ┌──────────────────────────────┐
                      │           用户浏览器          │
                      └──────────────┬───────────────┘
                                     │ HTTPS
                 ┌───────────────────▼───────────────────┐
                 │        Cloudflare Pages（admin/）      │
                 │  React 19 · Vite · TanStack Router     │
                 └───────────────────┬───────────────────┘
                                     │ /api/*（cookie 会话）
                 ┌───────────────────▼───────────────────┐
                 │      Cloudflare Workers（edge/）       │
                 │  Hono · TypeScript                     │
                 │  ├── 鉴权（GitHub OAuth · 会话）        │
                 │  ├── 元数据读写（D1）                   │
                 │  ├── 向量检索（Vectorize，M3）          │
                 │  └── 任务调度（→ VPS）                  │
                 └───────┬───────────────────┬───────────┘
                         │ D1 / Vectorize    │ 内部 API
                         │                   │ X-Internal-Token
                 ┌───────▼──────┐   ┌────────▼─────────────────────┐
                 │  Cloudflare  │   │      本地 VPS 算力节点        │
                 │  D1 + Vector │   │      （vps/）                 │
                 │              │   │  FastAPI · Celery · Redis     │
                 └──────────────┘   │  ├── 爬虫（GitHub Trending）  │
                                    │  ├── 清洗 / 摘要（Ollama）    │
                                    │  ├── 向量化（BGE-M3）         │
                                    │  └── 推荐 / 推送              │
                                    └──────────────────────────────┘
```

## 2. 组件职责

| 组件 | 目录 | 职责 | 不该做的事 |
| --- | --- | --- | --- |
| 前端控制台 | `admin/` | 展示、交互、调用 edge API | 不存密钥、不做业务计算 |
| 边缘 API | `edge/` | 鉴权、调度、D1 读写、Vectorize 检索 | 不跑长任务、不跑模型 |
| 算力节点 | `vps/` | 爬虫、清洗、摘要、向量化、推荐、推送 | 不对外暴露（仅内网/内部 token） |
| 数据资产 | `docs/assets/` | Schema、样例数据 | — |

## 3. 关键数据流

### 3.1 登录流（GitHub OAuth）

```
浏览器 → /api/auth/github/login → 302 GitHub authorize
GitHub → /api/auth/github/callback?code → edge 换取 token → 拉取用户 → upsert users → 建会话 → 302 回前端
前端 → /api/auth/me（cookie）→ 返回 AuthUser
```

### 3.2 同步流（资产）

```
admin「同步仓库」→ POST /api/sync（edge）→ POST {VPS}/api/tasks/sync（X-Internal-Token）
→ Celery 拉取 GitHub Starred/自有仓库 → upsert → 摘要（Ollama）→ 写回 D1 → 前端可见
```

### 3.3 热榜流

```
Celery beat 每日 → 抓取 GitHub Trending → 清洗解析 → upsert trending_repositories
→ 摘要/技术栈提取 → （M3）向量化 → 同步 Vectorize
```

### 3.4 推荐流（RAG）

```
用户自然语言查询 → edge → Vectorize 检索（已收藏库 + 热榜库）
→ 结果聚合排序 → 返回（含匹配度与理由）；每日推送任务见 M4
```

### 3.5 站内通知流（M4-02）

```
VPS 每日评估 → recommendations.status = 'pushed'
→ admin 打开通知中心 / 轮询未读数 → edge 惰性物化 notifications（幂等）
→ 用户标记已读 / 全部已读 / 忽略 → 未读数徽标同步刷新
```

通知正文与推荐快照同表存储，前端无需二次请求推荐接口；同一 `(user_id, recommendation_id)` 只生成一条通知。

## 4. 接口边界

### 4.1 admin ↔ edge（JSON over HTTPS，Cookie 会话）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/auth/github/login` | GET | 302 → GitHub 授权（`redirect` 参数回跳） |
| `/api/auth/github/callback` | GET | OAuth 回调（code → 会话） |
| `/api/auth/me` | GET | 当前用户（未登录 401） |
| `/api/auth/logout` | POST | 退出（204） |
| `/api/repos` | GET | 仓库列表（`?q=` / `?categoryId=`） |
| `/api/trending` | GET | 热榜（`?limit=`） |
| `/api/recommendations` | GET | 推荐列表 |
| `/api/categories` | GET | 分类 + 标签 |
| `/api/dashboard/stats` | GET | 仪表盘统计 |
| `/api/notifications` | GET | 通知列表（`?status=` / `?limit=` / `?offset=`，需登录） |
| `/api/notifications/unread-count` | GET | 未读数（侧边栏徽标轮询） |
| `/api/notifications/:id/read` | POST | 单条标记已读（幂等） |
| `/api/notifications/read-all` | POST | 全部标记已读 |
| `/api/notifications/:id/dismiss` | POST | 忽略通知（同步推荐状态） |
| `/api/sync` | POST | 触发同步任务（202） |

### 4.2 edge ↔ vps（内部 API，`X-Internal-Token`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/tasks/sync` | POST | 入队仓库同步 |
| `/api/tasks/crawl-trending` | POST | 入队热榜抓取 |
| `/api/tasks/generate-recommendations` | POST | 入队推荐生成 |
| `/api/tasks/daily-push` | POST | 入队每日推送 |
| `/api/internal/notifications` | POST | 批量写入站内通知（`X-Internal-Token`，单批 ≤100） |
| `/api/internal/notifications/sync-recommendations` | POST | 物化指定用户的 `pushed` 推荐为通知 |
| `/api/tasks/{taskId}` | GET | 任务状态 |
| `/healthz` | GET | 健康检查 |

## 5. 安全边界

- 浏览器侧仅持有 httpOnly 会话 Cookie（`of_session`），**不接触任何第三方 token**；
- GitHub access token 仅存在于 edge（换取用户信息后即弃）与 vps（同步任务使用，存服务端）；
- edge → vps 调用必须带 `X-Internal-Token`；vps 不直接对公网暴露业务接口；
- 所有密钥通过平台 secrets 注入，仓库内只有 `.env.example` 占位符。

## 6. 部署拓扑

| 组件 | 部署位置 | 说明 |
| --- | --- | --- |
| admin | Cloudflare Pages | `npm run build` 产物（`admin/dist`），SPA 回退 `_redirects` |
| edge | Cloudflare Workers | `wrangler deploy`；绑定 D1 / Vectorize |
| vps | 本地服务器 | uvicorn + celery worker + celery beat + redis + ollama |
| 数据 | D1 + VPS 本地 SQLite | D1 为主数据；VPS 侧为算力缓存/镜像 |
