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

### 3.4 推荐流（RAG / M3-07 闭环）

```
VPS 生成（Celery / POST /api/tasks/generate-recommendations）
→ 按用户从 edge GET /api/internal/recommendations/feedback 拉取 saved / dismissed
→ 排除已收藏、已忽略与本地收藏库 → 余弦排序 + 中文理由
→ 本地 recommendations 落库
→ POST /api/internal/recommendations/upsert 回写 D1（saved / dismissed 状态不被覆盖）
→ admin 推荐页 GET /api/recommendations?status=new
→ 用户收藏 / 忽略 / 查看（save / dismiss / click 接口写 recommendation_feedback）
→ 下一轮生成读取反馈，形成闭环

降级：edge 未配置或不可达时使用本地 recommendations 状态兜底；回写失败只记日志，
不影响本地生成结果。
```

### 3.4.1 每日推荐生成（M3-05）

每日推荐生成（M3-05）：

```
Celery beat 08:30 → 收藏库平均向量（复用 repo_vectors）→ 热榜候选
→ 排除已收藏 → 相似度 × 0.8 + 热榜热度 × 0.2 → 阈值过滤 → top_k
→ upsert recommendations（旧 new 未入选标记 expired）→ 09:00 推送准备
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

### 3.7 向量索引同步流（M3-03）

```
Celery beat（每日 04:37）或 POST /api/vector-index/sync
→ VPS 读取本地 repo_vectors（仅 text_hash / model / backend / dim 变化或上次失败项；full 可全量）
→ 按批 POST {EDGE_BASE_URL}/api/internal/vectors/upsert（X-Internal-Token）
→ edge Worker 通过 Vectorize 绑定批量 upsert
→ VPS 写 vector_index_state（逐条状态）/ vector_index_runs（运行统计 + 断点游标）

对账（每日 05:17 或 POST /api/vector-index/reconcile）：getByIds 比对缺失 / 过期向量，
可选修复并按开关清理孤儿（默认关闭）。
```

### 3.8 语义搜索流（M3-04 / M3-10）

```
admin 搜索页 POST /api/search/semantic（登录态）
→ edge 调 VPS POST /api/search/embed（X-Internal-Token）
   ↳ VPS 先做查询理解：同义词 / 技术栈词表扩展（expand=false 可关闭），返回 understanding
→ edge 通过 Vectorize 绑定做近邻检索（topK 放大后按 source / user 过滤）
→ edge 从 D1 水合（my 仅当前用户；trending 全局）→ 返回匹配度 + 项目元信息

降级链：
Vectorize 未绑定 / 查询失败 / 水合 0 条 → VPS POST /api/search/query（本地 repo_vectors 余弦）
→ VPS 不可达 → edge D1 关键词 LIKE 检索（mode=keyword，使用 understanding.keywordTerms 多词 OR 召回）
```

### 3.9 推荐理由生成流（M3-06）

```
generate_recommendations / POST /api/recommend/query
→ build_user_profile（收藏库语言 / 技术栈 / 分类）
→ build_reason_detail（相似度分档 + 共同语言 / 技术栈 / 分类 / 今日热度 / 简介）
→ reason（中文）+ based_on（JSON 数组）
→ 写 recommendations.reason / based_on；存量可 POST /api/tasks/regenerate-recommendation-reasons 回填
```

纯规则、不调用 LLM；收藏库为空时退化为候选字段 + 相似度，不虚构用户偏好。

### 3.10 推荐质量评估（M3-08）

```
POST /api/recommend/eval（离线、只读）
→ 收藏库按种子切分：画像集 + 留出正样本（多个 fold）
→ 热榜未收藏仓库采样为负样本 → 复用 repo_vectors / 缺失时编码
→ 计算 Precision@K / Recall@K / HitRate / MRR / NDCG / 覆盖率 / 多样性
→ min_score × 相似度权重二维扫描 → 返回 current / thresholds / weights / recommended
→ 运维确认后写入 .env（不自动修改运行配置）
```

### 3.11 降级路径（M3-09）

```
EmbeddingService 加载前 → resolve_embedding_spec 估算驻留
  ├─ 依赖缺失 / 模型加载失败 → hash 向量（256 维 char-trigram、blake2b、L2 归一化）
  └─ 估算驻留 > MODEL_BUDGET_MB → 不加载模型，直接 hash（degraded_reason=over_budget）

