# OpenFactory VPS 算力节点（`vps/`）

「开源项目工厂 / OpenFactory」的**本地算力节点**：运行在个人 VPS 上的 Python 服务，承担整个系统中所有重算力任务。

## 项目定位

- **边缘轻量、算力下沉**：Cloudflare 边缘（Pages 前端 + Workers/Hono API + D1 + Vectorize）只做鉴权、调度与元数据读写；一切耗时任务通过内部 API 交给本节点异步执行。
- **本地优先、隐私安全**：LLM 与向量化优先使用本地模型（Ollama / BGE-M3），云端 API（DeepSeek）仅作可选降级。
- **优雅降级**：LLM、重型模型、目标站点不可用时系统必须可用（降级返回，不抛错阻塞）。

本节点负责：GitHub 数据同步、热榜抓取（GitHub Trending / Gitee）、README 清洗与摘要、向量生成与语义推荐、每日推送准备。

README 清洗（`app/services/readme.py`）会去除 HTML 注释 / 脚本块 / 徽章 / 图片 / HTML 标签与链接地址，解码 HTML 实体并折叠空行；技术栈提取支持别名归并（Golang → Go、K8s → Kubernetes）、语言字段优先与 topics 提示。

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
│   ├── degradation.py        # 降级路径自检 CLI（python -m app.degradation check）
│   ├── services/             # 业务逻辑（单一职责，可独立单测）
│   │   ├── github_service.py     # GitHub REST v3 异步客户端（分页、README base64 解码）
│   │   ├── trending_crawler.py   # GitHub Trending 解析/抓取 + Gitee 探索页（尽力而为）
│   │   ├── trending_snapshot.py  # 按日快照去重 / 排名 / 趋势字段 + D1 批量回写
│   │   ├── crawl_guard.py        # 抓取重试、页面结构变更判定与告警落库（M2-02）
│   │   ├── trending_retention.py # 热榜保留窗口 / gzip JSONL 归档 / 本地与 D1 清理
│   │   ├── readme.py             # README 去噪（徽章 / 图片 / HTML）+ 技术栈别名归并
│   │   ├── embedding.py          # BGE-M3（懒加载）与确定性 hash 降级向量
│   │   ├── vector_pipeline.py    # 收藏库 / 热榜向量化：批量、增量、断点续跑
│   │   ├── summarizer.py         # Ollama → DeepSeek → 截断降级 的摘要生成
│   │   ├── recommender.py        # 余弦排序 + 综合打分
│   │   ├── recommend_reason.py   # 中文推荐理由 + based_on 依据字段（纯规则）
│   │   ├── recommendation_service.py # 每日推荐：画像 / 去重已收藏 / 阈值 / 落库
│   │   ├── recommendation_feedback.py # 推荐反馈：edge 拉取 / 回写 / 本地降级
│   │   ├── recommendation_quality.py # 质量评估：抽样评估集 / 指标 / 阈值调优（M3-08）
│   │   ├── recommendation_eval.py # 每日评估：质量分 / 匹配度门槛 / 运行记录（M4-01）
│   │   ├── bark.py               # Bark 推送通道：消息构建 / 投递 / 状态（M4-03）
│   │   ├── telegram.py           # Telegram 摘要：HTML / 分片 / 重试 / 送达记录（M4-04）
│   │   ├── email_channel.py      # Email 摘要：SMTP 投递 / 幂等 / 送达记录（M4-05）
│   │   ├── push_policy.py        # 推送去重 / 静默 / 每日上限 / 事件账本（M4-07）
│   │   ├── push_records.py       # 统一推送记录 / 回执流水 / 统计（M4-08）
│   │   ├── vector_index.py       # Vectorize 批量 upsert / 重试 / 对账 / 孤儿清理
│   │   ├── query_understanding.py # 同义词 / 技术栈词表查询理解（离线、确定性）
│   │   ├── semantic_search.py    # 查询向量化 + repo_vectors 余弦检索 + 结果水合
│   │   └── degradation.py        # 降级路径自检（模型缺失 / 超预算，离线可跑）
│   ├── api/                  # HTTP 层（只做参数校验与编排）
│   │   ├── repos.py              # GET /api/repos、POST /api/repos/sync
│   │   ├── trending.py           # GET /api/trending、/snapshots、/dates、/history、/retention、POST /crawl、/retention/cleanup
│   │   ├── recommend.py          # /api/recommend/*（查询 / 列表 / 生成 / 质量评估 / 每日评估 / 合格推荐）
│   │   ├── push.py               # /api/push/bark/*（状态 / 测试 / 投递入队）、/api/push/records/*、/api/push/receipts
│   │   ├── notifications.py      # /api/notifications/telegram/*、/api/notifications/email/*（状态 / 测试）
│   │   ├── push_policy.py        # /api/push/policy/*（状态 / 预演 / 事件）
│   │   ├── vector_index.py       # /api/vector-index/*（同步入队、对账、状态、运行记录）
│   │   ├── vectors.py            # GET /api/vectors/stats、runs、单条向量
│   │   ├── search.py             # /api/search/*（understand / embed / query / semantic / status）
│   │   ├── degradation.py        # GET /api/degradation/status（降级自检）
│   │   └── tasks.py              # /api/tasks/*（与边缘 Worker 的集成契约，X-Internal-Token 鉴权）
│   └── tasks/                # Celery 任务（薄封装，调用 services + 落库）
│       ├── celery_app.py         # Celery 应用与 beat 定时计划
│       └── jobs.py               # sync / crawl / generate / daily_push / bark / telegram / vectorize / vector_index / cleanup_trending_data 任务
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
| `OLLAMA_MODEL` | `qwen2.5:1.5b-instruct-q4_K_M` | Ollama 摘要模型（≤2B 量化，M3-01 选型） |
| `OLLAMA_KEEP_ALIVE` | `2m` | 模型空闲卸载时间，控制 2G 推理预算 |
| `DEEPSEEK_API_KEY` | 空 | 可选；配置后作为 LLM 云端降级（OpenAI 兼容） |
| `SUMMARY_BATCH_SIZE` | `10` | 摘要任务每批提交条数 |
| `SUMMARY_MAX_PER_RUN` | `200` | 单次摘要任务最多处理条数 |
| `SUMMARY_DELAY_MS` | `500` | 每条摘要之间的间隔（毫秒），给 Ollama 留出余量 |
| `SUMMARY_MAX_CHARS` | `800` | 摘要最大字符数 |
| `SUMMARY_SAMPLE_RATE` | `0.1` | 摘要抽检比例（按批次 + 仓库确定性抽样） |
| `SUMMARY_SAMPLE_MAX_PER_RUN` | `50` | 单次任务最多留存样本数 |
| `SUMMARY_SAMPLE_ALWAYS_BELOW` | `60` | 质量分低于该值时强制留存样本 |
| `SUMMARY_QUALITY_PASS_SCORE` | `70` | 质量判定通过分数线 |
| `SUMMARY_QUALITY_MIN_CHARS` | `40` | 摘要长度检查下限 |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | 向量模型名（sentence-transformers / FlagEmbedding） |
| `EMBEDDING_QUANTIZATION` | `int8` | 向量模型量化口径；`fp16` 约 2.3G 超预算，仅按需启用 |
| `EMBEDDING_DEVICE` | `cpu` | 向量模型运行设备（`cpu` / `cuda`） |
| `EMBEDDING_FORCE_FALLBACK` | `0` | 置 `1` 强制使用确定性 hash 向量（CI / 2G 预算紧张时） |
| `MODEL_BUDGET_MB` | `2048` | AI 推理峰值驻留上限（MB），同一时刻仅加载 1 个模型 |
| `VECTORIZE_BATCH_SIZE` | `32` | 向量化每批编码 / 提交条数（1~256） |
| `VECTORIZE_MAX_PER_RUN` | `1000` | 单次向量化默认上限 |
| `VECTORIZE_AUTO` | `1` | 同步 / 热榜抓取完成后自动入队增量向量化 |
| `RECOMMEND_MIN_SCORE` | `0.30` | 推荐最终得分最低阈值（0~1） |
| `RECOMMEND_DAILY_TOP_K` | `20` | 每日任务每个用户最多生成的推荐数 |
| `RECOMMEND_CANDIDATE_LIMIT` | `500` | 单次参与打分的热榜候选上限 |
| `RECOMMEND_SIMILARITY_WEIGHT` | `0.8` | 相似度权重 |
| `RECOMMEND_TRENDING_WEIGHT` | `0.2` | 热榜热度权重 |
| `EDGE_BASE_URL` | 空 | 边缘 API 地址；配置后摘要任务与热榜快照批量回写 D1，同时作为 Vectorize 同步目标 |
| `VECTORIZE_SYNC_ENABLED` | `true` | Vectorize 同步总开关；`false` 时同步任务直接返回 `disabled` |
| `VECTORIZE_INDEX_NAME` | `opensource-factory-vectors` | 索引名（仅用于状态展示，实际绑定在 edge `wrangler.toml`） |
| `VECTORIZE_INDEX_DIM` | `1024` | 索引维度校验；`0` 表示不校验 |
| `VECTORIZE_SYNC_BATCH_SIZE` | `100` | 单批 upsert 条数（上限 1000） |
| `VECTORIZE_SYNC_MAX_PER_RUN` | `1000` | 单次运行最多处理的向量数 |
| `VECTORIZE_SYNC_MAX_RETRIES` | `3` | 单批失败重试次数（指数退避） |
| `VECTORIZE_SYNC_RETRY_BASE_MS` | `500` | 退避基数（毫秒） |
| `VECTORIZE_SYNC_TIMEOUT_SECONDS` | `30` | 调用 edge 的超时（秒） |
| `VECTORIZE_SYNC_DELETE_ORPHANS` | `false` | 对账时是否删除索引中本地已不存在的向量 |
| `VECTORIZE_SYNC_MAX_ORPHANS` | `100` | 单次对账最多清理的孤儿数 |
| `RECOMMEND_EVAL_SAMPLE_SIZE` | `5` | 推荐评估默认折叠数 |
| `RECOMMEND_EVAL_HOLDOUT_RATIO` | `0.2` | 每个折叠留出的正样本比例 |
| `RECOMMEND_EVAL_TOP_K` | `10` | 评估用 top_k |
| `RECOMMEND_EVAL_NEGATIVES_PER_POSITIVE` | `5` | 每个正样本配的负样本数 |
| `RECOMMEND_EVAL_SEED` | `42` | 抽样随机种子（同种子结果可复现） |
| `RECOMMEND_EVAL_MIN_SCORE_GRID` | `0.1,0.2,0.3,0.4,0.5` | min_score 扫描网格 |
| `RECOMMEND_EVAL_WEIGHT_GRID` | `0.6,0.8,1.0` | 相似度权重扫描网格（热榜权重 = 1 - w） |
| `SEARCH_DEFAULT_TOP_K` | `10` | 语义搜索默认返回条数 |
| `SEARCH_MAX_TOP_K` | `50` | 语义搜索单次最大返回条数 |
| `SEARCH_MIN_SCORE` | `0.0` | 最低余弦相似度（0 表示不过滤） |
| `SEARCH_MAX_VECTORS` | `50000` | 本地全量余弦扫描上限，超过后依赖 Vectorize |
| `SEARCH_QUERY_EXPANSION_ENABLED` | `true` | 是否启用查询理解（同义词 / 技术栈词表扩展） |
| `SEARCH_QUERY_EXPANSION_MAX_TERMS` | `12` | 单次查询最多扩展词数（1~50） |
| `EVAL_MATCH_THRESHOLD` | `0.35` | 每日评估匹配度硬门槛（低于直接 `filtered`） |
| `EVAL_QUALITY_THRESHOLD` | `0.55` | 每日评估质量分门槛 |
| `EVAL_REPO_WEIGHT` | `0.7` | 质量分中仓库质量权重 |
| `EVAL_REASON_WEIGHT` | `0.3` | 质量分中理由质量权重 |
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
| `TELEGRAM_ENABLED` | `false` | Telegram 通道总开关；关闭时任务直接跳过 |
| `TELEGRAM_BOT_TOKEN` | 空 | BotFather 颁发的 Bot Token（机密，仅存本机 `.env`） |
| `TELEGRAM_CHAT_ID` | 空 | 接收推送的私聊 / 群组 id（群组为负数） |
| `TELEGRAM_API_BASE` | `https://api.telegram.org` | Bot API 地址（可指向自建反代） |
| `TELEGRAM_TIMEOUT_SECONDS` | `10` | 单次 HTTP 超时 |
| `TELEGRAM_MAX_RETRIES` | `3` | 网络 / 429 / 5xx 最大重试次数 |
| `TELEGRAM_RETRY_BASE_SECONDS` | `0.5` | 指数退避基数（429 优先用 `retry_after`） |
| `TELEGRAM_DAILY_LIMIT` | `10` | 单条摘要最多包含的推荐数 |
| `TELEGRAM_DIGEST_WINDOW_HOURS` | `24` | 摘要只取最近 N 小时进入 `pushed` 的推荐 |
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
| `EMBEDDING_FORCE_FALLBACK` | `0` | 置 `1` 强制使用确定性 hash 向量（CI / 2G 预算紧张时） |
| `VECTORIZE_BATCH_SIZE` | `32` | 向量化每批编码 / 提交条数（1~256） |
| `VECTORIZE_MAX_PER_RUN` | `1000` | 单次向量化默认上限 |
| `VECTORIZE_AUTO` | `1` | 同步 / 热榜抓取完成后自动入队增量向量化 |
| `INTERNAL_TOKEN` | 空 | 设置后 `/api/tasks/*`、`/api/push/*`、`/api/notifications/*`、`/api/vector-index/*`、`/api/search/*` 必须携带 `X-Internal-Token`；为空表示本地开发不鉴权 |
| `CELERY_TASK_ALWAYS_EAGER` | `0` | 置 `1` 时任务同步执行（本地调试 / 测试用） |
| `GITHUB_TOKEN` | 空 | GitHub PAT（仅需 read 权限）；为空时同步任务跳过 |
| `TRENDING_LANGUAGES` | `python,javascript,typescript,go,rust,java,cpp,c,php,ruby,swift,kotlin` | 每日抓取的 Trending 语言页（逗号分隔；留空只抓全局页） |
| `TRENDING_CRAWL_HOUR` | `3` | 每日抓取小时（Asia/Shanghai，0–23） |
| `TRENDING_CRAWL_MINUTE` | `27` | 每日抓取分钟（0–59） |
| `TRENDING_RETRY_MAX` | `3` | 单页抓取最大尝试次数（仅超时 / 429 / 5xx 重试） |
| `TRENDING_RETRY_BASE_DELAY` | `1.0` | 指数退避基数（秒） |
| `TRENDING_RETRY_MAX_DELAY` | `8.0` | 单次重试等待上限（秒） |
| `TRENDING_COUNT_DROP_RATIO` | `0.3` | 条数低于上次成功的比例时判定「骤降」 |
| `TRENDING_COUNT_DROP_MIN_BASELINE` | `5` | 基线少于该条数不做骤降判定 |
| `TRENDING_ALERT_COOLDOWN_MINUTES` | `360` | 同页同类告警去重窗口（分钟） |
| `TRENDING_ALERT_WEBHOOK_URL` | 空 | 可选告警 webhook；留空只落库 + 日志 |
| `TRENDING_RETENTION_DAYS` | `90` | 快照保留天数（含当天）；`0` = 暂停自动清理 |
| `TRENDING_ARCHIVE_ENABLED` | `true` | 清理前归档为 gzip JSONL；关闭后直接删除（不推荐） |
| `TRENDING_ARCHIVE_DIR` | `./data/archives` | 归档目录（相对路径按 `vps/` 解析） |
| `TRENDING_ARCHIVE_KEEP_DAYS` | `365` | 归档文件保留天数；`0` = 永久保留 |
| `TRENDING_RETENTION_HOUR` / `TRENDING_RETENTION_MINUTE` | `4` / `17` | 每日清理时刻（Asia/Shanghai） |

