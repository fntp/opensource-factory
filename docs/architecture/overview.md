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

### 1.1 本机一体化模式（可选，REQ-202610-0940 / M5-02）

默认架构为上面的混合模式（Q9 选项 A）。开启 `LOCAL_MODE=1` 后，`openfactory-api`
在同一进程内额外提供 admin 静态托管与 edge 兼容的只读 API，可完全脱离 Cloudflare 运行：

```
浏览器 → http://127.0.0.1:8000/
         ├── GET /                 admin/dist（SPA 回退）
         ├── GET /local/api/*      edge 兼容只读 API（本机单用户）
         └── GET /api/*            既有 VPS 内部任务 API（X-Internal-Token）
                     │
                     ▼
         /opt/openfactory/data/*.db（SQLite 镜像）
```

边界约定：

- `/local/api/*` 仅在 `LOCAL_MODE=1` 时注册，默认 404；只读，不做 GitHub OAuth；
- 静态托管只服务 `LOCAL_ADMIN_DIR` 内的文件，未知路径回退 `index.html`，并做路径穿越防护；
- 写操作、通知、OAuth 等仍由 edge 承担；本机模式首版只覆盖仪表盘 / 仓库 / 热榜 / 推荐 / 分类；
- 部署、资源与安全细则见 [local-allinone-deployment.md](../guides/local-allinone-deployment.md)。

## 2. 组件职责

| 组件 | 目录 | 职责 | 不该做的事 |
| --- | --- | --- | --- |
| 前端控制台 | `admin/` | 展示、交互、调用 edge API | 不存密钥、不做业务计算 |
| 边缘 API | `edge/` | 鉴权、调度、D1 读写、Vectorize 检索、Workers 请求指标聚合 | 不跑长任务、不跑模型 |
| 算力节点 | `vps/` | 爬虫、清洗、摘要、向量化、推荐、推送、健康检查与资源监控 | 不对外暴露（仅内网/内部 token） |
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

### 3.4.1 每日推荐生成与评估（M3-05 + M4-01）

每日推荐生成与评估（M3-05 + M4-01）：

```
Celery beat 08:30 → 收藏库平均向量（复用 repo_vectors）→ 热榜候选
→ 排除已收藏 → 相似度 × 0.8 + 热榜热度 × 0.2 → 阈值过滤 → top_k
→ upsert recommendations（status=new、match_score=原始相似度；旧 new 未入选标记 expired）
08:45 每日评估 → 质量分 = 仓库质量 × 0.7 + 理由质量 × 0.3
→ 双重门槛：match_score ≥ EVAL_MATCH_THRESHOLD 且 quality_score ≥ EVAL_QUALITY_THRESHOLD
→ qualified / filtered，写 recommendation_evaluation_runs
→ 推送准备按用户偏好（时间 / 阈值 / 通道）经 M4-07 静默 / 去重 / 日限额闸门
→ 通过的 qualified 标记为 pushed，并写 push_events 账本
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

### 3.8.1 README 全文检索流（M6-01）

```
README 抓取（同步 / 摘要管线 / 每日补索引任务）
→ clean_readme 清洗 → repo_readmes（VPS SQLite 全文镜像，source + repo_id 联合主键）
→ SQLite 触发器 repo_readmes_ai/au/ad 同步 repo_readme_fts（FTS5 trigram）

admin 搜索页 POST /api/search/fulltext（登录态，全文 / 语义切换）
→ edge 调 VPS POST /api/search/fulltext（X-Internal-Token）
   ↳ bm25 排序 + 原文命中片段 + 水合项目元信息
→ edge 按 D1 user_id 过滤 my 结果 / 校验 trending 存在性
→ 返回 mode=fts（短词回退 mode=like）
→ VPS 不可用 / 无命中 → edge D1 关键词 LIKE 检索（mode=keyword）
```

- trigram 要求查询词 ≥3 字符；1~2 字短词自动回退 LIKE，不返回 500；
- `GET /api/search/fulltext/status` 可观测索引覆盖率，`POST /api/search/fulltext/rebuild` 支持灾备重建；
- D1 不保存 README 全文，保持「本地镜像先行」；索引随 `repo_readmes` 增删改自动同步。

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
### 3.12 站内通知流（M4-02）

```
VPS 每日评估 → recommendations.status = 'pushed'
→ admin 打开通知中心 / 轮询未读数 → edge 惰性物化 notifications（幂等）
→ 用户标记已读 / 全部已读 / 忽略 → 未读数徽标同步刷新
```

通知正文与推荐快照同表存储，前端无需二次请求推荐接口；同一 `(user_id, recommendation_id)` 只生成一条通知。

### 3.13 Bark 推送流（M4-03）

```
Celery beat（每天 09:05）或 POST /api/push/bark/dispatch
→ 读取 recommendations：status='pushed' 且 bark_sent_at IS NULL
  （可选 user_id 过滤，按 quality_score / score 降序取前 BARK_MAX_PER_RUN 条）