summarize() → Ollama（超预算则跳过请求）→ DeepSeek → 截断原文（带降级说明）
```

- 降级自检 `python -m app.degradation check [--json]` 五项全部离线执行，PASS 退出码 0；
- `GET /api/degradation/status` 返回当前配置的预期后端、LLM 降级标记与五项检查结果；
- 测试不依赖模型与网络，覆盖「模型缺失 / 超预算 → hash 向量 / 截断摘要」两条主路径。

查询理解结果（`query` / `rewritten` / `techStack` / `concepts` / `terms` / `keywordTerms`）随搜索响应返回：
admin 搜索页展示「查询理解」标签，edge 关键词兜底使用扩展词提升召回。

### 3.12 相似项目推荐流（M6-02「看了又看」）

```
admin 热榜详情页 GET /api/similar?source=trending&repoId=owner/name&topK=6
→ edge 校验参数并从 D1 读取种子仓库（source=my 时校验归属当前用户）
→ edge 调 VPS POST /api/search/similar（X-Internal-Token）
   ↳ 读取种子仓库 repo_vectors 向量 → 同 model / dim 向量余弦近邻 → topK
→ edge 按 source 水合 D1（my 仅当前用户；trending 全局）→ 返回匹配度 + 中文理由

降级：
VPS 不可达 / 种子未向量化 / 0 命中 → edge D1 同语言 + 共享技术栈打分
（mode=keyword，理由明确为语言 / 技术栈匹配，不冒充语义相似度）
```

纯向量近邻复用 M3 `repo_vectors`，不新增表；`scope` 控制候选来源（`my` / `trending` / `all`），
`excludeSaved` 可排除收藏库；`minScore` 可过滤低分近邻。

### 3.13 依赖分析流（M6-07）

```
admin「依赖分析」页 GET /api/analysis/dependencies（登录态）
→ edge 从 D1 读取当前用户仓库 id / language（最多 100 个）
→ edge 调 VPS GET /api/analysis/dependencies?repoIds=...&top=20（X-Internal-Token）
   ↳ VPS 聚合 repo_dependencies + repo_dependency_scans + my_repositories.language
→ 返回 summary / techStack / ecosystems / dependencies / links / repos

刷新：admin POST /api/analysis/dependencies/refresh
→ edge 以当前用户仓库 id 调 VPS POST /api/analysis/dependencies/refresh
→ VPS 按仓库拉取 package.json / requirements.txt / pyproject.toml / go.mod /
   Cargo.toml / pom.xml / Gemfile / composer.json，解析后覆盖式写入
