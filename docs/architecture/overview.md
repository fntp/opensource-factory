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
→ 摘要/技术栈提取 → 向量化（M3-02）→ 同步 Vectorize（M3-03）
```

### 3.4 推荐流（RAG）

```
用户自然语言查询 → edge → Vectorize 检索（已收藏库 + 热榜库）
→ 结果聚合排序 → 返回（含匹配度与理由）；每日推送任务见 M4
```

### 3.5 向量化流（M3-02）

```
同步 / 抓取完成 → 自动入队 vectorize_repositories（或 POST /api/tasks/vectorize）
→ 按批读取 my_repositories / trending_repositories
→ 文本哈希 + 模型 + 后端判断增量 → EmbeddingService（BGE-M3 / hash 降级）
→ upsert repo_vectors（逐批提交 + 游标）→ 运行状态可查询 / 可断点续跑
→ M3-03 批量同步 Cloudflare Vectorize
```

### 3.6 向量索引同步流（M3-03）

```
Celery beat（每 30 分钟）或 POST /api/vector-index/sync
→ VPS 读取本地 repo_vectors（仅 text_hash 变更 / 上次失败项；force 可全量）
→ 按批 POST {EDGE_BASE_URL}/api/internal/vectors/upsert（X-Internal-Token）
→ edge Worker 通过 Vectorize 绑定批量 upsert
→ VPS 写 vector_sync_state（逐条状态）/ vector_sync_runs（运行统计）

对账（kind=reconcile）：POST /api/internal/vectors/check 比对缺失 / 过期向量并修复；
可选 list + delete 清理孤儿（默认关闭）。
```

### 3.7 语义搜索流（M3-04）

```
admin 搜索页 POST /api/search/semantic（登录态）
→ edge 调 VPS POST /api/search/embed 生成查询向量（X-Internal-Token）
→ edge 通过 Vectorize 绑定做近邻检索（topK 放大后按 source / user 过滤）
→ edge 从 D1 水合（my 仅当前用户；trending 全局）→ 返回匹配度 + 项目元信息

降级链：
Vectorize 未绑定 / 查询失败 / 水合 0 条 → VPS POST /api/search/query（本地 repo_vectors 余弦）
→ VPS 不可达 → edge D1 关键词 LIKE 检索（mode=keyword，页面仍可用）
```

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
| `/api/sync` | POST | 触发同步任务（202） |
| `/api/search/semantic` | POST | 语义搜索（`query` / `topK` / `scope`；vectorize → local → keyword 三级降级） |

### 4.2 edge ↔ vps（内部 API，`X-Internal-Token`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/tasks/sync` | POST | 入队仓库同步 |
| `/api/tasks/crawl-trending` | POST | 入队热榜抓取 |
| `/api/tasks/generate-recommendations` | POST | 入队推荐生成 |
| `/api/tasks/daily-push` | POST | 入队每日推送 |
| `/api/tasks/vectorize` | POST | 入队向量化（批量 / 增量 / 断点续跑） |
| `/api/tasks/{taskId}` | GET | 任务状态 |
| `/api/vector-index/sync` | POST | 入队 Vectorize 同步 / 对账（`kind` / `scope` / `force`） |
| `/api/vector-index/status` | GET | 本地向量覆盖率与同步状态分布 |
| `/api/vector-index/runs` | GET | 最近同步运行记录 |
| `/api/vector-index/runs/{runId}` | GET | 单次运行详情 |
| `/api/vectors/stats` | GET | 向量覆盖率与最近运行 |
| `/api/vectors/runs/{runId}` | GET | 向量化运行详情 |
| `/api/vectors/{source}/{repoId}` | GET | 单条仓库向量 |
| `/api/search/embed` | POST | 查询向量化（供 edge 调用 Vectorize） |
| `/api/search/query` | POST | 本地向量余弦检索（未水合，Vectorize 降级路径） |
| `/api/search/semantic` | POST | 本地检索 + 水合完整项目信息（调试 / CLI） |
| `/api/search/status` | GET | 语义搜索可用性：向量覆盖率与最近运行 |
| `/healthz` | GET | 健康检查 |

### 4.3 vps → edge（Vectorize 内部接口，`X-Internal-Token`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/internal/vectors/upsert` | POST | 批量写入向量（1~1000 条/批） |
| `/api/internal/vectors/check` | POST | 按 ID 批量查询元数据（≤100 条/批） |
| `/api/internal/vectors/delete` | POST | 批量删除向量（≤1000 条/批） |
| `/api/internal/vectors/stats` | GET | 索引统计 |
| `/api/internal/vectors/list` | GET | 分页列出 ID（孤儿对账；不支持时返回 501） |

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