完整清单见 `.env.example`。所有真实密钥只存在于本地 `.env`（git 忽略）或平台密钥托管，**不得提交**。

## 模型选型与 2G 预算（M3-01）

| 用途 | 默认模型 | 量化 | 估算驻留 | 说明 |
| --- | --- | --- | --- | --- |
| Embedding | `BAAI/bge-m3` | int8 | ~1.1 GB | 1024 维；fp16 约 2.3G，超预算 |
| LLM 摘要 | `qwen2.5:1.5b-instruct-q4_K_M` | q4_K_M | ~1.3 GB | ≤2B，替代旧默认 `qwen2.5:7b`（~4.7G） |
| 降级 Embedding | `BAAI/bge-small-zh-v1.5` | fp32 | ~0.3 GB | 模型缺失 / 超预算时切换 |

同一时刻仅加载 1 个模型（摘要与向量化分队列串行），因此约束的是**峰值驻留**，不是两者之和。
准备模型：

```bash
ollama pull qwen2.5:1.5b-instruct-q4_K_M
pip install -r requirements-ml.txt   # BGE-M3 真实向量（未安装时 hash 兜底）
```

校验命令（离线即可运行；`--probe` 额外读取本机 Ollama `/api/ps`）：

```bash
cd vps
.venv/bin/python -m app.model_budget check
.venv/bin/python -m app.model_budget check --probe --json
```