降级：VPS 不可达 → edge buildLocalOverview 只按 D1 语言给出本地概览（mode=local）
```

依赖明细只落 VPS 本地 SQLite，不复制到 D1；扫描按 `DEPENDENCY_SCAN_TTL_HOURS`
跳过最近成功仓库，单仓库失败保留旧依赖并标记 `failed`；每日 06:23 由 Celery beat 增量补扫。

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
| `/api/recommendations` | GET | 推荐列表（`?status=new\|saved\|dismissed\|all`、`?limit=`） |
| `/api/recommendations/stats` | GET | 推荐状态统计 + 点击反馈数 |
| `/api/recommendations/:id/save` | POST | 收藏推荐（写 my_repositories + saved 反馈） |
| `/api/recommendations/:id/dismiss` | POST | 忽略推荐（可带 `reason`） |
| `/api/recommendations/:id/click` | POST | 记录查看点击（clicked 反馈） |
| `/api/categories` | GET | 分类 + 标签 |
| `/api/dashboard/stats` | GET | 仪表盘统计 |
| `/api/sync` | POST | 触发同步任务（202） |
| `/api/search/semantic` | POST | 语义搜索（`query` / `topK` / `scope`；vectorize → local → keyword 三级降级） |
| `/api/similar` | GET | 相似项目推荐（`source=my\|trending` / `repoId` / `topK` / `scope` / `minScore` / `excludeSaved`；local → keyword 降级） |
| `/api/analysis/dependencies` | GET | 依赖分析聚合（`?top=`；当前用户仓库 → VPS；VPS 不可达回退 D1 语言概览） |
| `/api/analysis/dependencies/refresh` | POST | 扫描当前用户仓库依赖清单（VPS 不可达返回 `status=unavailable`） |

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
| `/api/tasks/regenerate-recommendation-reasons` | POST | 入队重算存量推荐理由与依据字段 |
| `/api/tasks/daily-push` | POST | 入队每日推送 |
| `/api/recommend/query` | POST | 语义查询（返回 `reason` + `based_on`） |
| `/api/recommend/list` | GET | 本地已生成推荐（`reason` + `based_on`） |
| `/api/tasks/vectorize` | POST | 入队向量化（批量 / 增量 / 断点续跑） |
| `/api/tasks/{taskId}` | GET | 任务状态 |
| `/api/trending/retention` | GET | 热榜保留策略状态（窗口 / 过期数 / 库与归档占用） |
| `/api/trending/retention/cleanup` | POST | 入队热榜归档与清理（`?dryRun=` / `?retentionDays=` / `?archive=`） |
| `/api/internal/trending/snapshots` | POST | VPS → edge：批量 upsert 热榜快照（单批 ≤ 500，`X-Internal-Token`） |
| `/api/internal/trending/retention` | GET | VPS → edge：D1 快照总数与最早 / 最新日期（`X-Internal-Token`） |
| `/api/internal/trending/retention/cleanup` | POST | VPS → edge：按 `beforeDate` 删除过期快照（`X-Internal-Token`） |
| `/api/vector-index/sync` | POST | 入队 Vectorize 同步（`mode=incremental|full` / `scope` / `limit` / `batchSize`） |
| `/api/vector-index/reconcile` | POST | 入队对账（`scope` / `repair` / `limit`） |
| `/api/vector-index/status` | GET | 本地向量覆盖率与同步状态分布 |
| `/api/vector-index/runs` | GET | 最近同步运行记录 |
| `/api/vector-index/runs/{runId}` | GET | 单次运行详情 |
| `/api/search/embed` | POST | 查询向量化（供 edge 调用 Vectorize） |
| `/api/search/query` | POST | 本地 `repo_vectors` 余弦检索（降级路径） |
| `/api/search/semantic` | POST | 本地检索并水合完整项目信息 |
| `/api/search/similar` | POST | 相似项目向量近邻（`source` / `repoId` / `topK` / `scope` / `minScore` / `excludeSaved`；返回未水合 hits） |
| `/api/search/status` | GET | 向量覆盖率、模型分布与最近向量化运行 |
| `/api/analysis/dependencies` | GET | 依赖分析聚合（`repoIds` 逗号分隔 / `top`；只读本地表） |
| `/api/analysis/dependencies/refresh` | POST | 扫描依赖清单并入库（`repoIds` / `force` / `limit`） |
| `/api/vectors/stats` | GET | 向量覆盖率与最近运行 |
| `/api/vectors/runs/{runId}` | GET | 向量化运行详情 |
| `/api/vectors/{source}/{repoId}` | GET | 单条仓库向量 |
| `/api/search/understand` | POST | 查询理解：同义词 / 技术栈词表扩展（`query` / `expand`） |
| `/api/recommend/eval` | POST | 推荐质量评估与阈值 / 权重调参建议（抽样评估集） |
| `/api/degradation/status` | GET | 降级路径自检（模型缺失 / 超预算） |
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
