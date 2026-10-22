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
│   │   ├── summarizer.py         # Ollama → DeepSeek → 截断降级 的摘要生成
│   │   └── recommender.py        # 余弦排序 + 中文推荐理由模板
│   ├── api/                  # HTTP 层（只做参数校验与编排）
│   │   ├── repos.py              # GET /api/repos、POST /api/repos/sync
│   │   ├── trending.py           # GET /api/trending、POST /api/trending/crawl
│   │   ├── recommend.py          # POST /api/recommend/query、POST /api/recommend/generate
│   │   └── tasks.py              # /api/tasks/*（与边缘 Worker 的集成契约，X-Internal-Token 鉴权）
│   └── tasks/                # Celery 任务（薄封装，调用 services + 落库）
│       ├── celery_app.py         # Celery 应用与 beat 定时计划
│       └── jobs.py               # sync / crawl / generate / daily_push 四个任务
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

## 环境变量说明

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./data/opensource_factory.db` | 本地镜像库（SQLite 起步，可换 PostgreSQL） |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker / result backend |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | 本地 Ollama 服务地址 |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Ollama 摘要模型（M3-01 选型后切换 ≤2B 量化模型） |
| `OLLAMA_KEEP_ALIVE` | `2m` | 模型空闲卸载时间，控制 2G 推理预算 |
| `DEEPSEEK_API_KEY` | 空 | 可选；配置后作为 LLM 云端降级（OpenAI 兼容） |
| `SUMMARY_BATCH_SIZE` | `10` | 摘要任务每批提交条数 |
| `SUMMARY_MAX_PER_RUN` | `200` | 单次摘要任务最多处理条数 |
| `SUMMARY_DELAY_MS` | `500` | 每条摘要之间的间隔（毫秒），给 Ollama 留出余量 |
| `SUMMARY_MAX_CHARS` | `800` | 摘要最大字符数 |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | 向量模型名（sentence-transformers / FlagEmbedding） |
| `INTERNAL_TOKEN` | 空 | 设置后 `/api/tasks/*` 必须携带 `X-Internal-Token`；为空表示本地开发不鉴权 |
| `EDGE_BASE_URL` | 空 | edge Worker 地址；配置后摘要任务批量回写 D1 |
| `CELERY_TASK_ALWAYS_EAGER` | `0` | 置 `1` 时任务同步执行（本地调试 / 测试用） |
| `GITHUB_TOKEN` | 空 | GitHub PAT（仅需 read 权限）；为空时同步任务跳过 |

完整清单见 `.env.example`。所有真实密钥只存在于本地 `.env`（git 忽略）或平台密钥托管，**不得提交**。

## 与 Cloudflare 边缘的接口约定

边缘 Worker 通过内部 API 调度本节点，全部任务接口位于 `/api/tasks/*`：

| 方法 | 路径 | 说明 | 返回 |
| --- | --- | --- | --- |
| POST | `/api/tasks/sync` | 入队 GitHub 仓库同步（自己的 + Starred，`with_summary=1` 时完成后自动排队摘要） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/summarize` | 入队 README 摘要批量生成（可选 `repo_id` 重复传、`limit`、`batch_size`、`force`、`max_chars`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/crawl-trending` | 入队热榜抓取（`platform=github\|gitee\|all`，可选 `language`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/generate-recommendations` | 入队推荐生成（可选 `user_id`、`top_k`） | `202 {"taskId": "..."}` |
| POST | `/api/tasks/daily-push` | 入队每日推送准备（将 `new` 推荐标记为 `pushed`） | `202 {"taskId": "..."}` |
| GET | `/api/tasks/{task_id}` | 查询任务状态（`pending/started/progress/success/failure`，PROGRESS 时带 `progress`） | `200 {"taskId","status","result","progress"}` |

约定：

- **鉴权**：当服务端设置 `INTERNAL_TOKEN` 时，请求必须携带请求头 `X-Internal-Token: <token>`，否则返回 `401`；
- **异步语义**：任务接口一律 `202` + `{"taskId": ...}`（camelCase），由边缘侧轮询 `GET /api/tasks/{task_id}` 获取结果；
- **直接查询接口**（供边缘回源或调试）：`GET /api/repos`、`GET /api/trending`、`POST /api/recommend/query`；
- **数据契约**：本地表结构与 D1 Schema 保持一致（`my_repositories` / `trending_repositories` / `categories` 字段名与语义镜像），边缘侧按 `id`（`owner/repo`）对齐；
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

## 常用检查

```bash
cd vps
.venv/bin/pytest -q
.venv/bin/python -c "from app.main import app; print('app ok')"
```
