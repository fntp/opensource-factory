# 实施计划 · REQ-202610-0965 模型路由与升级（按任务选择模型）

> 需求：REQ-202610-0965（backlog M7-06）｜ 分支：`feat/req-202610-0965-model-routing`
> 依赖：M3-01 模型选型与 2G 预算（`vps/app/services/model_budget.py` 已落地）
> 目标：在既有单模型配置之上增加「按任务选模型」的路由层，所有候选模型都必须落在推理内存预算内，并支持人工切换、升级建议与预算可视化。

## 1. 现状与缺口

- M3-01 只确定了全局默认：摘要 `qwen2.5:1.5b-instruct-q4_K_M`、向量 `BAAI/bge-m3`（int8），`OLLAMA_MODEL` / `EMBEDDING_MODEL` 是进程级配置；
- 摘要服务硬编码读取 `OLLAMA_MODEL`，无法针对「摘要 / 打标 / 分类 / 问答 / 精排」分别选择模型；
- 没有多模型目录（质量 / 成本 / 延迟 / 驻留）与统一预算视图，换模型只能改 `.env` 重启；
- 没有升级建议：更高规格模型是否在预算内、切换后峰值驻留多少，只能人工估算；
- 管理端没有模型路由页面，运维无法看到「当前每个任务实际用哪个模型」。

## 2. 方案总览

```
admin /model-routing
  → edge GET/PUT /api/model-routes（登录态，代理）
    → VPS /api/model-routes（X-Internal-Token）
       ├─ MODEL_ROUTING_CATALOG：任务 → 候选模型（质量 / 成本 / 延迟 / 驻留）
       ├─ route_task()：budget | balanced | quality | manual 四种策略
       ├─ model_route_configs（SQLite）：任务级覆盖，缺省走内置默认
       └─ 预算报告：峰值驻留 max(selected) ≤ MODEL_BUDGET_MB
摘要 / 向量任务
  → get_route_decision(task) → 选中的模型 / 量化口径 → Ollama / BGE-M3 / 降级链
```

设计原则：

1. **预算硬约束**：任何路由结果都必须满足 `resident_mb ≤ MODEL_BUDGET_MB`（云端模型驻留按 0 计），超预算候选只能出现在「升级被预算阻塞」提示中；
2. **默认行为不变**：没有覆盖配置时，摘要仍选 `qwen2.5:1.5b-instruct-q4_K_M`，向量仍选 `BAAI/bge-m3` int8；
3. **配置持久化**：任务级选择写 `model_route_configs`，VPS 重启后仍生效；配置读取失败时回退内置默认，不影响摘要 / 向量任务；
4. **可解释**：每个路由结果带 `reason`、候选列表、回退链与预算占用；
5. **升级可控**：升级建议只提示，必须人工确认后写配置；不做自动切换，避免悄悄改变质量 / 成本。

## 3. 任务与候选模型

| 任务 | 默认策略 | 默认模型 | 候选（预算内） | 说明 |
| --- | --- | --- | --- | --- |
| `summary` 摘要生成 | budget | qwen2.5-1.5b-q4 | qwen2.5-1.5b / deepseek-r1-1.5b / deepseek-chat | 本地优先，云端作为质量升级 |
| `embedding` 向量化 | quality | bge-m3-int8 | bge-m3-int8 / bge-small-zh-v1.5 | 默认 1024 维；切小模型需重建向量 |
| `tagging` 自动打标 | budget | local-rules | local-rules / qwen2.5-1.5b / deepseek-chat | 规则引擎零成本，LLM 为增强 |
| `classification` 自动分类 | budget | local-rules | local-rules / qwen2.5-1.5b / deepseek-chat | 同上 |
| `chat` 问答检索 | quality | deepseek-chat | deepseek-chat / qwen2.5-1.5b / deepseek-r1-1.5b | 质量优先，云端未配置时降级本地 |
| `rerank` 精排 | budget | local-heuristic | local-heuristic / qwen2.5-1.5b / deepseek-chat | 为 M7-07 预留路由位 |

策略语义：

- `budget`：预算内本地优先，按「驻留 → 成本 → 质量」排序；本地无候选时才考虑云端；
- `balanced`：预算内按质量减延迟 / 成本惩罚排序，本地优先；
- `quality`：预算内质量最高，允许云端；
- `manual`：必须指定候选模型，且必须满足预算。

## 4. 数据模型

VPS SQLite 新增 `model_route_configs`（`init_db` 的 `create_all` 自动建表，无需迁移脚本）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task` | TEXT PK | 任务键（summary / embedding / …） |
| `strategy` | TEXT | budget / balanced / quality / manual |
| `model_id` | TEXT NULL | manual 策略必填 |
| `updated_by` | TEXT | 操作人（默认 `admin`） |
| `updated_at` | DATETIME | 更新时间 |

## 5. 接口

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/api/model-routes` | GET | `X-Internal-Token` | 任务路由列表 + 模型目录 + 预算报告 + 升级建议 |
| `/api/model-routes/{task}` | PUT | `X-Internal-Token` | 更新任务策略 / 模型（校验候选与预算） |
| `/api/model-routes/{task}` | DELETE | `X-Internal-Token` | 恢复任务默认 |
| `/api/model-routes/reset` | POST | `X-Internal-Token` | 恢复全部默认 |
| `/api/model-routes/upgrade` | POST | `X-Internal-Token` | 应用任务的最佳可用升级 |
| `/api/model-routes/health` | GET | `X-Internal-Token` | Ollama / DeepSeek / 规则引擎可用性 |

