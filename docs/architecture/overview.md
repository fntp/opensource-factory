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
→ Celery 拉取 GitHub Starred/自有仓库 → upsert
→ 入队 summarize_readmes（批量队列）→ 抓 README / 清洗
→ Ollama → DeepSeek → 截断原文（降级链）
→ 分批写本地镜像 + 质量评分 / 抽检样本留存
→ POST {edge}/api/repos/summaries 回写 D1 → 前端可见
```

### 3.3 热榜流

```
Celery beat 每日 → 抓取 GitHub Trending（全局页 + 多语言页，超时/429/5xx 指数退避重试）
→ 清洗解析 / 去重 → 页面健康判定（结构变更 / 条数骤降）→ 告警落库（可选 webhook）
→ upsert trending_repositories（最新状态）→ README 去噪（徽章 / 图片 / HTML）+ 技术栈提取（别名归并 / language 优先）
→ 写 trending_snapshots（按日快照 + 排名 / Star 增量 / 连续上榜等趋势字段）
→ 变化仓库入队 summarize_readmes（source=trending）→ 摘要 / 质量抽检
→ 配置 EDGE_BASE_URL 时批量回写 D1（快照 + 摘要）→ 向量化（M3-02）→ 同步 Vectorize（M3-03）
→ admin 热榜页按日期 / 语言筛选，展示趋势徽标（↑ / ↓ / 新上榜 / —）

admin 热榜列表 → 详情页 GET /api/trending/{owner}/{name}（摘要 + 元信息 + 收藏态）
→「一键收藏」POST /api/trending/{owner}/{name}/favorite → upsert my_repositories

每日 04:17（可配）保留任务：过期快照先归档为 gzip JSONL，再删除本地与 D1 同日期范围数据
```

> 快照以 `(snapshot_date, repo_id)` 为主键，重复执行同一日任务幂等；趋势基线最多回看 7 天（M2-05）。
> 保留窗口默认 90 天，归档目录与保留期见 `docs/guides/trending-retention.md`（M2-08）。

容错约定：单页失败只记录并继续其他页；解析异常 / 页面改版降级为空列表 + 告警，
任务不抛异常。告警写入本地 `crawl_alerts`，通过 `GET /api/trending/alerts` 查询、
`POST /api/trending/alerts/{id}/ack` 确认。

### 3.4 推荐流（RAG）

```
用户自然语言查询 → edge → Vectorize 检索（已收藏库 + 热榜库）
→ 结果聚合排序 → 返回（含匹配度与理由）；每日推送任务见 M4
```

### 3.5 模型选型与推理预算（M3-01）

```
摘要任务 → Ollama qwen2.5:1.5b-instruct-q4_K_M（~1.3G，q4_K_M）
向量化任务 → BAAI/bge-m3（~1.1G，int8；fp16 ~2.3G 超预算）
```

- 同一时刻仅加载 1 个模型（摘要与向量化分队列串行），峰值驻留 ≤ `MODEL_BUDGET_MB`（默认 2048）；
- `vps/app/services/model_budget.py` 维护选型表与预算报告，CLI `python -m app.model_budget check` 可离线复跑；
- 部署自检 `deploy/scripts/doctor.sh` 包含 `model_budget` 检查项；模型不可用时仍走 hash 向量 / 截断摘要降级。

### 3.6 向量化流（M3-02）

```
同步 / 抓取完成 → 自动入队 vectorize_repositories（或 POST /api/tasks/vectorize）
→ 按批读取 my_repositories / trending_repositories
→ 文本哈希 + 模型 + 后端判断增量 → EmbeddingService（BGE-M3 / hash 降级）
→ upsert repo_vectors（逐批提交 + 游标）→ 运行状态可查询 / 可断点续跑
→ M3-03 批量同步 Cloudflare Vectorize
```

## 4. 接口边界

### 4.1 admin ↔ edge（JSON over HTTPS，Cookie 会话）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/auth/github/login` | GET | 302 → GitHub 授权（`redirect` 参数回跳） |
| `/api/auth/github/callback` | GET | OAuth 回调（code → 会话） |
| `/api/auth/me` | GET | 当前用户（未登录 401） |
| `/api/auth/logout` | POST | 退出（204） |
| `/api/repos` | GET | 仓库列表（`?q=` / `?categoryId=`，含 `summary`） |
| `/api/trending` | GET | 热榜（`?date=` / `?language=` / `?limit=`；优先读按日快照，返回 `rank` / `rankChange` / `trend` / `summary`，无快照回退最新状态） |
| `/api/trending/dates` | GET | 可用快照日期（倒序） |
| `/api/trending/languages` | GET | 指定日期的语言分布（`?date=`） |
| `/api/trending/history` | GET | 单仓库历史（`?repoId=` / `?days=`） |
| `/api/trending/{owner}/{name}` | GET | 热榜详情（摘要 + 元信息 + 收藏态，登录可选） |
| `/api/trending/{owner}/{name}/favorite` | POST / DELETE | 一键收藏 / 取消收藏（需登录） |
| `/api/trending/alerts` | GET | 抓取告警（`?status=open\|acknowledged\|all`） |
| `/api/trending/alerts/{id}/ack` | POST | 确认抓取告警 |
| `/api/recommendations` | GET | 推荐列表 |
| `/api/categories` | GET | 分类 + 标签 |
| `/api/dashboard/stats` | GET | 仪表盘统计 |
| `/api/sync` | POST | 触发同步任务（202） |