预算内退出码 0；超预算或未收录模型退出码 1。`deploy/scripts/doctor.sh` 也会执行同一项检查。
int8 量化在 `sentence-transformers` 后端下对 Linear 层做动态量化；生产更推荐预量化的 ONNX int8 权重。

## 降级路径自检（M3-09）

模型缺失或超预算时，节点必须继续可用：

| 场景 | 降级行为 |
| --- | --- |
| 未安装 `sentence-transformers` / `FlagEmbedding`，或模型加载失败 | `EmbeddingService` 使用确定性 hash 向量（256 维、L2 归一化） |
| embedding 模型估算驻留 > `MODEL_BUDGET_MB` | 不加载模型，直接使用 hash 向量（`degraded_reason=over_budget`） |
| Ollama 未配置 / 请求失败 / 模型超预算 | 继续尝试 DeepSeek；仍不可用则返回截断原文（带「LLM 暂不可用」说明） |

自检命令不加载真实模型、不访问网络，全部 PASS 退出码 0：

```bash
cd vps
.venv/bin/python -m app.degradation check
.venv/bin/python -m app.degradation check --json
```

部署后也可调用 `GET /api/degradation/status`（配置 `INTERNAL_TOKEN` 时需携带 `X-Internal-Token`）
核对当前配置的预期后端与五项自检结果。