→ 组装中文消息（标题 owner/name；正文 = 简介 + 推荐理由 + 匹配度 / 语言 / Star）
→ POST {BARK_SERVER_URL}/push（device_key / title / body / group / level / url）
→ 成功：写 bark_sent_at、清空 bark_error；失败：写 bark_error（截断 300 字符）留待重试

降级：BARK_ENABLED=false 或 BARK_DEVICE_KEY 为空 → 任务 skipped；
BARK_DRY_RUN=true → 只返回预览，不发送、不写标记；
网络 / Bark 返回异常 → 单条失败不中断整批。
```

M4-02 站内通知中心与本通道消费同一批 `pushed` 推荐，彼此独立：站内通知失败不影响 Bark 投递，反之亦然。

### 3.14 Telegram 推送流（M4-04）

```
Celery beat 09:05（daily_push 之后）或 POST /api/tasks/send-telegram-digest
→ 读取最近 TELEGRAM_DIGEST_WINDOW_HOURS 小时内 status=pushed 的推荐
→ 关联 trending_repositories（标题 / 简介 / 链接 / 今日 Star）
→ 生成中文 HTML 摘要（转义 + 按 3800 字符分片，≤ Telegram 4096 上限）
→ POST {TELEGRAM_API_BASE}/bot{token}/sendMessage（429 / 5xx / 网络异常指数退避）
→ 写 telegram_deliveries（sent / failed / pending；同日同会话最小幂等）
```

未启用 / 未配置 / 无数据时任务返回结构化状态并直接跳过，不访问网络；Bot Token 仅存
VPS 本机 `.env`，状态接口只返回脱敏 chat id。

### 3.15 Email 推送流（M4-05）

```
Celery beat 09:10 或 POST /api/tasks/send-email-digest
→ 读取 recommendations.status='pushed'（默认回溯 24h，按质量分 / 匹配度排序）
→ 水合 trending_repositories（回退 my_repositories）→ 渲染中文摘要（plain + HTML）
→ 校验 EMAIL_* 配置 / 收件人 → smtplib 投递（STARTTLS / SSL / AUTH，瞬时错误重试）
→ 写 email_deliveries（sent / failed，收件人脱敏、Message-ID、错误脱敏）
→ 同日同收件人已有 sent 记录时跳过（force 可补发）
```

未启用 / 未配置 / 无数据 / SMTP 失败分别返回 `disabled` / `not_configured` / `empty` / `failed`，
不阻塞每日推送主流程；站内通知中心（M4-02）与本通道互不影响。

### 3.16 推送偏好流（M4-06）

```
admin「设置 → 通知设置」→ GET/PUT /api/push-preferences（edge，登录态）
→ D1 push_preferences（按用户保存时间 / 阈值 / 通道开关）
→ VPS 推送任务通过 GET /api/internal/push-preferences（X-Internal-Token）拉取
→ 仅对到达推送时间、至少开启一个通道的用户，按阈值筛选 qualified 推荐
→ 标记 pushed（站内通知中心惰性物化；Bark / Telegram / Email 通道按开关下发）
```

未保存偏好的用户使用默认值（启用、09:00、Asia/Shanghai、匹配度 0.35、质量分 0.55、仅站内通知）；edge 不可达时 VPS 回退默认值，不阻塞推送。

### 3.17 推送去重与静默流（M4-07）

```
qualified 推荐 → Celery beat 09:00 daily_push（或静默结束后 retry_deferred_push）
→ 读取 PUSH_* 策略（开关 / 静默时段 / 去重窗口 / 每日上限）
→ 静默中：不改状态，整体 deferred，等待下一轮重试
→ 去重命中（窗口内同用户同仓库）：标记 expired，写 push_events(skipped)
→ 超过每日上限：保留 qualified，写 push_events(skipped)
→ 通过：标记 pushed + 写 push_events(prepared)
→ 站内通知中心 / Bark / Telegram / Email 只消费 pushed
```

所有通道共用 `push_events` 账本；通道侧重试前可调用 `POST /api/push/policy/check` 复核。
静默窗口支持跨午夜（如 22:00–08:00），按 `PUSH_TIMEZONE` 解释；`PUSH_POLICY_ENABLED=false`
时 `daily_push` 保持旧行为（仅把 `qualified` 标记为 `pushed`）。

### 3.18 推送记录与回执（M4-08）

```
Bark / Telegram / Email 每次实际发送
→ push_records.create_delivery：写 push_deliveries（channel / kind / target / status）
→ 发送结束：finish_delivery 回写 sent / failed / skipped、消息数与 message_id
→ 服务商回调或人工补记：POST /api/push/receipts
→ push_receipts 追加 accepted / delivered / bounced / failed 流水
→ 回执更新 push_deliveries.receipt_status，并同步 email_deliveries / telegram_deliveries 状态
```

查询：`GET /api/push/records`（通道 / 状态 / 类型 / 时间 / 关键字 + 分页）、
`GET /api/push/records/stats`（分通道 / 分状态计数与送达率）、
`GET /api/push/records/{id}`（详情 + 回执时间线）。目标在 API 输出时统一脱敏；
已 `delivered` 的记录不会被迟到的 `accepted` / `bounced` 回执降级。

```