### 4.2 edge ↔ vps（内部 API，`X-Internal-Token`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/tasks/sync` | POST | 入队仓库同步（完成后自动排队摘要） |
| `/api/tasks/summarize` | POST | 入队 README 摘要批量生成（`source=my\|trending\|all`） |
| `/api/repos/summaries` | POST | 反向：VPS 批量回写摘要到 edge / D1 |
| `/api/trending/summaries` | POST | 反向：VPS 批量回写热榜摘要到 edge / D1 |
| `/api/trending/summarize` | POST | 入队热榜摘要生成（`source=trending`） |
| `/api/summaries/quality/samples` | GET | 抽检样本列表（按批次 / 来源 / 复核状态筛选） |
| `/api/summaries/quality/samples/{id}/review` | POST | 人工复核样本（`passed` / `failed`） |
| `/api/summaries/quality/stats` | GET | 抽检质量统计（通过率 / 均分 / 来源分布） |
| `/api/summaries/quality/sample-existing` | POST | 对存量摘要补抽样 |
| `/api/tasks/crawl-trending` | POST | 入队热榜抓取 |
| `/api/tasks/generate-recommendations` | POST | 入队推荐生成 |
| `/api/tasks/daily-push` | POST | 入队每日推送 |
| `/api/tasks/vectorize` | POST | 入队向量化（批量 / 增量 / 断点续跑） |
| `/api/tasks/{taskId}` | GET | 任务状态 |
| `/api/trending/retention` | GET | 热榜保留策略状态（窗口 / 过期数 / 库与归档占用） |
| `/api/trending/retention/cleanup` | POST | 入队热榜归档与清理（`?dryRun=` / `?retentionDays=` / `?archive=`） |
| `/api/internal/trending/snapshots` | POST | VPS → edge：批量 upsert 热榜快照（单批 ≤ 500，`X-Internal-Token`） |
| `/api/internal/trending/retention` | GET | VPS → edge：D1 快照总数与最早 / 最新日期（`X-Internal-Token`） |
| `/api/internal/trending/retention/cleanup` | POST | VPS → edge：按 `beforeDate` 删除过期快照（`X-Internal-Token`） |
| `/api/vectors/stats` | GET | 向量覆盖率与最近运行 |
| `/api/vectors/runs/{runId}` | GET | 向量化运行详情 |
| `/api/vectors/{source}/{repoId}` | GET | 单条仓库向量 |
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