## M3 端到端验收（M3-11）

`scripts/m3_acceptance.py` 覆盖 M3-01~M3-10 的跨分支链路：真实 HTTP + 临时 SQLite +
mock edge（Vectorize / 推荐反馈契约）+ Celery eager 模式，不加载真实模型、不访问外网：

```bash
cd vps
.venv/bin/python scripts/m3_acceptance.py --strict \
  --report-md ../docs/planning/acceptance-m3-report.md \
  --report-json ../docs/planning/acceptance-m3-report.json
```

退出码 0 表示全部 PASS；`--strict` 下任何 GAP / FAIL / SKIP 均返回非 0。结论与回顾见
[docs/planning/acceptance-m3.md](../docs/planning/acceptance-m3.md)。

## 与 Cloudflare 边缘的接口约定

边缘 Worker 通过内部 API 调度本节点，任务接口位于 `/api/tasks/*`；热榜保留策略接口位于 `/api/trending/retention*`：

| 方法 | 路径 | 说明 | 返回 |
| --- | --- | --- | --- |
| POST | `/api/tasks/sync` | 入队 GitHub 仓库同步（自己的 + Starred，`with_summary=1` 时完成后自动排队摘要） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/summarize` | 入队 README 摘要批量生成（可选 `repo_id` 重复传、`limit`、`batch_size`、`force`、`max_chars`、`source=my\|trending\|all`） | `202 {"taskId": "..."}` |
| POST | `/api/trending/summarize` | 入队热榜摘要生成（等价 `source=trending`，可选 `repo_id`、`limit`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/crawl-trending` | 入队热榜抓取（`platform=github\|gitee\|all`；可选 `language` 单页、`languages` 多页 CSV、`since=daily\|weekly\|monthly`、`with_summary`、`summary_limit`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/generate-recommendations` | 入队推荐生成（可选 `user_id`、`top_k`、`min_score`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/regenerate-recommendation-reasons` | 入队重算存量推荐理由与 `based_on`（可选 `user_id`、`limit`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/evaluate-recommendations` | 入队每日评估（可选 `user_id`、`match_threshold`、`quality_threshold`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/daily-push` | 入队每日推送准备（按用户偏好 + M4-07 策略筛选 `qualified`；可选 `user_id` / `respect_schedule`） | `202 {"taskId": "..."}` |
| GET | `/api/push/policy/status` | 推送策略状态（静默 / 限额 / 今日计数 / 最近事件） | `200 {...}` |
| POST | `/api/push/policy/check` | 单条推送发送前预演（不写库） | `200 {...}` |
| GET | `/api/push/policy/events` | 查询推送事件（按用户 / 通道 / 状态） | `200 {...}` |
| POST | `/api/push/policy/events` | 记录通道投递事件（幂等） | `200 {...}` |
| POST | `/api/tasks/send-telegram-digest` | 入队 Telegram 每日摘要（可选 `user_id` / `limit` / `force`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/send-email-digest` | 入队 Email 每日摘要（可选 `user_id`、`limit`、`force`） | `202 {"taskId": "..."}` |
| GET | `/api/notifications/telegram/status` | Telegram 通道开关 / 配置状态 / 最近送达（chat id 脱敏） | `200 {...}` |
| POST | `/api/notifications/telegram/test` | 同步发送一条 Telegram 测试消息（`{"text": "..."}` 可选） | `200 {...}` / `409` / `502` |
| GET | `/api/notifications/email/status` | Email 通道开关、配置完整性与最近送达（收件人脱敏） | `200 {...}` |
| POST | `/api/notifications/email/test` | 发送测试邮件（`to` / `subject` / `body` 均可选） | `200 {...}`；未启用 / 未配置 `409` |
| GET | `/api/tasks/{task_id}` | 查询任务状态（`pending/started/progress/success/failure`，PROGRESS 时带 `progress`） | `200 {"taskId","status","result","progress"}` |
| POST | `/api/tasks/vectorize` | 入队向量化（`scope=my\|trending\|all`，可选 `limit` / `batch_size` / `force` / `run_id`） | `202 {"taskId","runId"}` |
| GET | `/api/trending/{owner}/{repo}` | 热榜详情（摘要 + 元信息；摘要回退 readme_summary → description → tech_stack） | `200 TrendingRepoDetail` / `404` |
| GET | `/api/trending/retention` | 热榜保留策略状态（窗口 / 过期数 / SQLite 与归档占用） | `200 {...}` |
| POST | `/api/trending/retention/cleanup` | 入队热榜归档与清理（`dryRun` / `retentionDays` / `archive`） | `202 {"taskId": "..."}` |
| POST | `/api/vector-index/sync` | 入队 Vectorize 同步（`mode=incremental\|full`、`scope=my\|trending\|all`、`limit`、`batchSize`） | `202 {"taskId","runId"}` |
| POST | `/api/vector-index/reconcile` | 入队对账（`scope`、`repair`、`limit`；默认只检查不修复） | `202 {"taskId"}` |
| GET | `/api/vector-index/status` | 本地向量覆盖率、状态分布与最近运行 | `200 {...}` |
| GET | `/api/vector-index/runs?limit=20` | 最近同步运行记录 | `200 [...]` |
| GET | `/api/vector-index/runs/{run_id}` | 单次运行详情 | `200 {...}` |
| GET | `/api/push/bark/status` | Bark 通道状态与待投递 / 已投递 / 失败计数 | `200 {...}` |
| POST | `/api/push/bark/test` | 同步发送 Bark 测试通知（需已配置） | `200 {"ok":true}` |
| POST | `/api/push/bark/dispatch` | 入队 Bark 投递（可选 `user_id` / `limit`） | `202 {"taskId":"..."}` |
| GET | `/api/push/records` | 统一推送记录（`channel` / `status` / `kind` / `user_id` / `q` / 时间 + 分页） | `200 {...}` |
| GET | `/api/push/records/stats` | 投递统计（分通道 / 分状态 / 回执 / 送达率） | `200 {...}` |
| GET | `/api/push/records/{id}` | 投递详情 + 回执时间线 | `200 {...}` / `404` |
| POST | `/api/push/receipts` | 写入送达回执（`deliveryId` / `status` / `source` / `externalId`） | `200 {...}` / `400` / `404` |

Celery beat 每日 04:37 自动增量同步、05:17 自动对账；也可通过上述接口手动触发。
| GET | `/api/vectors/stats` | 向量覆盖率与最近运行 | `200` |
| GET | `/api/vectors/runs?limit=20` | 最近向量化运行 | `200` |
| GET | `/api/vectors/runs/{runId}` | 单次运行详情（含游标 / 计数 / 错误） | `200` |
| GET | `/api/vectors/{source}/{repoId}` | 单条仓库向量（`source=my\|trending`） | `200` |
| POST | `/api/search/understand` | 查询理解（`{query,expand?}`） | `200 {query,rewritten,expanded,techStack,concepts,terms,keywordTerms,maxTerms}` |
| POST | `/api/search/embed` | 查询理解 + 查询向量化（`{query,expand?}`） | `200 {vector,dim,model,backend,understanding}` |
| POST | `/api/search/query` | 本地向量余弦检索（`{query,topK,scope,minScore,expand?}`） | `200 {items:[{source,repoId,score}],understanding,...}` |
| POST | `/api/search/semantic` | 本地检索并水合完整项目信息 | `200 {items:[...],understanding}` |
| GET | `/api/search/status` | 向量覆盖率、模型分布、最近运行与词表规模 | `200 {...}` |
| POST | `/api/recommend/eval` | 推荐质量评估与调参（`sampleSize` / `topK` / `holdoutRatio` / `negativesPerPositive` / `seed` / `userId`） | `200 {status,metrics,thresholds,weights,recommended,...}` |

Vectorize 索引维护接口（同样使用 `X-Internal-Token`）：

| 方法 | 路径 | 说明 | 返回 |
| --- | --- | --- | --- |
| POST | `/api/vector-index/sync` | 入队增量 / 全量同步（`mode`、`scope`、`limit`、`batchSize`） | `202 {"taskId","runId"}` |
| POST | `/api/vector-index/reconcile` | 对账（`scope`、`repair`、`limit`），同步执行 | `200` 运行统计 |
| GET | `/api/vector-index/status` | 本地向量数、状态分布、最近运行 | `200` |
| GET | `/api/vector-index/runs?limit=20` | 最近运行列表 | `200 {"items": [...]}` |
| GET | `/api/vector-index/runs/{run_id}` | 单次运行详情 | `200` / `404` |
| GET | `/api/degradation/status` | 降级路径自检（模型缺失 / 超预算） | `200 {...}` |

Celery beat 每 30 分钟（`7,37` 分）自动执行一次向量索引增量同步；对账建议在低峰期手动触发。

约定：

- **鉴权**：当服务端设置 `INTERNAL_TOKEN` 时，请求必须携带请求头 `X-Internal-Token: <token>`，否则返回 `401`；
- **异步语义**：任务接口一律 `202` + `{"taskId": ...}`（camelCase），由边缘侧轮询 `GET /api/tasks/{task_id}` 获取结果；
- **直接查询接口**（供边缘回源或调试）：`GET /api/repos`、`GET /api/trending?date=&language=&limit=`、`GET /api/trending/{owner}/{repo}`、`GET /api/trending/snapshots`、`GET /api/trending/dates`、`GET /api/trending/languages?date=`、`GET /api/trending/history`、`POST /api/recommend/query`、`GET /api/recommend/evaluations`、`GET /api/recommend/qualified`；
- **推荐理由**：`reason` 为中文可读文案，`based_on` 为 JSON 数组字符串（如 `["相似度 87%","语言 Python","技术栈 FastAPI"]`），由 `services/recommend_reason.py` 基于用户画像与候选字段生成，不调用 LLM；存量数据可调用 `POST /api/tasks/regenerate-recommendation-reasons` 批量回填；
- **抓取告警**：`GET /api/trending/alerts?status=open|acknowledged|all`、`POST /api/trending/alerts/{id}/ack`；
- **热榜快照**：抓取任务同时写入 `trending_repositories`（最新状态）与 `trending_snapshots`（按日，主键 `(snapshot_date, repo_id)`）；快照含 `rank` / `language_rank` / `star_delta` / `rank_delta` / `appearances` / `is_new` / `trend`，趋势基线最多回看 7 天；
- **数据契约**：本地表结构与 D1 Schema 保持一致（`my_repositories` / `trending_repositories` / `trending_snapshots` / `categories` 字段名与语义镜像），边缘侧按 `id`（`owner/repo`）对齐；
- **降级语义**：外部依赖不可用时任务返回 `{"status": "skipped"|"error", ...}` 而不是失败抛错，边缘侧可安全重试。

### README 摘要批量队列（M1-13）

```
同步任务 upsert → summarize_readmes.delay(变化仓库) → 逐条抓 README / 清洗
→ Ollama（首选）→ DeepSeek（可选）→ 截断原文（兜底）
→ 分批写本地 SQLite →（配置 EDGE_BASE_URL 时）POST {edge}/api/repos/summaries 回写 D1
```

- 只处理 `readme_summary` 为空的仓库；`force=1` 可重算；
- `SUMMARY_BATCH_SIZE` / `SUMMARY_MAX_PER_RUN` / `SUMMARY_DELAY_MS` / `OLLAMA_KEEP_ALIVE` 共同控制 2G 推理预算；
- 任务通过 Celery `PROGRESS` 上报 `{phase, processed, total, percent, current}`，边缘侧可轮询 `/api/tasks/{taskId}`；
- 摘要回写失败不影响本地落库，任务结果里 `writeback` 字段会标明 `ok / skipped / error`。

### 摘要质量抽检（M2-04）

- 每条摘要都做启发式评分：非空 / 长度 / 中文占比 / 功能·技术·场景三要素覆盖 / 非降级 / 无噪声 / 无重复；
- 样本按 `sha256(batch_id:repo_source:repo_id)` 确定性抽取，同一批次重跑样本稳定；低于 `SUMMARY_SAMPLE_ALWAYS_BELOW` 的摘要强制留存；
- 样本写入 `summary_quality_samples`，支持人工复核与统计（均为内部接口，需 `X-Internal-Token`）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/summaries/quality/samples` | 样本列表（`status` / `repoSource` / `batchId` / `limit` / `offset`） |
| POST | `/api/summaries/quality/samples/{id}/review` | 人工复核：`{"result":"passed\|failed","reviewer":"...","note":"..."}` |
| GET | `/api/summaries/quality/stats` | 总量 / 待复核 / 通过率 / 平均分 / 来源分布 / 最近批次 |
| POST | `/api/summaries/quality/sample-existing` | 存量摘要补抽样：`{"source":"my\|trending\|all","limit":200,"rate":0.1}` |