### 3.19 限流与登录防护（M5-05）

```
admin / 匿名请求 → edge /api/*
  ├─ 会话解析 → 限流桶（auth / write / read）
  │    ├─ 已登录：sha256(scope:user:<id>)
  │    └─ 匿名：sha256(scope:ip:<客户端 IP>)
  ├─ D1 rate_limit_counters 固定窗口计数（UPSERT + RETURNING）
  │    ├─ 未超限 → 放行并回写 X-RateLimit-* 响应头
  │    └─ 超限 → 429 rate_limited + Retry-After（auth 桶同时记 security_events）
  └─ D1 异常 → fail-open（放行并记录日志）

GitHub OAuth callback → login_attempts / security_events
  ├─ 失败（state / token / userinfo）→ 记失败，窗口内达到阈值 → 记 login_locked
  ├─ 锁定中 → 429 login_locked + Retry-After
  └─ 成功 → 清除该 IP 的失败记录并记 login_succeeded
```

- edge 侧 `/api/internal/*` 不走 IP 限流（由内部令牌保护），避免 VPS 批量任务被误伤；
- VPS 侧另有进程内滑动窗口（`RATE_LIMIT_*`），`/api/tasks`、`/api/vector-index`、`/api/search`、`/api/recommend/eval` 使用更低的「重接口」阈值；
- 限流身份只落 sha-256 哈希，不存明文 IP；`rate_limit_counters` 过期行与历史安全事件由 `POST /api/internal/security/cleanup` 定期清理。

### 3.20 监控与告警流（M5-03）

```
Celery beat（每 5 分钟）→ VPS monitoring.run_monitoring_check
  ├── 采集：cgroup / 进程 RSS 内存、/proc/loadavg、运行目录磁盘、日志目录
  ├── 健康检查：数据库 / 运行目录 / Redis(TCP) / edge /healthz / 模型预算
  ├── 阈值判定：内存 3.5G 预警 / 4G 严重、磁盘 13G / 15G、日志预算、失败检查
  ├── 告警：monitoring_alerts 按 dedupe_key 去重（冷却窗口累计次数，恢复自动 resolved）
  └── 历史：monitoring_check_runs 保存最近检查快照（默认保留 7 天）
        ↓
edge 中间件按 日期/路由/方法/状态类 UPSERT worker_metrics（D1，迁移 0012）
        ↓
admin /monitoring → GET /api/monitoring/overview（edge 合并 VPS 状态 + Workers 指标）
```

VPS 端点同时提供 `GET /healthz/ready`（数据库 + 运行目录就绪探针）与
`/api/monitoring/{status,check,history,alerts,logs}`（全部要求 `X-Internal-Token`）；
edge 侧 `/api/monitoring/overview` 需登录，`/api/internal/analytics` 供内部工具读取 Workers 聚合。

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

### 3.13 重复 / 相似项目检测（M6-03）

