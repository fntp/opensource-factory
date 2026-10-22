# OpenFactory VPS 算力节点（`vps/`）

「开源项目工厂 / OpenFactory」的**本地算力节点**：运行在个人 VPS 上的 Python 服务，承担整个系统中所有重算力任务。

## 项目定位

- **边缘轻量、算力下沉**：Cloudflare 边缘（Pages 前端 + Workers/Hono API + D1 + Vectorize）只做鉴权、调度与元数据读写；一切耗时任务通过内部 API 交给本节点异步执行。
- **本地优先、隐私安全**：LLM 与向量化优先使用本地模型（Ollama / BGE-M3），云端 API（DeepSeek）仅作可选降级。
- **优雅降级**：LLM、重型模型、目标站点不可用时系统必须可用（降级返回，不抛错阻塞）。

本节点负责：GitHub 数据同步、热榜抓取（GitHub Trending / Gitee）、README 清洗与摘要、向量生成与语义推荐、每日推送准备。

## 目录结构

```
vps/
├── README.md
├── requirements.txt          # 轻量依赖（API + 任务队列，无需 GPU）
├── requirements-ml.txt       # 重量级可选依赖（torch / sentence-transformers / FlagEmbedding）
├── .env.example              # 环境变量模板（占位符，可直接提交）
├── app/
│   ├── main.py               # FastAPI 入口（uvicorn app.main:app）
│   ├── config.py             # pydantic-settings 配置
│   ├── db.py                 # SQLAlchemy engine / Session / init_db
│   ├── models.py             # 数据库模型（D1 表结构的本地镜像）
│   ├── schemas.py            # Pydantic 出入参模型
│   ├── services/             # 业务逻辑（单一职责，可独立单测）
│   │   ├── github_service.py     # GitHub REST v3 异步客户端（分页、README base64 解码）
│   │   ├── trending_crawler.py   # GitHub Trending 解析/抓取 + Gitee 探索页（尽力而为）
│   │   ├── readme.py             # README 清洗 + 技术栈启发式提取
│   │   ├── embedding.py          # BGE-M3（懒加载）与确定性 hash 降级向量
│   │   ├── vector_pipeline.py    # 收藏库 / 热榜向量化：批量、增量、断点续跑
│   │   ├── summarizer.py         # Ollama → DeepSeek → 截断降级 的摘要生成
│   │   ├── recommender.py        # 余弦排序 + 综合打分 + 中文推荐理由模板
│   │   ├── recommendation_service.py # 每日推荐：画像 / 去重已收藏 / 阈值 / 落库
│   │   ├── recommendation_eval.py # 每日评估：质量分 / 匹配度门槛 / 运行记录（M4-01）
│   │   ├── email_channel.py      # Email 摘要：SMTP 投递 / 幂等 / 送达记录（M4-05）

│   │   ├── bark.py               # Bark 推送通道：消息构建 / 投递 / 状态（M4-03）
│   │   └── vector_sync.py        # Vectorize 批量 upsert / 重试 / 对账 / 孤儿清理
│   ├── api/                  # HTTP 层（只做参数校验与编排）
│   │   ├── repos.py              # GET /api/repos、POST /api/repos/sync
│   │   ├── trending.py           # GET /api/trending、POST /api/trending/crawl
│   │   ├── recommend.py          # /api/recommend/*（查询 / 生成 / 评估 / 合格推荐）
│   │   ├── notifications.py      # /api/notifications/email/*（状态 / 测试邮件）

│   │   ├── push.py               # /api/push/bark/*（状态 / 测试 / 投递入队）
│   │   ├── vector_sync.py        # /api/vector-index/*（同步入队、状态、运行记录）
│   │   ├── vectors.py            # GET /api/vectors/stats、runs、单条向量
│   │   └── tasks.py              # /api/tasks/*（与边缘 Worker 的集成契约，X-Internal-Token 鉴权）
│   └── tasks/                # Celery 任务（薄封装，调用 services + 落库）
│       ├── celery_app.py         # Celery 应用与 beat 定时计划
│       └── jobs.py               # sync / crawl / generate / daily_push / vectorize / vector_index 任务
└── tests/                    # pytest（不访问网络）
```

## 运行方式

