# 实施计划 · REQ-202610-0922 语义搜索接口与页面（自然语言检索）

> 需求：REQ-202610-0922（backlog M3-04）｜ 分支：`feat/req-202610-0922-semantic-search`
> 依赖：M3-02 向量化管线（REQ-202610-0920）、M3-03 Vectorize 索引同步（REQ-202610-0921）
> 目标：用户输入自然语言，跨「我的收藏」与「每日热榜」返回语义相似项目，并提供可用的检索页面。

## 1. 现状与缺口

- `repo_vectors` 已持久化每个仓库的向量（M3-02），Vectorize 已具备批量同步能力（M3-03）；
- 现有 `POST /api/recommend/query` 每次请求都会对最多 500 个收藏仓库**即时编码**，既慢又只覆盖收藏库；
- 没有面向用户的语义搜索接口，也没有检索页面；
- edge 已绑定 Vectorize，但尚无查询入口。

## 2. 方案总览

```
admin 搜索页 → POST /api/search/semantic（edge，登录态）
  → edge 调 VPS /api/search/embed 生成查询向量（X-Internal-Token）
  → edge 用 VECTORIZE.query 做近邻检索（topK 放大后过滤）
  → edge 按 source/repo_id 从 D1 水合（my 仅当前用户；trending 全局）
  → 返回匹配度 + 来源 + 项目元信息

降级链：
  Vectorize 未绑定 / 查询失败 / 0 命中 → VPS /api/search/query（本地 repo_vectors 余弦检索）
  VPS 不可达 → edge 在 D1 内做关键词检索（mode=keyword），页面仍可用
```

## 3. 接口契约

### 3.1 admin ↔ edge

`POST /api/search/semantic`（需登录）

```json
{ "query": "支持多租户的 NestJS 管理后台模板", "topK": 10, "scope": "all" }
```

响应：

```json
{
  "query": "...",
  "mode": "vectorize | local | keyword",
  "count": 2,
  "tookMs": 18,
  "backend": "hash",
  "model": "BAAI/bge-m3",
  "dim": 256,
  "items": [
    {
      "id": "owner/repo",
      "source": "my | trending",
      "fullName": "owner/repo",
      "name": "repo",
      "description": "...",
      "language": "TypeScript",
      "stars": 1234,
      "starsToday": 12,
      "url": "https://github.com/owner/repo",
      "score": 0.87,
      "reason": "与查询语义相似度 87%，主要使用 TypeScript 开发。"
    }
  ]
}
```

约束：`query` 去空白后 1~200 字符；`topK` 1~30，默认 10；`scope` 为 `my | trending | all`，默认 `all`。

### 3.2 edge ↔ vps（内部接口，`X-Internal-Token`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/search/embed` | POST | `{query}` → `{vector, dim, model, backend}`，供 edge 查询 Vectorize |
| `/api/search/query` | POST | `{query, topK, scope, minScore}` → 本地向量余弦命中（`source` / `repoId` / `score`） |
| `/api/search/semantic` | POST | 同上但直接返回水合后的完整项目信息（内部 / 调试 / CLI 使用） |
| `/api/search/status` | GET | 向量覆盖率、模型 / 后端分布与最近一次向量化运行 |

## 4. 实现要点

### 4.1 VPS

- 新增 `app/services/semantic_search.py`：
  - `normalize_scope` / `load_vectors` / `search_vectors`（纯函数，余弦排序）；
  - `search_local`：`EmbeddingService.encode_one(query)` → 读取 `repo_vectors` → 排序；
  - 维度不一致的向量跳过并计数；`minScore` 过滤；`SEARCH_MAX_VECTORS` 限制扫描量；
  - `hydrate_hits`：按 `source` 查 `my_repositories` / `trending_repositories`，拼装中文摘要与元信息；
  - `get_status`：按来源 / 模型 / 后端统计，附最近运行。
- 新增 `app/api/search.py`，四个端点统一 `require_internal_token`；
- `schemas.py` 增加搜索请求 / 响应模型；
- `config.py` 增加 `SEARCH_DEFAULT_TOP_K` / `SEARCH_MAX_TOP_K` / `SEARCH_MIN_SCORE` / `SEARCH_MAX_VECTORS`；
- `.env.example` 与 `deploy/env/openfactory.env.example` 同步；
- `runtime.py` 的 `REQUIRED_ENV_KEYS` 补充新配置。

### 4.2 edge

- 新增 `edge/src/routes/search.ts`，挂载 `/api/search`；
- 登录态校验；参数校验与 topK 限制；
- Vectorize 优先：`VPS /api/search/embed` → `VECTORIZE.query`；
- 本地降级：`VPS /api/search/query`；
- 最终降级：D1 `LIKE` 关键词检索（`mode=keyword`）；
- 水合时 `my` 仅保留 `user_id = 当前用户` 的行，避免跨用户泄漏；
- `types.ts` 增加 `SearchResultItem` / `SearchResponse` 类型（`VECTORIZE` 绑定已由 M3-03 引入）。

### 4.3 admin

- 新增 `features/search/api.ts`（`searchRepositories`，失败时使用演示数据）；
- 新增 `features/search/index.tsx`：搜索框、示例查询、加载 / 空态 / 错误态、结果卡片（来源、匹配度、语言、Star、摘要、外链）；
- 新增路由 `routes/_authenticated/search/index.tsx`；
- 侧边栏「开源资产」增加「语义搜索」入口；
- 新增纯函数单测（查询归一化 / 匹配度格式化）。

## 5. 文件清单

- `vps/app/services/semantic_search.py`（新增）
- `vps/app/api/search.py`（新增）
- `vps/app/schemas.py`、`vps/app/config.py`、`vps/app/main.py`、`vps/app/runtime.py`
- `vps/tests/test_semantic_search.py`（新增）
- `vps/.env.example`、`deploy/env/openfactory.env.example`
- `edge/src/routes/search.ts`（新增）、`edge/src/index.ts`、`edge/src/types.ts`
- `admin/src/features/search/{api.ts,index.tsx,search.test.ts}`（新增）
- `admin/src/routes/_authenticated/search/index.tsx`（新增）
- `admin/src/components/layout/data/sidebar-data.ts`
- 文档：`docs/architecture/overview.md`、`docs/requirements/backlog.md`、`docs/planning/task-planning.md`、`vps/README.md`、`edge/README.md`

## 6. 验证计划

- `vps`: `.venv/bin/pytest -q`（新增语义搜索服务 / API / 降级 / 鉴权用例）；
- `edge`: `npm run typecheck`；
- `admin`: `npm run lint && npm run build && npm run test`；
- `git diff --check`；
- 不访问网络：VPS 使用 `EMBEDDING_FORCE_FALLBACK=1` 的确定性 hash 向量，edge 只做类型检查。

## 7. 风险与边界

- Vectorize 索引需先在 Cloudflare 创建并完成 M3-03 同步，否则自动走本地降级；
- 本地检索为全量余弦扫描，`SEARCH_MAX_VECTORS` 控制上限；更大规模依赖 Vectorize；
- hash 兜底向量只反映字符 trigram 相似度，生产应使用 BGE-M3；
- `my` 结果在 edge 按当前用户过滤，VPS 本地镜像不承担多用户隔离职责；
- 本需求不包含查询理解增强（M3-10）、多轮问答（M6-09）与 Rerank（M7-07）。