```
admin 重复检测页 POST /api/duplicates/scan {scope, minScore?, maxClusters?}
→ edge 读取当前用户收藏 + 热榜（上限 500），把 myRepoIds 传给 VPS（不传用户身份）
→ VPS POST /api/duplicates/scan：
   地址归一化（platform:owner/repo）→ 名称 SequenceMatcher / token Jaccard
   → 简介 token Jaccard（中文 bigram）→ 同 model/dim 向量余弦复核
   → union-find 聚类 → 选保留项 + 字段合并建议（只读，不落库）
→ edge 按 D1 行水合、二次校验 my 归属、按用户过滤已忽略簇 → 返回簇列表
```

降级：VPS 不可达时 edge 用名称 / 简介规则本地兜底（`mode=local`）；VPS 可用时本地规则只补扫收藏库
（`mode=hybrid`）。忽略记录存 D1 `duplicate_dismissals`（按 `user_id + cluster_key` 唯一），
簇成员变化后 `cluster_key` 改变，会重新出现供复核。

阈值：`DUPLICATE_NAME_THRESHOLD`（0.86）、`DUPLICATE_DESCRIPTION_THRESHOLD`（0.75）、
`DUPLICATE_VECTOR_THRESHOLD`（0.88）、`DUPLICATE_MIN_CONFIDENCE`（0.70）、
`DUPLICATE_MAX_REPOS`（500）、`DUPLICATE_MAX_CLUSTERS`（50）。检测为 O(n²) 有界扫描，
超过 500 个仓库时按 Star 截断，后续可改为分桶 / 向量近邻候选。
### 3.14 技术栈图谱流（M6-04）

```
admin /tech-stack → GET /api/tech-stack（登录态）
  → edge 读取 D1 my_repositories + repo_tags / tags（均按 user_id 隔离）
  → 语言归一（language 字段）+ 框架启发式识别（标签精确命中 → 简介 / 摘要关键词）
  → 聚合语言榜、框架榜、语言 × 框架连线（Top 8 语言 × Top 16 框架）
  → admin 渲染 KPI、径向关系图、语言条形榜、框架排行与组合洞察
```

- 只读聚合，不新增表、不依赖 VPS；数据口径为当前账号收藏的全部仓库；
- 框架别名表在 `edge/src/tech-stack/catalog.ts`，聚合逻辑 `aggregate.ts` 为纯函数；
- `share` 以全部收藏仓库数为分母；覆盖率 = 语言或框架至少识别其一的仓库占比；
- 图谱只保留 Top N 节点与两端均在图中的连线，长尾仍可在框架排行表中查看。

### 3.15 项目健康度追踪（M6-05）

```
admin 仓库页「刷新健康度」POST /api/repos/health/refresh（edge，登录）
→ edge 转发 VPS POST /api/repos/health/refresh（X-Internal-Token）
→ Celery refresh_repo_health：按 id 或最久未检查顺序拉 GitHub GET /repos/{owner}/{repo}
   ↳ 更新 VPS 镜像 pushed_at / updated_at / open_issues_count / archived / disabled
   ↳ 计算 health_status / health_score / health_checked_at
→ VPS 批量回写 POST {edge}/api/repos/health（X-Internal-Token）→ D1 my_repositories
→ admin GET /api/repos 内嵌 health（edge 本地按 D1 字段计算，VPS 结果优先）
```

分档规则（默认值可通过 `REPO_HEALTH_*` 配置）：最后提交 ≤90 天为 `active`，≤180 天为
`attention`，≤365 天为 `stale`；超过 365 天仍为 `stale` 但分数降到 20。归档直接 `archived`（0 分），
GitHub 禁用强制 `stale` 且封顶 30 分，缺少 `pushed_at` 为 `unknown`。未关闭 issue / Star 比例
≥50% 扣 20 分、≥20% 扣 10 分，只影响分数不影响状态；无 issue 加 5 分。VPS 每日 06:12
（`REPO_HEALTH_HOUR/MINUTE`）自动刷新一批（默认 200 个），也可手动触发。

### 3.16 License 识别与合规提示流（M6-06）

```
VPS 定时任务 enrich_licenses（每日 06:47 beat，或 POST /api/tasks/enrich-licenses 手动触发）
→ 逐仓库识别：GitHub API license.spdx_id 优先
   ↳ 无元数据时读 README：SPDX-License-Identifier / shields 徽章 / 许可证名称正则
   ↳ 仍未命中 → unknown（license_source=none）
→ 写入本地镜像 license_spdx / license_name / license_source / license_checked_at
→ POST {edge}/api/internal/licenses 批量回写 D1（my_repositories / trending_repositories）
→ edge 读取时按 SPDX 目录派生 category / riskLevel / obligations / warnings
→ admin 仓库列表、热榜列表与详情页展示 License 徽章；/licenses 汇总覆盖率与风险分布

分类：permissive / weak-copyleft / strong-copyleft / network-copyleft / public-domain / unknown
风险：low / medium / high / unknown（AGPL 等网络著佐权为 high，无许可证按 unknown 提示）
```