```bash
cd vps
python3 -m venv .venv
source .venv/bin/activate

# 1) 轻量依赖：API + Celery + 测试全部可用（无 torch）
pip install -r requirements.txt

# 2) 可选：真实向量模型（BGE-M3 等，需较大内存/磁盘）
# pip install -r requirements-ml.txt

# 3) 配置环境变量
cp .env.example .env && $EDITOR .env

# 4) 启动 API
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 5) 启动 Celery worker（异步任务）
celery -A app.tasks.celery_app worker -l info

# 6) 可选：启动 beat（定时抓取热榜 / 每日推送）
celery -A app.tasks.celery_app beat -l info

# 7) 测试（不访问网络）
pytest -q
```

> 未安装 `requirements-ml.txt` 时节点自动降级：向量走确定性 hash 兜底、摘要走截断降级，所有接口与任务仍可运行。

## 生产运行（systemd 基线）

本机部署不再手工 `nohup`，统一由 [`deploy/`](../deploy/README.md) 提供的基线托管：
运行目录 `/opt/openfactory`（`.env` / `data` / `logs` / `backups`）、Redis 配置与
`openfactory-api` / `-worker` / `-beat` / `-redis` 四个 systemd 单元。

```bash
deploy/scripts/bootstrap-runtime.sh          # 创建运行目录、渲染 .env 与 redis.conf
deploy/scripts/bootstrap-runtime.sh --install-units   # 安装 systemd 单元（root）
deploy/scripts/doctor.sh --services          # 基线自检
```

完整步骤与验收标准见 [docs/guides/deployment-baseline.md](../docs/guides/deployment-baseline.md)。

## 环境变量说明

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_DIR` | 空 | 非空时 API 写滚动日志（10MB × 5）到该目录 |
| `DATABASE_URL` | `sqlite:///./data/opensource_factory.db` | 本地镜像库（SQLite 起步，可换 PostgreSQL） |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker / result backend |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | 本地 Ollama 服务地址 |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Ollama 摘要模型 |
| `DEEPSEEK_API_KEY` | 空 | 可选；配置后作为 LLM 云端降级（OpenAI 兼容） |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | 向量模型名（sentence-transformers / FlagEmbedding） |
| `EDGE_BASE_URL` | 空 | edge Worker 地址；与 `INTERNAL_TOKEN` 同时配置后启用 Vectorize 同步 |
| `VECTORIZE_SYNC_ENABLED` | `true` | 是否启用 Vectorize 索引同步 |
| `VECTORIZE_INDEX_NAME` | `opensource-factory-vectors` | Cloudflare Vectorize 索引名（需与 edge 绑定一致） |
| `VECTORIZE_INDEX_DIM` | `1024` | 索引维度；与本地向量维度不一致的条目会标记 `dim_mismatch` 跳过 |
| `VECTORIZE_SYNC_BATCH_SIZE` | `100` | 单批 upsert 条数（上限 1000） |
| `VECTORIZE_SYNC_MAX_PER_RUN` | `1000` | 单次运行最多处理条数 |
| `VECTORIZE_SYNC_MAX_RETRIES` | `3` | 网络错误 / 429 / 5xx 的最大重试次数 |
| `VECTORIZE_SYNC_RETRY_BASE_MS` | `500` | 指数退避基数（毫秒） |
| `VECTORIZE_SYNC_TIMEOUT_SECONDS` | `30` | edge 请求超时 |
| `VECTORIZE_SYNC_DELETE_ORPHANS` | `false` | 对账时是否清理孤儿向量（确认索引独占后开启） |
| `VECTORIZE_SYNC_MAX_ORPHANS` | `100` | 单次最多删除的孤儿向量数 |
| `RECOMMEND_MIN_SCORE` | `0.30` | 推荐最终得分最低阈值（0~1） |
| `RECOMMEND_DAILY_TOP_K` | `20` | 每日任务每个用户最多生成的推荐数 |
| `RECOMMEND_CANDIDATE_LIMIT` | `500` | 单次参与打分的热榜候选上限 |
| `RECOMMEND_SIMILARITY_WEIGHT` | `0.8` | 相似度权重 |
| `RECOMMEND_TRENDING_WEIGHT` | `0.2` | 热榜热度权重 |
| `EVAL_MATCH_THRESHOLD` | `0.35` | 每日评估匹配度硬门槛（低于直接 `filtered`） |
| `EVAL_QUALITY_THRESHOLD` | `0.55` | 每日评估质量分门槛 |
| `EVAL_REPO_WEIGHT` | `0.7` | 质量分中仓库质量权重 |
| `EVAL_REASON_WEIGHT` | `0.3` | 质量分中理由质量权重 |
| `EMAIL_ENABLED` | `false` | Email 通道总开关；关闭时摘要任务与测试接口直接跳过 |
| `EMAIL_SMTP_HOST` | 空 | SMTP 服务商地址（如 `smtp.example.com`） |
| `EMAIL_SMTP_PORT` | `587` | SMTP 端口；465 通常配合 `EMAIL_SSL=true`、`EMAIL_STARTTLS=false` |
| `EMAIL_SMTP_USERNAME` | 空 | SMTP 认证用户名；留空表示匿名中继 |
| `EMAIL_SMTP_PASSWORD` | 空 | SMTP 密码（仅 `.env`，不落库 / 不回显） |
| `EMAIL_FROM` | 空 | 发件人地址（需与服务商允许的 From 一致） |
| `EMAIL_FROM_NAME` | `OpenFactory` | 发件人显示名 |
| `EMAIL_TO` | 空 | 默认收件人，逗号 / 分号分隔，最多 20 个 |
| `EMAIL_STARTTLS` | `true` | 是否对明文连接执行 STARTTLS（与 `EMAIL_SSL` 互斥） |
| `EMAIL_SSL` | `false` | 是否使用隐式 SSL（通常配 465 端口） |
| `EMAIL_TIMEOUT_SECONDS` | `15` | SMTP 连接 / 读写超时 |
| `EMAIL_MAX_RETRIES` | `2` | 瞬时网络错误重试次数（认证 / 收件人拒绝不重试） |
| `EMAIL_RETRY_BASE_SECONDS` | `0.5` | 重试指数退避基数 |
| `EMAIL_DAILY_LIMIT` | `10` | 单封摘要最多包含的推荐数 |
| `EMAIL_DIGEST_WINDOW_HOURS` | `24` | 摘要回溯窗口（小时） |
| `INTERNAL_TOKEN` | 空 | 设置后 `/api/tasks/*`、`/api/vector-index/*`、`/api/notifications/*` 必须携带 `X-Internal-Token`；为空表示本地开发不鉴权 |