## 热榜每日抓取

- Celery beat `crawl-trending-daily` 每天 `03:27`（Asia/Shanghai，可用 `TRENDING_CRAWL_HOUR` / `TRENDING_CRAWL_MINUTE` 覆盖）触发 `crawl_trending`；
- 抓取全局页 + `TRENDING_LANGUAGES` 列出的语言页，页间串行并默认间隔 1 秒，避免触发 GitHub 限流；
- 同一仓库跨页去重，`stars` / `stars_today` 取最大值，`owner` / `language` / `stars` 一并落库；
- 单页失败不中断整轮，任务结果包含 `pages[]` 与 `failedPages[]`（`status=partial` / `error`），作为 M2-02 告警的基础信号；
- 每次抓取同时写 `trending_snapshots`（主键 `snapshot_date + repo_id`）：同一日重复执行幂等，趋势字段对比上一有效快照（最多回看 7 天）计算 `star_delta` / `rank_delta` / `appearances` / `is_new` / `trend`；
- 配置 `EDGE_BASE_URL` + `INTERNAL_TOKEN` 时，快照按批（默认 200 条）回写 `POST /api/internal/trending/snapshots`；回写失败只记日志，不影响本地入库；
- 手动触发示例：`curl -X POST 'http://127.0.0.1:8000/api/tasks/crawl-trending?platform=github&languages=python,rust' -H "X-Internal-Token: <token>"`。