分类与义务在读取时派生，数据库只存 SPDX 与来源，避免升级目录后存量数据口径不一致；
提示为工程辅助信息，不构成法律意见。

### 3.17 依赖分析流（M6-07）

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

### 3.18 知识库导出流（M6-08）

```
admin /export → GET /api/export/knowledge/summary（登录态）→ 统计卡
→ 选择格式 / 是否含摘要 / 分组方式
→ GET /api/export/knowledge?format=markdown|json|obsidian&includeSummary=1|0&groupBy=category|none
→ edge 按 user_id 只读查询 my_repositories + categories + tags / repo_tags
→ 纯函数构建：JSON（openfactory.knowledge.v1）/ Markdown（单文件）/ Obsidian（ZIP Vault）
→ Content-Disposition 附件下载（Cache-Control: no-store）
```

只读聚合，不新增表、不写 D1；格式规范（JSON Schema、Markdown 结构、Obsidian 目录与
frontmatter）见 `docs/guides/knowledge-export.md`，并作为 M9-04 全量归档的格式基线。

## 4. 接口边界

### 4.1 admin ↔ edge（JSON over HTTPS，Cookie 会话）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/auth/github/login` | GET | 302 → GitHub 授权（`redirect` 参数回跳） |
| `/api/auth/github/callback` | GET | OAuth 回调（code → 会话） |
| `/api/auth/me` | GET | 当前用户（未登录 401） |
| `/api/auth/logout` | POST | 退出（204） |
| `/api/repos` | GET | 仓库列表（`?q=` / `?categoryId=`，含 `summary` / `health`） |
| `/api/repos/health` | GET | 当前用户仓库健康度列表与汇总（`?status=active\|attention\|stale\|archived\|unknown`） |
| `/api/repos/health/refresh` | POST | 触发 VPS 刷新健康度（202；VPS 未配置时返回 accepted 提示） |
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
| `/api/notifications` | GET | 通知列表（`?status=` / `?limit=` / `?offset=`，需登录） |
| `/api/notifications/unread-count` | GET | 未读数（侧边栏徽标轮询） |
| `/api/notifications/:id/read` | POST | 单条标记已读（幂等） |
| `/api/notifications/read-all` | POST | 全部标记已读 |
| `/api/notifications/:id/dismiss` | POST | 忽略通知（同步推荐状态） |
| `/api/push-preferences` | GET | 当前用户推送偏好（未保存时返回默认值） |
| `/api/push-preferences` | PUT | 保存推送偏好（时间 / 时区 / 阈值 / 通道开关） |
| `/api/sync` | POST | 触发同步任务（202） |
| `/api/search/semantic` | POST | 语义搜索（`query` / `topK` / `scope`；vectorize → local → keyword 三级降级） |
| `/api/tech-stack` | GET | 技术栈图谱（登录态；语言 / 框架聚合 + 语言 × 框架关系图，Top 8 × 16） |
| `/api/monitoring/overview` | GET | 监控总览（登录态；合并 VPS 状态与 Workers 指标，`?days=1..30`） |
| `/api/monitoring/check` | POST | 触发一次 VPS 监控检查（登录态代理） |
| `/api/monitoring/alerts/:id/ack` | POST | 确认监控告警（登录态代理） |
| `/api/search/fulltext` | POST | README 全文检索（`query` / `topK` / `scope` / `offset`；VPS FTS → D1 关键词回退） |
| `/api/similar` | GET | 相似项目推荐（`source=my\|trending` / `repoId` / `topK` / `scope` / `minScore` / `excludeSaved`；local → keyword 降级） |
| `/api/duplicates/scan` | POST | 重复 / 相似项目扫描（`scope` / `minScore` / `maxClusters`；VPS 规则 + 向量 → 本地兜底；需登录） |
| `/api/duplicates/dismiss` | POST | 忽略一个重复簇（`clusterId` / `repoIds` / `reason`，按用户存 D1） |
| `/api/duplicates/dismissed` | GET | 当前用户已忽略的重复簇 |
| `/api/duplicates/dismiss/:clusterId` | DELETE | 取消忽略（恢复展示） |
| `/api/licenses/catalog` | GET | License 目录（分类 / 风险 / 义务 / 提醒，公开） |
| `/api/licenses/summary` | GET | License 分布与风险统计（`?scope=my\|trending\|all`；`my` / `all` 需登录） |
| `/api/analysis/dependencies` | GET | 依赖分析聚合（`?top=`；当前用户仓库 → VPS；VPS 不可达回退 D1 语言概览） |
| `/api/analysis/dependencies/refresh` | POST | 扫描当前用户仓库依赖清单（VPS 不可达返回 `status=unavailable`） |
| `/api/export/knowledge/summary` | GET | 知识库导出统计（登录态；项目 / 摘要 / 分类 / 标签 / Star） |
| `/api/export/knowledge` | GET | 生成知识库附件（`format` / `includeSummary` / `groupBy`，登录态） |