| `BARK_ENABLED` | `false` | Bark 推送通道总开关 |
| `BARK_SERVER_URL` | `https://api.day.app` | Bark 服务地址（支持自建，自动拼接 `/push`） |
| `BARK_DEVICE_KEY` | 空 | Bark device key（密钥，仅存 `.env`，接口不回显） |
| `BARK_GROUP` | `OpenFactory` | 通知分组 |
| `BARK_SOUND` | 空 | 提示音（如 `minuet.caf`），空则用 Bark 默认 |
| `BARK_ICON` | 空 | 通知图标 URL |
| `BARK_LEVEL` | `active` | `active` / `timeSensitive` / `passive` / `critical` |
| `BARK_TIMEOUT_SECONDS` | `10` | 单次请求超时 |
| `BARK_MAX_PER_RUN` | `5` | 单次任务最多投递条数 |
| `BARK_DRY_RUN` | `false` | 试运行：只生成消息不发送、不写投递标记 |
| `INTERNAL_TOKEN` | 空 | 设置后 `/api/tasks/*`、`/api/vector-index/*` 必须携带 `X-Internal-Token`；为空表示本地开发不鉴权 |
| `EMBEDDING_FORCE_FALLBACK` | `0` | 置 `1` 强制使用确定性 hash 向量（CI / 2G 预算紧张时） |
| `VECTORIZE_BATCH_SIZE` | `32` | 向量化每批编码 / 提交条数（1~256） |
| `VECTORIZE_MAX_PER_RUN` | `1000` | 单次向量化默认上限 |
| `VECTORIZE_AUTO` | `1` | 同步 / 热榜抓取完成后自动入队增量向量化 |
| `INTERNAL_TOKEN` | 空 | 设置后 `/api/tasks/*` 必须携带 `X-Internal-Token`；为空表示本地开发不鉴权 |
| `CELERY_TASK_ALWAYS_EAGER` | `0` | 置 `1` 时任务同步执行（本地调试 / 测试用） |
| `GITHUB_TOKEN` | 空 | GitHub PAT（仅需 read 权限）；为空时同步任务跳过 |

完整清单见 `.env.example`。所有真实密钥只存在于本地 `.env`（git 忽略）或平台密钥托管，**不得提交**。

## 与 Cloudflare 边缘的接口约定

边缘 Worker 通过内部 API 调度本节点，全部任务接口位于 `/api/tasks/*`：

