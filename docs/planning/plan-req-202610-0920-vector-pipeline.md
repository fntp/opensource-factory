# 实施计划 · REQ-202610-0920 向量化管线（收藏库 + 热榜；批量 / 增量 / 断点续跑）

> 需求：REQ-202610-0920（backlog M3-02）｜ 分支：`feat/req-202610-0920-vector-pipeline`
> 依赖：M3-01（模型选型与 2G 预算验证）——本需求按「模型可配置 + 后端可降级」实现，
> M3-01 完成后只需调整 `EMBEDDING_MODEL` / `EMBEDDING_FORCE_FALLBACK`，无需改代码。

## 1. 目标

把「收藏库（`my_repositories`）」与「热榜（`trending_repositories`）」的文本向量化做成
可重复执行的数据管线：

1. **批量**：按批编码、按批提交，单次可限制条数，避免一次性把大量文本塞进内存；
2. **增量**：文本内容未变化且模型 / 后端一致的仓库直接跳过，只处理新增 / 变更仓库；
3. **断点续跑**：每次运行落一条 `vectorization_runs` 记录，逐批提交游标（source + repo_id）；
   任务中断后可用同一 `runId` 继续，不重复处理已完成的仓库；
4. **可观测**：提供运行状态、统计接口与 Celery `PROGRESS` 进度，失败可定位到批次与仓库范围；
5. **可降级**：未安装 BGE-M3 重型依赖时使用既有确定性 hash 向量，测试与 CI 不依赖模型 / 网络。

## 2. 现状与缺口

- `vps/app/services/embedding.py` 已有 BGE-M3（sentence-transformers / FlagEmbedding）懒加载与
  256 维 hash 兜底，但只被推荐接口即时调用；
- 推荐 / 语义查询每次都重新编码全量文本，没有持久化向量；
- 没有「哪些仓库已向量化、哪些内容变了」的状态，无法增量；
- 没有运行记录与游标，任务中断只能从头再来。

## 3. 方案

### 3.1 数据模型（VPS 本地 SQLite）

新增两张本地表（`Base.metadata.create_all` 幂等建表，不影响 D1）：

`repo_vectors`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| source | TEXT | `my` / `trending`，联合主键 |
| repo_id | TEXT | 仓库 id，联合主键 |
| model | TEXT | 编码模型名（`EMBEDDING_MODEL`） |
| backend | TEXT | `sentence-transformers` / `flagembedding` / `hash` |
| dim | INTEGER | 向量维度 |
| text_hash | TEXT | 参与编码文本的 SHA-256，用于增量判断 |
| vector | TEXT | JSON 数组（保留 6 位小数） |
| created_at / updated_at | DATETIME | 生成 / 最近更新时间 |

`vectorization_runs`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | 运行 id（UUID hex），API 返回给调用方 |
| scope | TEXT | `my` / `trending` / `all` |
| status | TEXT | `running` / `completed` / `failed` |
| model / backend / dim | — | 本次运行使用的编码配置 |
| force / limit / batch_size | — | 运行参数 |
| total / processed / vectorized / skipped / failed | INTEGER | 计数 |
| cursor_source / cursor_repo_id | TEXT | 断点游标（最后一批已提交的位置） |
| error | TEXT | 失败原因 |
| created_at / updated_at / finished_at | DATETIME | 时间 |

### 3.2 文本与增量口径

- 收藏库：`name + description + readme_summary + language`；
- 热榜：`name + description + tech_stack`；
- `text_hash = sha256(文本)`；跳过条件：`text_hash` 相同 **且** `model` / `backend` 相同；
- `force=true` 忽略上述条件全部重算；模型或后端变化时旧向量会在下次运行时被覆盖；
- 向量按 `repo_id` upsert，不产生重复行。

### 3.3 批处理与断点续跑

- 按 `source, repo_id` 稳定排序，使用 keyset 分页（`id > cursor`）逐批读取，每批最多 `batch_size` 条；
- `limit` 只限制**待处理**条数：已向量化且未变化的仓库只计入 `skipped`，不占用预算，避免大库永远轮不到后面的仓库；
- 每批：批量查已存向量 → 过滤未变化 → 批量编码 → upsert → 更新运行计数与游标 → **提交事务**；
- 每批提交后回调进度（Celery `update_state(PROGRESS)`）；
- 运行失败时保留已提交批次，`status=failed`；再次以同一 `runId` 提交即可从游标继续；
- 已 `completed` 的运行不允许重复执行；`runId` 不存在返回 404。

### 3.4 接入点

- 新增 `vps/app/services/vector_pipeline.py`：运行创建 / 执行 / 统计 / 序列化；
- 新增 Celery 任务 `app.tasks.jobs.vectorize_repositories`；
- `POST /api/tasks/vectorize` 入队，返回 `taskId` + `runId`；
- `GET /api/vectors/runs/{runId}`、`GET /api/vectors/runs`、`GET /api/vectors/stats` 查询；
- 同步 / 热榜抓取完成后按 `VECTORIZE_AUTO=true` 自动入队对应来源的增量任务（失败不影响主任务）。

### 3.5 配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | 既有；M3-01 完成后切换量化模型 |
| `EMBEDDING_FORCE_FALLBACK` | `false` | `true` 时强制 hash 向量（CI / 2G 预算紧张时） |
| `VECTORIZE_BATCH_SIZE` | `32` | 每批条数（1~256） |
| `VECTORIZE_MAX_PER_RUN` | `1000` | 单次默认上限，防止长时间占用 worker |
| `VECTORIZE_AUTO` | `true` | 同步 / 抓取完成后自动入队增量任务 |

## 4. 文件清单

- `vps/app/models.py`：新增 `RepoVector` / `VectorizationRun`
- `vps/app/services/vector_pipeline.py`：管线核心
- `vps/app/api/vectors.py`：统计 / 运行查询
- `vps/app/api/tasks.py`：`POST /api/tasks/vectorize`
- `vps/app/tasks/jobs.py`：Celery 任务与同步 / 抓取后的自动入队
- `vps/app/config.py`、`vps/.env.example`、`deploy/env/openfactory.env.example`、`vps/app/runtime.py`
- `vps/tests/test_vector_pipeline.py`
- 文档：`docs/architecture/overview.md`、`docs/architecture/data-model.md`、`vps/README.md`、
  `docs/requirements/backlog.md`、`docs/planning/task-planning.md`、本计划文档

## 5. 验证计划

- `cd vps && .venv/bin/pytest -q`：覆盖批量、增量跳过、force、limit、断点续跑、API、统计；
- `cd edge && npm run typecheck`：确认未改 edge 契约；
- `cd admin && npm run lint && npm run build && npm run test`：回归（本需求未改 admin）；
- `python -m compileall vps/app`、`git diff --check`。

## 6. 风险与边界

- **M3-01 未合并**：默认模型仍可能超 2G 预算；本需求只保证可配置、可降级，选型由 M3-01 切换；
- **维度变化**：hash 兜底 256 维、BGE-M3 1024 维；`model` / `backend` 变化会触发重算，
  M3-03 同步 Vectorize 时需按索引维度校验；
- **Vectorize 同步不在本需求范围**：本需求只落本地向量与运行状态，M3-03 负责批量 upsert / 重试 / 对账；
- **大表内存**：按批 keyset 分页 + 每批提交，单批编码条数受 `batch_size` 控制；
- **模型加载失败**：既有 `EmbeddingService` 自动降级为 hash，不阻塞任务。