## 热榜数据保留（M2-08）

- Celery beat `cleanup-trending-daily` 每天 `04:17`（Asia/Shanghai，可用 `TRENDING_RETENTION_HOUR` / `TRENDING_RETENTION_MINUTE` 覆盖）触发 `cleanup_trending_data`；
- 保留窗口默认 90 天（`TRENDING_RETENTION_DAYS`，`0` 暂停）：删除 `snapshot_date < today - N` 的快照；
- **先归档后删除**：过期快照写成 `TRENDING_ARCHIVE_DIR` 下的 `trending-snapshots-<起>_<止>.jsonl.gz`（gzip JSONL，首行为格式头）；归档失败时不删除任何行；
- 本地删除成功后调用 edge `POST /api/internal/trending/retention/cleanup` 删除 D1 同日期范围；未配置 `EDGE_BASE_URL` / `INTERNAL_TOKEN` 时跳过，失败标记 `status=partial`；
- 归档文件按 `TRENDING_ARCHIVE_KEEP_DAYS`（默认 365 天）滚动清理；状态与手动触发见 `GET/POST /api/trending/retention*`；
- 完整操作手册：`docs/guides/trending-retention.md`。

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

## 语义搜索（M3-04 / M3-10）

`semantic_search` 直接复用 `repo_vectors` 中的持久化向量，不再即时编码仓库文本：