| 方法 | 路径 | 说明 | 返回 |
| --- | --- | --- | --- |
| POST | `/api/tasks/sync` | 入队 GitHub 仓库同步（自己的 + Starred） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/crawl-trending` | 入队热榜抓取（`platform=github\|gitee\|all`，可选 `language`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/generate-recommendations` | 入队推荐生成（可选 `user_id`、`top_k`、`min_score`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/evaluate-recommendations` | 入队每日评估（可选 `user_id`、`match_threshold`、`quality_threshold`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/daily-push` | 入队每日推送准备（仅将 `qualified` 推荐标记为 `pushed`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/send-email-digest` | 入队 Email 每日摘要（可选 `user_id`、`limit`、`force`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/vectorize` | 入队向量化（`scope=my\|trending\|all`，可选 `limit` / `batch_size` / `force` / `run_id`） | `202 {"taskId","runId"}` |
| GET | `/api/tasks/{task_id}` | 查询任务状态（`pending/started/success/failure`） | `200 {"taskId","status","result"}` |
| POST | `/api/vector-index/sync` | 入队 Vectorize 同步 / 对账（`kind=sync\|reconcile`、`scope=my\|trending\|all`、`force`、`limit`、`batchSize`） | `202 {"taskId": "..."}` |
| GET | `/api/vector-index/status` | 本地向量覆盖率、状态分布与最近运行 | `200 {...}` |
| GET | `/api/vector-index/runs?limit=20` | 最近同步运行记录 | `200 [...]` |
| GET | `/api/vector-index/runs/{run_id}` | 单次运行详情 | `200 {...}` |
| GET | `/api/notifications/email/status` | Email 通道开关、配置完整性与最近送达（收件人脱敏） | `200 {...}` |
| POST | `/api/notifications/email/test` | 发送测试邮件（`to` / `subject` / `body` 均可选） | `200 {...}`；未启用 / 未配置 `409` |

| GET | `/api/push/bark/status` | Bark 通道状态与待投递 / 已投递 / 失败计数 | `200 {...}` |
| POST | `/api/push/bark/test` | 同步发送 Bark 测试通知（需已配置） | `200 {"ok":true}` |
| POST | `/api/push/bark/dispatch` | 入队 Bark 投递（可选 `user_id` / `limit`） | `202 {"taskId":"..."}` |

Celery beat 每 30 分钟（`7,37` 分）自动执行一次增量同步；对账建议在低峰期手动触发。
| GET | `/api/vectors/stats` | 向量覆盖率与最近运行 | `200` |
| GET | `/api/vectors/runs?limit=20` | 最近向量化运行 | `200` |
| GET | `/api/vectors/runs/{runId}` | 单次运行详情（含游标 / 计数 / 错误） | `200` |
| GET | `/api/vectors/{source}/{repoId}` | 单条仓库向量（`source=my\|trending`） | `200` |

约定：

- **鉴权**：当服务端设置 `INTERNAL_TOKEN` 时，请求必须携带请求头 `X-Internal-Token: <token>`，否则返回 `401`；
- **异步语义**：任务接口一律 `202` + `{"taskId": ...}`（camelCase），由边缘侧轮询 `GET /api/tasks/{task_id}` 获取结果；
- **直接查询接口**（供边缘回源或调试）：`GET /api/repos`、`GET /api/trending`、`POST /api/recommend/query`、`GET /api/recommend/evaluations`、`GET /api/recommend/qualified`；
- **数据契约**：本地表结构与 D1 Schema 保持一致（`my_repositories` / `trending_repositories` / `categories` 字段名与语义镜像），边缘侧按 `id`（`owner/repo`）对齐；
- **降级语义**：外部依赖不可用时任务返回 `{"status": "skipped"|"error", ...}` 而不是失败抛错，边缘侧可安全重试。

## 向量化管线（M3-02）

`vector_pipeline` 把收藏库（`my_repositories`）与热榜（`trending_repositories`）的文本
编码为向量并持久化到本地 `repo_vectors`，供后续语义检索 / Vectorize 同步使用：

- **批量**：`batch_size` 条一批，逐批编码并提交，内存占用可控；
- **增量**：文本 SHA-256、模型名、编码后端三者一致时跳过；同步 / 抓取后自动入队；
- **limit 口径**：只限制待处理条数，已是最新向量的仓库只计入 `skipped`，不占单次预算；
- **断点续跑**：运行记录 `vectorization_runs` 保存 `source + repo_id` 游标，失败后用同一 `runId` 继续；
- **降级**：未安装 BGE-M3 依赖时自动使用 256 维确定性 hash 向量，测试与 CI 不依赖模型。

