# M3 验收与回顾（REQ-202610-0929）

> 验收日期：2026-10-22 ｜ 分支：`feat/req-202610-0929-m3-acceptance`
>
> 关联需求：`docs/requirements/backlog.md` · M3-11（M3 · 推荐引擎）｜ 依赖：M3-01~09
>
> 自动报告：`acceptance-m3-report.md` / `acceptance-m3-report.json`（由 `vps/scripts/m3_acceptance.py` 生成）

## 1. 结论

M3-01~M3-10 已全部集成到验收分支，跨分支端到端验收 **23/23 PASS**，
三端检查全部通过：

| 检查 | 结果 |
| --- | --- |
| VPS pytest | **233 passed**（10 warnings，无失败） |
| Edge `tsc --noEmit` | 通过 |
| Edge `node --test scripts/*.test.mjs` | **27 passed** |
| Admin `eslint .` | 通过 |
| Admin `tsc -b && vite build` | 通过（3982 modules） |
| Admin Vitest（headless） | **92 passed**（14 files） |
| M3 验收脚本 | **23 PASS / 0 GAP / 0 FAIL / 0 SKIP** |

验收环境：Linux x86_64 · Python 3.12.3 · Node（edge/admin 依赖本地安装）·
临时 SQLite + 本地 mock edge（Vectorize / 推荐反馈契约）· `EMBEDDING_FORCE_FALLBACK=1`。

## 2. 验收矩阵

| 编号 | 能力 | 验收方式 | 结果 |
| --- | --- | --- | --- |
| M3-01 | 模型选型与 2G 预算 | `python -m app.model_budget check --json`：bge-m3 int8 1100MB、LLM 1300MB，峰值 1300/2048MB | PASS |
| M3-02 | 向量化管线 | 全量向量化 20 条（my 8 / trending 12），统计 / 单条详情 / 增量跳过 | PASS |
| M3-03 | Vectorize 索引同步 | mock edge upsert 20 条分 3 批；二次同步 skipped=20；对账 checked=20 / missing=0 / stale=0 | PASS |
| M3-04 | 语义搜索 | 查询命中支付项目、结果水合（描述 / 理由 / 链接）、scope / topK 过滤、状态接口 | PASS |
| M3-05 | 每日推荐 | 推荐任务生成 10 条并落库，排除已收藏 / 已忽略 | PASS |
| M3-06 | 推荐理由 | 每条推荐含中文理由与 `based_on`；即时推荐接口同样返回 | PASS |
| M3-07 | 反馈闭环 | mock 反馈拉取 1 次，saved/dismissed 排除，生成后回写 10 条且 `basedOn` 完整 | PASS |
| M3-08 | 质量评估 | `POST /api/recommend/eval`：3 个折叠、8 项指标、阈值 / 权重扫描、调参建议 | PASS |
| M3-09 | 降级路径 | `GET /api/degradation/status` 5 项全 PASS；CLI `python -m app.degradation check --json` exit 0 | PASS |
| M3-10 | 查询理解 | 识别 React / 前端 / frontend；`expand=false` 保持原查询；embed 返回 understanding | PASS |
| M3-11 | 验收与回顾 | 本文件 + 计划文档 + 自动报告 + 三端检查 | PASS |

## 3. 集成修复记录

本轮合并 0919~0928 十个分支时发现并修复：

1. **`SummaryQualitySample` 模型丢失**：M3 分支合并后 `vps/app/models.py` 缺少 M2-04 的
   摘要质量抽检模型，导致 `app.api.summaries` / `app.services.summary_quality` 导入失败、
   `uvicorn` 无法启动。已按 M2-04 原始定义补回。
2. **推荐理由回填任务引用未定义变量**：`regenerate_recommendation_reasons` 中残留
   `target_users` / `pushed` 循环，运行即 `NameError`；已改为按推荐所属用户回写 edge，
   并在返回值中返回 `pushed` 统计。
3. **推荐汇总缺少 `feedbackExcluded`**：M3-07 反馈测试期望任务返回每个用户被排除的
   反馈数量；已在 `generate_daily_recommendations` 汇总中补充。