边缘代理（登录态）：

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/model-routes` | GET | 代理 VPS 列表 |
| `/api/model-routes/:task` | PUT / DELETE | 代理更新 / 恢复 |
| `/api/model-routes/reset` | POST | 代理全部恢复 |
| `/api/model-routes/upgrade` | POST | 代理应用升级 |
| `/api/model-routes/health` | GET | 代理健康检查 |

## 6. 运行链路接入

- `summarizer.summarize_with_source()` 先取 `summary` 路由决策：
  - provider=`ollama` → 用决策中的模型名请求 Ollama；超预算 / 不可达时走 DeepSeek；
  - provider=`deepseek` → 跳过 Ollama，直接调用云端；
  - 最终仍保留「截断原文」降级，`SummaryResult.model` 记录实际模型；
- `EmbeddingService` 未显式传 `model_name` 时读取 `embedding` 路由决策（模型 + 量化口径）；配置变更后新建的服务实例生效，已有单例需重启进程；
- 打标 / 分类 / 精排当前是规则引擎，路由层只登记「规则 / LLM」候选，实际调用方后续接入时复用同一决策函数。

## 7. 管理端

新增 `/model-routing` 页面（侧边栏「系统 → 模型路由」）：

- 汇总卡：任务数、本地 / 云端模型数、峰值驻留 / 预算、预算状态；
- 每个任务一张卡：当前模型、策略、驻留、质量分、成本、延迟、回退链、升级建议；
- 操作：切换策略 / 模型并应用、恢复默认、一键应用升级、全部恢复默认；
- Ollama 健康状态与 DeepSeek 配置状态；
- 接口不可用时回退演示数据，保持页面可预览。

## 8. 交付物

| 文件 | 说明 |
| --- | --- |
| `vps/app/services/model_router.py` | 模型目录、任务定义、路由算法、升级建议、配置读写 |
| `vps/app/api/model_routes.py` | 内部路由接口 |
| `vps/app/models.py` | `ModelRouteConfig` 表 |
| `vps/app/schemas.py` | 路由 DTO |
| `vps/app/main.py` | 挂载路由 |
| `vps/app/services/summarizer.py`、`embedding.py` | 接入路由决策 |
| `vps/tests/test_model_router.py` | 纯函数 + API 契约测试 |
| `edge/src/routes/model-routes.ts`、`edge/src/index.ts` | 登录态代理 |
| `edge/scripts/model-routes.test.mjs` | 代理 / 鉴权 / 降级测试 |
| `admin/src/features/model-routing/*`、`routes/_authenticated/model-routing/index.tsx`、`sidebar-data.ts` | 页面、API、工具函数与 Vitest |
| 文档 | 本计划、架构总览、数据模型、backlog、roadmap、task-planning、docs 索引、三端 README |

## 9. 测试与验收

| 层 | 用例 |
| --- | --- |
| VPS 单元 | 任务 / 候选完整性、四种策略、预算过滤、手动超预算拒绝、回退链、升级建议（可用 / 被预算阻塞）、配置合并 |
| VPS 接口 | 列表、更新、非法任务 404、manual 缺模型 400、超预算 400、恢复默认、升级、健康检查 |
| edge | 未登录 401、VPS 未配置 503、GET / PUT / DELETE 代理与内部令牌透传、VPS 错误映射 |
| admin | 预算百分比、驻留 / 成本格式化、策略 / 提供方文案、升级提示、演示数据筛选 |
| 回归 | vps `pytest -q`；edge `npm run typecheck` + `npm test`；admin `npm run lint` + `npm run build` + `npm run test`；`git diff --check` |

验收标准：

1. 管理端能看到 6 个任务的路由、当前模型与预算占用；
2. 切换模型后，摘要 / 向量新任务使用新模型（重启进程后生效），配置持久化；
3. 超预算模型不能被选中，接口返回明确原因；
4. 升级建议能识别「预算内可升级」与「需提高预算」两种情况；
5. 未配置 VPS / 未登录时接口按约定降级，页面回退演示数据；
6. 三端检查全绿，文档同步。

## 10. 风险与边界

- 云端模型成本按目录中的估算单价展示，不做实时账单；`DEEPSEEK_API_KEY` 未配置时云端路由会在运行期降级；
- 切换 embedding 模型可能改变向量维度（bge-m3 1024 / bge-small 512），页面会提示需要重建向量索引；
- 规则引擎任务（打标 / 分类 / 精排）当前不调用 LLM，路由配置先作为后续增强的开关与可观测项；
- 路由配置是节点级（非用户级），符合「个人部署、预算内多模型管理」的定位。