```bash
# 全量（收藏库 + 热榜）增量向量化，单次最多 500 条
curl -sS -X POST 'http://127.0.0.1:8000/api/tasks/vectorize?scope=all&limit=500' \
  -H 'X-Internal-Token: <token>'

# 强制重算收藏库
curl -sS -X POST 'http://127.0.0.1:8000/api/tasks/vectorize?scope=my&force=true' \
  -H 'X-Internal-Token: <token>'

# 失败后续跑（runId 来自入队响应或 GET /api/vectors/runs）
curl -sS -X POST 'http://127.0.0.1:8000/api/tasks/vectorize?run_id=<runId>' \
  -H 'X-Internal-Token: <token>'

# 查看覆盖率 / 运行状态
curl -sS 'http://127.0.0.1:8000/api/vectors/stats'
curl -sS 'http://127.0.0.1:8000/api/vectors/runs/<runId>'
```

> M3-01 完成模型选型后，只需调整 `EMBEDDING_MODEL`（必要时设置 `EMBEDDING_FORCE_FALLBACK=0`）；
> 模型 / 后端变化会在下一次运行时自动触发重算。Vectorize 索引同步由 M3-03 承接。

## 每日推荐生成（M3-05）

Celery beat 每天 08:30（Asia/Shanghai）执行 `generate_recommendations`，早于 09:00 的每日推送准备：

1. **画像**：按 star 取收藏库前 1000 条，优先复用 `repo_vectors(source='my')`，缺失时现场编码并回写；对有效向量求平均并 L2 归一化；
2. **候选**：热榜按 `stars_today` 降序取前 `RECOMMEND_CANDIDATE_LIMIT` 条，排除 `my_repositories` 已收藏的仓库；
3. **打分**：`score = 0.8 × 相似度 + 0.2 × 热度`，热度为 `log1p(stars_today)` 在候选集内归一化；
4. **阈值 / TopK**：过滤 `score < RECOMMEND_MIN_SCORE`，按得分降序取 `RECOMMEND_DAILY_TOP_K`；
5. **落库**：按 `(user_id, repo_id)` 更新已有推荐；旧 `new` 未入选或已收藏标记 `expired`；`saved` / `dismissed` / `pushed` 保留原状态。

```bash
# 手动触发（默认阈值 0.30、top_k 20）
curl -sS -X POST 'http://127.0.0.1:8000/api/tasks/generate-recommendations' \
  -H 'X-Internal-Token: <token>'

# 指定用户 / 阈值 / 数量
curl -sS -X POST 'http://127.0.0.1:8000/api/tasks/generate-recommendations?user_id=default&top_k=10&min_score=0.5' \
  -H 'X-Internal-Token: <token>'
```

任务返回 `created / updated / expired / selected / candidates / excludedCollected / belowThreshold` 等计数，便于 M3-08 调参。

## 每日推荐评估（M4-01）

Celery beat 每天 08:45 执行 `evaluate_recommendations`，在生成（08:30）与推送准备（09:00）之间：

1. **范围**：`status in (new, qualified, filtered)` 的推荐；`saved` / `dismissed` / `pushed` 不覆盖；
2. **质量分**：`quality_score = 仓库质量 × 0.7 + 理由质量 × 0.3`，仓库质量看简介 / 技术栈 / 今日 Star / README 摘要 / 语言，理由质量看长度与依据关键词；
3. **双重门槛**：`match_score ≥ EVAL_MATCH_THRESHOLD` 且 `quality_score ≥ EVAL_QUALITY_THRESHOLD`；历史数据无 `match_score` 时回退到综合 `score`；
4. **结果**：通过 → `qualified`，未通过 → `filtered`，缺失热榜仓库 → `skipped`；同时写 `recommendation_evaluation_runs` 运行统计与 `quality_detail` 明细；
5. **幂等**：重复运行会按当前阈值重算同一批推荐，可用于调参后回补。

```bash
# 手动触发全量评估
curl -sS -X POST 'http://127.0.0.1:8000/api/tasks/evaluate-recommendations' \
  -H 'X-Internal-Token: <token>'

# 指定用户 / 自定义门槛
curl -sS -X POST 'http://127.0.0.1:8000/api/tasks/evaluate-recommendations?user_id=default&match_threshold=0.4&quality_threshold=0.6' \
  -H 'X-Internal-Token: <token>'

# 查询运行记录 / 合格推荐
curl -sS 'http://127.0.0.1:8000/api/recommend/evaluations?limit=10'
curl -sS 'http://127.0.0.1:8000/api/recommend/qualified?user_id=default'
```