### 4.2 edge ↔ vps（内部 API，`X-Internal-Token`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/tasks/sync` | POST | 入队仓库同步（完成后自动排队摘要） |
| `/api/tasks/summarize` | POST | 入队 README 摘要批量生成（`source=my\|trending\|all`） |
| `/api/repos/summaries` | POST | 反向：VPS 批量回写摘要到 edge / D1 |
| `/api/repos/health` | POST | 反向：VPS 批量回写健康度快照到 edge / D1（单批 ≤ 500） |
| `/api/repos/health/refresh` | POST | 入队刷新仓库元数据与健康度（`repoIds` / `limit`） |
| `/api/repos/health` | GET | 健康度列表与汇总（`?status=` / `limit` / `offset`） |
| `/api/repos/{repo_id}/health` | GET | 单仓库健康度详情 |
| `/api/trending/summaries` | POST | 反向：VPS 批量回写热榜摘要到 edge / D1 |
| `/api/trending/summarize` | POST | 入队热榜摘要生成（`source=trending`） |
| `/api/summaries/quality/samples` | GET | 抽检样本列表（按批次 / 来源 / 复核状态筛选） |
| `/api/summaries/quality/samples/{id}/review` | POST | 人工复核样本（`passed` / `failed`） |
| `/api/summaries/quality/stats` | GET | 抽检质量统计（通过率 / 均分 / 来源分布） |
| `/api/summaries/quality/sample-existing` | POST | 对存量摘要补抽样 |
| `/api/tasks/crawl-trending` | POST | 入队热榜抓取 |
| `/api/tasks/sync-readmes` | POST | 入队 README 全文索引补录（`source` / `repoIds` / `limit` / `force`） |
| `/api/tasks/generate-recommendations` | POST | 入队推荐生成 |
| `/api/tasks/regenerate-recommendation-reasons` | POST | 入队重算存量推荐理由与依据字段 |
| `/api/tasks/evaluate-recommendations` | POST | 入队每日评估（质量分 + 匹配度阈值） |
| `/api/tasks/daily-push` | POST | 入队每日推送（按用户偏好 + M4-07 策略筛选 `qualified`，可 `respect_schedule`） |
| `/api/tasks/send-telegram-digest` | POST | 入队 Telegram 每日摘要（M4-04，可选 `user_id` / `limit` / `force`） |
| `/api/tasks/send-email-digest` | POST | 入队 Email 每日摘要（`user_id` / `limit` / `force`） |
| `/api/recommend/query` | POST | 语义查询（返回 `reason` + `based_on`） |
| `/api/recommend/list` | GET | 本地已生成推荐（`reason` + `based_on`） |
| `/api/notifications/telegram/status` | GET | Telegram 通道状态（不返回 token，chat id 脱敏） |
| `/api/notifications/telegram/test` | POST | 发送 Telegram 测试消息 |
| `/api/notifications/email/status` | GET | Email 通道状态与最近送达（脱敏） |
| `/api/notifications/email/test` | POST | 发送测试邮件（未启用 / 未配置 409） |
| `/api/push/policy/status` | GET | 推送策略状态：静默、限额、今日计数与最近事件 |
| `/api/push/policy/check` | POST | 单条推送发送前预演（不写库） |
| `/api/push/policy/events` | GET | 查询推送事件（按用户 / 通道 / 状态） |
| `/api/push/policy/events` | POST | 记录通道投递事件（幂等） |
| `/api/push/records` | GET | 推送记录列表（通道 / 状态 / 类型 / 时间 / 关键字 + 分页） |
| `/api/push/records/stats` | GET | 推送记录统计（分通道 / 分状态计数与送达率） |
| `/api/push/records/{id}` | GET | 推送记录详情 + 回执时间线（目标脱敏） |
| `/api/push/receipts` | POST | 追加服务商回执（accepted / delivered / bounced / failed） |
| `/api/tasks/vectorize` | POST | 入队向量化（批量 / 增量 / 断点续跑） |
| `/api/internal/notifications` | POST | 批量写入站内通知（`X-Internal-Token`，单批 ≤100） |
| `/api/internal/notifications/sync-recommendations` | POST | 物化指定用户的 `pushed` 推荐为通知 |
| `/api/tasks/enrich-licenses` | POST | 入队 License 识别补全（`scope=my\|trending\|all` / `limit` / `force`） |
| `/api/licenses/catalog` | GET | License 目录（VPS 侧同一份目录） |
| `/api/licenses/summary` | GET | 本地镜像 License 分布与风险统计（`?scope=`） |
| `/api/repos/{repoId}/license` | GET | 单仓库 License 合规提示（未识别时返回 unknown 结构） |
| `/api/internal/licenses` | POST | 反向：VPS 批量回写 License 到 edge / D1（`X-Internal-Token`） |
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
| `/api/search/fulltext` | POST | README 全文检索（FTS5 trigram，短词 LIKE 回退，返回 snippet） |
| `/api/search/fulltext/status` | GET | README 全文索引覆盖率与来源分布 |
| `/api/search/fulltext/rebuild` | POST | 全量重建 README 全文索引 |
| `/api/search/similar` | POST | 相似项目向量近邻（`source` / `repoId` / `topK` / `scope` / `minScore` / `excludeSaved`；返回未水合 hits） |
| `/api/duplicates/scan` | POST | 重复 / 相似项目检测（`scope` / `myRepoIds` / `maxRepos` / `maxClusters`；返回未水合簇，只读不落库） |
| `/api/search/status` | GET | 向量覆盖率、模型分布与最近向量化运行 |
| `/api/analysis/dependencies` | GET | 依赖分析聚合（`repoIds` 逗号分隔 / `top`；只读本地表） |
| `/api/analysis/dependencies/refresh` | POST | 扫描依赖清单并入库（`repoIds` / `force` / `limit`） |
| `/api/vectors/stats` | GET | 向量覆盖率与最近运行 |
| `/api/vectors/runs/{runId}` | GET | 向量化运行详情 |
| `/api/vectors/{source}/{repoId}` | GET | 单条仓库向量 |
| `/api/search/understand` | POST | 查询理解：同义词 / 技术栈词表扩展（`query` / `expand`） |
| `/api/recommend/eval` | POST | 推荐质量评估与阈值 / 权重调参建议（抽样评估集） |
| `/api/degradation/status` | GET | 降级路径自检（模型缺失 / 超预算） |
| `/api/push/bark/status` | GET | Bark 通道状态与待投递 / 已投递 / 失败计数 |
| `/api/push/bark/test` | POST | 同步发送 Bark 测试通知 |
| `/api/push/bark/dispatch` | POST | 入队 Bark 投递（`user_id` / `limit` 可选） |
| `/api/push/records` | GET | 统一推送记录（通道 / 状态 / 时间 / 关键字 + 分页） |
| `/api/push/records/stats` | GET | 投递统计（分通道 / 分状态 / 回执 / 送达率） |
| `/api/push/records/{id}` | GET | 投递详情 + 回执时间线 |
| `/api/push/receipts` | POST | 写入送达回执（服务商 / 人工，幂等） |
| `/api/monitoring/status` | GET | 实时监控快照（内存 / 磁盘 / 负载 / 日志 / 健康检查 / 活跃告警） |
| `/api/monitoring/check` | POST | 执行一次检查并落库（告警去重 / 自动恢复 / 历史记录） |
| `/api/monitoring/history` | GET | 最近检查历史（`?limit=`） |
| `/api/monitoring/alerts` | GET | 告警列表（`?status=` / `?limit=`） |
| `/api/monitoring/alerts/{id}/ack` | POST | 确认告警 |
| `/api/monitoring/logs` | GET | 日志目录统计与文件列表 |
| `/api/monitoring/logs/cleanup` | POST | 日志清理（`?retention_days=` / `?dry_run=`） || `/healthz` | GET | 健康检查 |
| `/healthz/ready` | GET | 就绪检查（数据库 / 运行目录，异常返回 503） |

