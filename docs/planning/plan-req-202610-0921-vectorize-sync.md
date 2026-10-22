# 实施计划 · REQ-202610-0921 Vectorize 索引同步

> 需求：REQ-202610-0921（backlog M3-03）｜ 分支：`feat/req-202610-0921-vectorize-sync-d3`
> 依赖：M3-02 向量化管线（本地 `repo_vectors`）、Q3 Cloudflare 资源信息（索引名 / 维度）

## 1. 目标与范围

把 VPS 已生成的仓库向量同步到 Cloudflare Vectorize，形成可重复执行、可观测、可对账的索引维护链路：

1. **批量 upsert**：按批读取本地 `repo_vectors`，通过 edge 内部接口写入 Vectorize，单批大小可配（默认 100，上限 1000）；
2. **失败重试**：网络错误 / 429 / 5xx 指数退避重试，单批最终失败只标记该批，不拖垮整个运行；
3. **增量同步**：以 `text_hash` 为版本，只推送新增 / 变更 / 上次失败的向量；
4. **对账**：逐批调用 Vectorize `getByIds` 比对缺失 / 过期向量并修复，可选清理孤儿向量；
5. **可观测**：本地记录 `vector_sync_state`（每条向量的同步状态）与 `vector_sync_runs`（每次运行统计），提供状态 / 运行查询接口；
6. **定时任务**：Celery beat 周期执行增量同步，支持手动触发全量 / 对账。

不在本次范围：语义检索查询接口（M3-04）、推荐生成（M3-05）、Cloudflare 账号资源创建（Q3 由维护者提供）。

## 2. 现状与缺口

- M3-02 已把向量持久化到本地 `repo_vectors(source, repo_id, model, backend, dim, text_hash, vector)`，但没有同步出口；
- edge 尚无 Vectorize 绑定与内部写入接口；
- 缺少同步状态、失败重试与对账机制，索引与本地向量可能长期漂移。

## 3. 方案

### 3.1 数据流

```text
repo_vectors (VPS SQLite)
   │  按批读取（keyset 分页）
   ▼
vector_sync.py（VPS）
   │  POST /api/internal/vectors/upsert   （X-Internal-Token）
   ▼
edge Worker（internal-vectors.ts）
   │  env.VECTORIZE.upsert / getByIds / deleteByIds / describe
   ▼
Cloudflare Vectorize 索引
```

VPS 不持有 Cloudflare 账号凭据；所有 Vectorize 操作都经 edge 绑定完成，凭据边界与 D1 一致。

### 3.2 向量标识与元数据

- `vector_id = "v1_" + sha256("{source}:{repo_id}")[:32]`，固定 35 字符，规避 Vectorize ID 长度限制，且跨运行稳定；
- 元数据：`source`（my / trending）、`repo_id`、`text_hash`、`model`、`dim`；
- 对账以 `text_hash` 判断是否过期，避免仅凭 ID 存在性误判。

### 3.3 本地状态表

| 表 | 关键字段 | 用途 |
| --- | --- | --- |
| `vector_sync_state` | `(source, repo_id)` 主键、`vector_id`、`text_hash`、`status`、`attempts`、`last_error`、`synced_at` | 每条向量的同步状态；增量筛选与失败重试依据 |
| `vector_sync_runs` | `id`、`kind`、`scope`、`status`、`total/processed/synced/deleted/skipped/failed/checked/missing/repaired`、`error` | 每次同步运行的可观测记录 |

### 3.4 同步模式

| 模式 | 行为 |
| --- | --- |
| `sync`（增量，默认） | 只处理 `state` 缺失、`text_hash` 不一致或上次失败的向量 |
| `sync` + `force=true` | 忽略状态，按 `limit` 全量 upsert（用于索引重建） |
| `reconcile` | 先 `getByIds` 对账，仅修复缺失 / 过期；可选清理本地已不存在的孤儿向量 |

### 3.5 重试与降级

- 客户端对 `TransportError`、429、500/502/503/504 做指数退避（`VECTORIZE_SYNC_MAX_RETRIES`，默认 3 次；429 优先 `Retry-After`）；
- 4xx 参数错误不重试，直接标记该批失败；
- 维度与索引不一致的向量跳过并计数（`skipped` / `dim_mismatch`），不阻断其他向量；
- 未配置 `EDGE_BASE_URL` / `INTERNAL_TOKEN` 时任务返回 `disabled`，不产生异常堆积；
- 单批失败只更新该批状态为 `failed`，下次增量运行自动重试。

### 3.6 接口

VPS（内部令牌鉴权）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/vector-index/sync` | 入队同步（kind / scope / limit / batchSize / force） |
| GET | `/api/vector-index/status` | 本地向量数、状态分布、最近运行 |
| GET | `/api/vector-index/runs` | 最近运行列表 |
| GET | `/api/vector-index/runs/{id}` | 单次运行详情 |

edge（`X-Internal-Token`）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/internal/vectors/upsert` | 批量 upsert（≤1000 条） |
| POST | `/api/internal/vectors/check` | 按 id 批量查询（≤100 条） |
| POST | `/api/internal/vectors/delete` | 按 id 批量删除（≤1000 条） |
| GET | `/api/internal/vectors/stats` | 索引统计（`describe`） |
| GET | `/api/internal/vectors/list` | 分页列出 id（可选，用于孤儿对账） |

## 4. 文件清单

- `vps/app/services/vector_sync.py`：同步核心、edge 客户端、对账与状态维护
- `vps/app/models.py`：`VectorSyncState`、`VectorSyncRun`
- `vps/app/api/vector_sync.py`：状态 / 运行 / 入队接口
- `vps/app/schemas.py`：同步请求与运行输出模型
- `vps/app/tasks/jobs.py`、`vps/app/tasks/celery_app.py`：Celery 任务与 beat 计划
- `vps/app/main.py`：挂载路由
- `vps/app/config.py`、`vps/.env.example`、`deploy/env/openfactory.env.example`：同步配置
- `edge/src/routes/internal-vectors.ts`、`edge/src/index.ts`、`edge/src/types.ts`、`edge/wrangler.toml`：Vectorize 绑定与内部接口
- `vps/tests/test_vector_sync.py`：批量、增量、重试、对账、维度、API 用例
- 文档：`docs/architecture/overview.md`、`docs/architecture/data-model.md`、`vps/README.md`、`edge/README.md`、`docs/planning/roadmap.md`、`docs/planning/task-planning.md`

## 5. 验证计划

- `cd vps && .venv/bin/pytest -q`：51 passed（新增用例不访问网络，使用 fake client / MockTransport）；
- `cd edge && npm run typecheck`：0 error；
- `git diff --check`：无空白错误；
- 手工冒烟：配置 mock edge 后触发 `POST /api/vector-index/sync`，核对 upsert 批次、重试次数与状态表。

## 6. 风险与待人工事项

1. **Q3 资源未提供**：`VECTORIZE_INDEX_NAME` / 维度 / 账号需维护者创建索引并填写；本分支默认 `opensource-factory-vectors`、1024 维、cosine。
2. **维度**：BGE-M3 为 1024 维；hash 兜底为 256 维，联调时需确保索引维度与 `VECTORIZE_INDEX_DIM` 一致，否则会跳过并提示。
3. **孤儿清理默认关闭**：`VECTORIZE_SYNC_DELETE_ORPHANS=false`，确认索引仅由本系统使用后再开启。
4. **M3-02 分支未合并**：本分支通过原生 SQL 读取 `repo_vectors`，表不存在时返回明确错误；M3-02 合并后即可直接运行。