- **查询理解**：`POST /api/search/understand` 基于内置同义词 / 技术栈词表做确定性扩展
  （ASCII 按词边界、中文按子串、最长别名优先），输出重写查询与关键词列表；不依赖网络 / LLM，
  可用 `expand=false` 关闭；
- **查询向量化**：`POST /api/search/embed` 返回 `{vector, dim, model, backend, understanding}`，供 edge 调用 Vectorize；
- **本地检索**：`POST /api/search/query` 对 `repo_vectors` 做全量余弦排序（`scope=my|trending|all`），
  维度不一致 / 非法向量自动跳过，`SEARCH_MAX_VECTORS` 限制扫描量；
- **结果水合**：`POST /api/search/semantic` 按来源查 `my_repositories` / `trending_repositories`，
  返回名称、描述、语言、Star、链接与中文相似度说明；
- **降级**：edge 侧优先 Vectorize，失败或无命中回落到本地检索，VPS 不可达时再用 D1 关键词检索
  （使用 `understanding.keywordTerms` 做多词 OR LIKE 提升召回）。

```bash
# 查询向量（edge 用于 Vectorize）
curl -sS -X POST 'http://127.0.0.1:8000/api/search/embed' \
  -H 'X-Internal-Token: <token>' -H 'Content-Type: application/json' \
  -d '{"query":"支持多租户的 NestJS 管理后台模板"}'

# 本地语义检索（直接返回完整项目信息）
curl -sS -X POST 'http://127.0.0.1:8000/api/search/semantic' \
  -H 'X-Internal-Token: <token>' -H 'Content-Type: application/json' \
  -d '{"query":"轻量级 Python 任务调度工具","topK":5,"scope":"all"}'

# 覆盖率 / 模型分布
curl -sS 'http://127.0.0.1:8000/api/search/status'
```

## 每日推荐生成（M3-05）

Celery beat 每天 08:30（Asia/Shanghai）执行 `generate_recommendations`，早于每日推送准备：

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

## Telegram 推送通道（M4-04）

每日 09:05（Asia/Shanghai）在 `daily_push` 之后执行 `send_telegram_digest`，把最近
`TELEGRAM_DIGEST_WINDOW_HOURS` 小时内进入 `pushed` 的推荐生成中文摘要并发送到配置的会话：

1. **取数**：按 `quality_score` / `score` 降序取 `TELEGRAM_DAILY_LIMIT` 条，关联
   `trending_repositories` 补全标题、简介、链接与今日 Star；
2. **格式化**：HTML 转义 + 单条推荐自包含区块；按 3800 字符打包，绝不超过 Telegram 4096 上限；
3. **发送**：`sendMessage`（`parse_mode=HTML`，关闭链接预览）；网络异常 / 429 / 5xx 指数退避，
   429 优先使用 `retry_after`；4xx（token / chat 错误）不重试；
4. **幂等**：同一天同一用户同一会话成功发送过则跳过，`force=true` 可重发；
5. **送达记录**：每次发送写 `telegram_deliveries`（`sent` / `failed` / `pending`），
   状态接口只返回脱敏 chat id，Bot Token 永不返回。

### 启用步骤

1. 在 Telegram 找 `@BotFather` 创建 Bot，拿到 Bot Token；
2. 把 Bot 拉进目标私聊 / 群组，发送一条消息后调用
   `https://api.telegram.org/bot<token>/getUpdates` 获取 `chat.id`（群组为负数）；
3. 在 `vps/.env` 配置 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`，并设 `TELEGRAM_ENABLED=true`；
4. 重启 API / worker / beat，先发测试消息确认链路。

```bash
# 查看状态（不返回 token，chat id 只显示末四位）
curl -sS 'http://127.0.0.1:8000/api/notifications/telegram/status' \
  -H 'X-Internal-Token: <token>'

# 发送测试消息
curl -sS -X POST 'http://127.0.0.1:8000/api/notifications/telegram/test' \
  -H 'Content-Type: application/json' \
  -H 'X-Internal-Token: <token>' \
  -d '{"text":"Telegram 通道测试"}'

# 手动触发每日摘要（force 忽略当日幂等）
curl -sS -X POST 'http://127.0.0.1:8000/api/tasks/send-telegram-digest?force=true' \
  -H 'X-Internal-Token: <token>'