### 4.3 vps → edge（Vectorize 内部接口，`X-Internal-Token`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/internal/vectors/upsert` | POST | 批量写入向量（1~1000 条/批） |
| `/api/internal/vectors/check` | POST | 按 ID 批量查询元数据（≤100 条/批） |
| `/api/internal/vectors/delete` | POST | 批量删除向量（≤1000 条/批） |
| `/api/internal/vectors/stats` | GET | 索引统计 |
| `/api/internal/vectors/list` | GET | 分页列出 ID（孤儿对账；不支持时返回 501） |
| `/api/internal/push-preferences` | GET | 读取全部推送偏好（VPS 推送任务使用；`?userId=` 可查单个） |

### 4.4 安全运维接口（M5-05）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/internal/security/status`（edge） | GET | 限流 / 登录防护 / 双令牌状态与指纹（`X-Internal-Token`） |
| `/api/internal/security/cleanup`（edge） | POST | 清理过期限流计数、30 天前登录失败与 90 天前安全事件（`X-Internal-Token`） |
| `/api/security/status`（vps） | GET | VPS 侧限流参数与双令牌状态（`X-Internal-Token`） |
| `/api/internal/analytics` | GET | Workers 请求指标聚合（`?days=1..30`，`X-Internal-Token`） |
## 5. 安全边界