4. **测试库表结构串扰**：`test_vector_index.py` 用简化版 `repo_vectors` 表做隔离，
   用例结束后未恢复，导致后续 `test_vector_pipeline` 缺 `created_at` 列；已在 fixture
   结束时删除简化表并 `init_db()` 重建完整模型表。
5. **测试替身契约漂移**：`test_recommend_job.py` 的 `FakeEmbedding` 缺少 M3-02 所需的
   `model_name` / `backend` 属性；已补齐，避免推荐生成在测试中降级为 error。
6. **M3-05 旧断言与 M3-07 行为冲突**：反馈闭环会把 dismissed 仓库排除出候选，
   因此第二轮生成不再刷新该行；已更新断言为 `updated == 0`，并保留“状态不被覆盖 /
   旧 new 推荐过期”的检查。
7. 合并过程中另清理了重复 `VectorSyncRequest`、`REQUIRED_ENV_KEYS` 漂移、
   `config.py` 重复配置块、`docs/architecture/overview.md` 代码围栏错位等问题。

## 4. 性能抽样

| 场景 | 样本数 | P50 | P95 | Max | 预算 |
| --- | --- | --- | --- | --- | --- |
| `/api/search/query` | 30 | 9.3ms | 13.4ms | 15.4ms | P95 < 500ms |
| `/api/recommend/list?user_id=2001&limit=50` | 30 | 8.0ms | 9.7ms | 10.5ms | P95 < 300ms |

本机为 hash 兜底向量（256 维），性能数据仅代表本地 SQLite + 纯计算路径；
真实 BGE-M3 / Vectorize 的延迟需在生产环境复测。

## 5. 回顾

### 做得好的

- 按依赖顺序合并，先 M3-01/02 基础层，再 03/04 检索层，最后 05~10 推荐与增强层，
  冲突集中在配置 / schema / 文档，业务实现基本保持独立。
- 验收脚本用真实 HTTP + 临时数据库 + mock edge，不依赖外网与重型模型，可在 CI 重复执行；
  M3-03 的批量 / 幂等 / 对账和 M3-07 的反馈闭环都通过 mock 契约得到覆盖。
- 降级路径（hash 向量、截断摘要）在无模型环境仍可完成全链路验收，符合 2G 预算设计目标。

### 需要改进的

- 多分支并行修改 `models.py` / `config.py` / `schemas.py` 时，合并后必须跑一次完整
  `pytest` + 应用启动冒烟；本次 `SummaryQualitySample` 丢失属于“测试未覆盖 app 导入”的盲区。
- 测试模块间共用同一个 SQLite 文件，容易出现表结构串扰；后续可考虑按模块隔离数据库，
  或在 fixture 中统一恢复 `Base.metadata` 全量表。
- 推荐评估在合成数据上的 F1 较低（0.19），属于小样本 / hash 向量下的预期结果；
  真实数据接入后应以线上反馈指标为准，不能直接据此调参。

## 6. 复跑方式

```bash
# VPS：完整测试 + M3 验收（在 vps/ 下，使用项目 venv）
pytest -q
python scripts/m3_acceptance.py --strict \
  --report-md docs/planning/acceptance-m3-report.md \
  --report-json docs/planning/acceptance-m3-report.json

# Edge
cd edge && npm ci && npm run typecheck && npm test

# Admin
cd admin && npm ci && npm run lint && npm run build && npm test
```

## 7. 遗留事项

- 真实 BGE-M3（1024 维）与 Ollama 模型未在本机加载；生产部署后需用真实模型复跑
  M3-02 / M3-04 / M3-05 的覆盖率与延迟抽样。
- 真实 Cloudflare Vectorize / edge 生产环境未联调；mock 已覆盖 upsert / check / stats /
  delete 契约，上线前需在预发环境做一次真实索引同步与对账。
- 推荐质量评估目前基于合成数据；接入真实收藏 / 点击反馈后需重新建立评估基线。