```

> 单用户口径：`TELEGRAM_CHAT_ID` 为一个会话；多用户 / 多会话偏好由 M4-06 承接，
> 去重与静默策略由 M4-07 承接，送达回执由 M4-08 承接。

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

## 推送偏好（M4-06）

推送偏好保存在 edge 的 D1 `push_preferences` 表，VPS 在推送时通过内部接口批量拉取；
未保存偏好的用户使用默认值（启用、09:00、Asia/Shanghai、匹配度 0.35、质量分 0.55、仅站内通知）。

- **调度**：Celery beat 每 10 分钟执行一次 `daily_push(respect_schedule=True)`，按用户时区判断是否落在
  `time_of_day` 起 10 分钟窗口内（支持跨午夜）；手动触发默认 `respect_schedule=false`，立即推送；
- **筛选**：逐用户检查总开关、至少一个通道、`min_score` / `min_quality_score` 阈值；
  匹配度优先 `match_score`，缺失回退 `score`；质量分仅在 `>0` 时参与，避免历史数据误杀；
- **降级**：edge 不可达或内部令牌未配置时回退默认偏好，不阻塞推送；
- **返回**：`{status, pushed, skippedUsers, users:[{userId,pushed,filtered?,channels?,reason?}]}`，
  跳过原因包括 `disabled` / `no_channel` / `not_due`。

```bash
# 手动触发（立即推送，忽略时间窗口）
curl -sS -X POST 'http://127.0.0.1:8000/api/tasks/daily-push' \
  -H 'X-Internal-Token: <token>'

# 指定用户 / 按偏好时间窗口
curl -sS -X POST 'http://127.0.0.1:8000/api/tasks/daily-push?user_id=default&respect_schedule=true' \
  -H 'X-Internal-Token: <token>'
```
## 推送去重与静默（M4-07）

`daily_push` 在把 `qualified` 标记为 `pushed` 前统一经过策略闸门，所有推送通道共用 `push_events` 账本：

1. **静默时段**：`PUSH_QUIET_HOURS_START` / `PUSH_QUIET_HOURS_END`（默认 22:00–08:00，支持跨午夜），按 `PUSH_TIMEZONE` 解释；静默中不改推荐状态，由 `retry_deferred_push` 在窗口结束后重试；
2. **跨天去重**：同一用户 + 仓库在 `PUSH_DEDUPE_DAYS`（默认 7 天）内已推送过则标记 `expired`；`PUSH_DEDUPE_CROSS_CHANNEL=true` 时跨通道生效；
3. **每日上限**：每用户每个本地自然日最多 `PUSH_DAILY_LIMIT`（默认 3）个去重仓库；超限保留 `qualified` 等次日 / 重试；
4. **事件账本**：`push_events` 以 `event_key = user:repo:channel:YYYY-MM-DD` 幂等记录 `prepared / sent / failed / skipped`，`failed` / `skipped` 不占额度；
5. **总开关**：`PUSH_POLICY_ENABLED=false` 时保持旧行为（仅标记 `pushed`，不做静默 / 去重 / 限额）。

```bash
# 策略状态 / 今日计数 / 最近事件
curl -sS 'http://127.0.0.1:8000/api/push/policy/status' -H 'X-Internal-Token: <token>'

# 发送前预演（不写库）
curl -sS -X POST 'http://127.0.0.1:8000/api/push/policy/check' \
  -H 'Content-Type: application/json' -H 'X-Internal-Token: <token>' \
  -d '{"userId":"default","repoId":"owner/repo","channel":"bark"}'

# 通道回报投递结果（幂等）
curl -sS -X POST 'http://127.0.0.1:8000/api/push/policy/events' \
  -H 'Content-Type: application/json' -H 'X-Internal-Token: <token>' \
  -d '{"userId":"default","repoId":"owner/repo","channel":"bark","status":"sent"}'
```

Celery beat 每 10 分钟执行 `daily_push(respect_schedule=True)`，并按 `PUSH_RETRY_INTERVAL_MINUTES`（默认 30 分钟）执行
`retry_deferred_push`；重试任务只在非静默且存在 `qualified` 时真正运行。

## 推送记录与回执（M4-08）

Bark / Telegram / Email 每次实际发送都会写一条 `push_deliveries`，并在发送结束后回写
`sent` / `failed` / `skipped`；服务商异步回执或人工补记通过 `POST /api/push/receipts`
写入 `push_receipts`，支持 `accepted / delivered / bounced / failed` 四种状态。

```bash
# 最近 7 天的记录（可按 channel / status / kind / q / date_from / date_to 过滤）
curl -sS 'http://127.0.0.1:8000/api/push/records?date_from=2026-10-15T00:00:00&page=1&pageSize=20' \
  -H 'X-Internal-Token: <token>'

# 统计
curl -sS 'http://127.0.0.1:8000/api/push/records/stats?days=30' \
  -H 'X-Internal-Token: <token>'

# 写入回执（服务商回调或人工确认）
curl -sS -X POST 'http://127.0.0.1:8000/api/push/receipts' \
  -H 'Content-Type: application/json' \
  -H 'X-Internal-Token: <token>' \
  -d '{"deliveryId":"<id>","status":"delivered","source":"manual","detail":"人工确认已送达"}'
```

说明：

- 列表接口的 `days` 只用于 `stats`；记录列表用 `date_from` / `date_to`（ISO 时间）过滤；
- 目标字段统一脱敏：邮箱 `a***@example.com`，chat id `12***89`，Bark group 原样返回；
- 同一 `deliveryId + externalId + status` 重复回调幂等；已 `delivered` 的记录不会被迟到回执降级；
- Bark / Telegram 官方 API 没有逐条送达回执，默认只有发送结果；需要精确送达时由服务商适配器或人工补记；
- 历史 `telegram_deliveries` / `email_deliveries` 不回填，统一记录从本版本起生效。

## 常用检查

```bash
cd vps
.venv/bin/pytest -q
.venv/bin/python -c "from app.main import app; print('app ok')"
```