- 浏览器侧仅持有 httpOnly 会话 Cookie（`of_session`），**不接触任何第三方 token**；
- GitHub access token 仅存在于 edge（换取用户信息后即弃）与 vps（同步任务使用，存服务端）；
- edge → vps 调用必须带 `X-Internal-Token`；vps 不直接对公网暴露业务接口；
- 内部令牌支持双令牌轮换：`INTERNAL_TOKEN`（当前）+ `INTERNAL_TOKEN_PREVIOUS`（过渡期），两端均接受两枚，验证通过后清空过渡位；
- 边缘接口按 auth / write / read 三类固定窗口限流；登录失败达到阈值后按 IP 锁定，身份只存 sha-256 哈希；
- 所有密钥通过平台 secrets 注入，仓库内只有 `.env.example` 占位符；任何接口都不回显令牌明文，只提供 12 位指纹；
- 响应头基线：edge 使用 `hono/secure-headers`，VPS 使用 `SecurityHeadersMiddleware`（nosniff / frame / referrer / permissions / COOP，认证路径 `Cache-Control: no-store`）；
- 安全审计：`deploy/scripts/security-audit.sh`（`vps/app/security_audit.py`）只读扫描密钥泄露、依赖完整性 / 漏洞、配置基线、Cookie / 响应头与隐私边界，`--strict` 可作为 CI 门禁；清单见 [security-audit.md](../guides/security-audit.md)。

## 6. 部署拓扑

| 组件 | 部署位置 | 说明 |
| --- | --- | --- |
| admin | Cloudflare Pages | `npm run build` 产物（`admin/dist`），SPA 回退 `_redirects` |
| edge | Cloudflare Workers | `wrangler deploy`；绑定 D1 / Vectorize |
| vps | 本地服务器 | uvicorn + celery worker + celery beat + redis + ollama |
| 数据 | D1 + VPS 本地 SQLite | D1 为主数据；VPS 侧为算力缓存/镜像 |

### 3.21 备份与恢复（M5-04）

```
Celery beat 03:50（每日）→ SQLite backup API 快照 → integrity_check → gzip + manifest
→ backups/sqlite/sqlite-*.sqlite3.gz + .json → 按份数 / 总量清理

cron 04:10（每日）→ deploy/scripts/backup-d1.sh → wrangler d1 export（远端 D1）
→ 临时 SQLite 导入校验（integrity / 表清单 / 行数）→ gzip + manifest
→ backups/d1/d1-*.sql.gz + .json

Celery beat 周日 04:20 → backup_drill → 快照恢复到临时库 → 完整性 / 表行数核对
→ 报告落日志；生产恢复仅允许 CLI（restore-sqlite.sh，默认拒绝覆盖）
```

D1 凭据只存在于部署控制面，VPS 不持有 Cloudflare 凭据；备份目录 700 / 文件 600，
保留最近 7 份、总量 3 GB（`resource-plan.md` §4）。详见
[backup-restore.md](../guides/backup-restore.md)。