## Email 通道（M4-05）

Celery beat 每天 09:10 执行 `send_email_digest`，在 09:00 推送准备之后读取
`recommendations.status='pushed'` 的推荐（默认回溯 24 小时，最多 `EMAIL_DAILY_LIMIT` 条），
渲染中文摘要并通过 SMTP 投递：

1. **配置**：`.env` 设置 `EMAIL_ENABLED=true`、`EMAIL_SMTP_HOST`、`EMAIL_FROM`、`EMAIL_TO`；
   587 端口用 STARTTLS（默认），465 端口配 `EMAIL_SSL=true` + `EMAIL_STARTTLS=false`；
2. **幂等**：按「日期 + 收件人」生成 `dedupe_key`，同日已成功发送则跳过；`force=true` 可补发；
3. **送达记录**：每次摘要 / 测试邮件写 `email_deliveries`（收件人、状态、条数、Message-ID、脱敏错误）；
4. **降级**：未启用 → `disabled`，配置不全 → `not_configured`，无推荐 → `empty`，SMTP 失败 → `failed`；
5. **安全**：SMTP 密码只从环境变量读取，错误信息与状态接口均不回显密码 / 完整收件人。

```bash
# 查看通道状态（收件人 / 发件人脱敏）
curl -sS 'http://127.0.0.1:8000/api/notifications/email/status' \
  -H 'X-Internal-Token: <token>'

# 发送测试邮件（不填 to 时使用 EMAIL_TO）
curl -sS -X POST 'http://127.0.0.1:8000/api/notifications/email/test' \
  -H 'Content-Type: application/json' \
  -H 'X-Internal-Token: <token>' \
  -d '{"to":"you@example.com"}'

# 手动触发摘要（force=true 忽略当日幂等）
curl -sS -X POST 'http://127.0.0.1:8000/api/tasks/send-email-digest?force=true' \
  -H 'X-Internal-Token: <token>'
```


## Bark 推送通道（M4-03）

Celery beat 每天 09:05 执行 `send_bark_notifications`，把 09:00 推送准备产生的
`pushed` 推荐推送到 iOS Bark；与 M4-02 站内通知中心消费同一批推荐，互不阻塞：

1. **范围**：`status='pushed'` 且 `bark_sent_at IS NULL` 的推荐，按质量分 / 综合分降序取前 `BARK_MAX_PER_RUN` 条；
2. **消息**：标题为 `owner/name`；正文依次为项目简介、推荐理由、匹配度 / 语言 / 今日 Star；`url` 指向 GitHub；
3. **幂等**：成功后写 `bark_sent_at` 并清空 `bark_error`；失败写 `bark_error`（截断 300 字符），保留待下次重试；
4. **降级**：`BARK_ENABLED=false` 或 `BARK_DEVICE_KEY` 为空时任务直接 `skipped`；网络 / Bark 返回异常只记失败，不抛错；
5. **dry-run**：`BARK_DRY_RUN=true` 时只返回消息预览，不发送、不写投递标记，便于先核对文案。

```bash
# 查看通道状态（不返回 device key）
curl -sS 'http://127.0.0.1:8000/api/push/bark/status'

# 发送测试通知（需在 .env 配置 BARK_ENABLED=true / BARK_DEVICE_KEY）
curl -sS -X POST 'http://127.0.0.1:8000/api/push/bark/test' \
  -H 'Content-Type: application/json' \
  -H 'X-Internal-Token: <token>' \
  -d '{"title":"OpenFactory 测试","body":"Bark 通道已联通"}'

# 手动触发投递（可选 user_id / limit）
curl -sS -X POST 'http://127.0.0.1:8000/api/push/bark/dispatch?limit=5' \
  -H 'X-Internal-Token: <token>'
```

排障：

- `status.configured=false`：检查 `BARK_DEVICE_KEY` 是否写入运行目录 `.env` 并重启 API / worker / beat；
- `status.failed > 0` 且 `lastError` 为 `HTTP 401/403`：device key 失效或被服务端拒绝；
- `lastError` 为 `请求失败：ConnectError`：VPS 到 Bark 服务网络不通（自建服务检查地址 / 防火墙）；
- 重复收到同一条推送：确认 `bark_sent_at` 是否成功落库（SQLite 文件可写），极端崩溃窗口可能重复一次。

## 常用检查

```bash
cd vps
.venv/bin/pytest -q
.venv/bin/python -c "from app.main import app; print('app ok')"
```
