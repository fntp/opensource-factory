# 实施计划 · REQ-202610-0912 中文摘要批量生成（含质量抽检机制）

> 需求：REQ-202610-0912（backlog M2-04）｜ 分支：`feat/req-202610-0912-summary-quality`
> 依赖：M1-13 / REQ-202610-0905（README 摘要批量管线，本分支基于其交付分支）
> 备注：抽检样本留存评估

## 1. 目标

在 M1-13 已完成的「同步 → README 清洗 → 中文摘要 → 本地落库 → D1 回写」基础上，补齐 M2 阶段的两块能力：

1. **摘要覆盖热榜仓库**：批量摘要不再只处理 `my_repositories`，同时支持 `trending_repositories`；热榜抓取完成后自动入队摘要任务，摘要回写 D1，供 M2-07 热榜详情页直接使用。
2. **质量抽检机制**：按可配置比例确定性抽样（同一次任务重跑样本稳定），并强制留存低质量样本；样本落 `summary_quality_samples` 表，附带自动质量评分与检查明细，支持人工复核（通过 / 不通过）与质量统计，用于「抽检样本留存评估」。

## 2. 现状与缺口

- `summary_pipeline.summarize_repositories()` 只查询 `MyRepository`，热榜仓库没有摘要生成路径；
- `trending_repositories`（本地 + D1）没有 `readme_summary` 列，edge `/api/trending` 不返回摘要；
- 摘要生成后只有统计计数，没有样本留存、质量评分与人工复核记录；
- `crawl_trending` 抓取完成后不触发摘要，热榜摘要只能靠人工补跑。

## 3. 方案

### 3.1 数据模型

**本地 SQLite（SQLAlchemy）**

- `trending_repositories` 增加 `readme_summary TEXT`；
- 新增 `summary_quality_samples`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | 样本 id（uuid hex） |
| batch_id | TEXT | 批次 id（Celery task id 或手动批次） |
| repo_id | TEXT | 仓库 id（owner/repo） |
| repo_source | TEXT | `my` / `trending` |
| summary | TEXT | 被抽检的摘要全文 |
| source | TEXT | `ollama` / `deepseek` / `truncated` / `empty` |
| model | TEXT | 生成模型 |
| max_chars | INTEGER | 生成长度上限 |
| score | REAL | 自动质量分 0~100 |
| verdict | TEXT | `pass` / `fail` |
| checks | TEXT | 检查明细 JSON |
| status | TEXT | `pending` / `passed` / `failed`（人工复核状态） |
| reviewer / review_note | TEXT | 复核人 / 备注 |
| reviewed_at | DATETIME | 复核时间 |
| created_at | DATETIME | 抽样时间 |

索引：`(batch_id)` 供批次查询；`(batch_id, repo_source, repo_id)` 唯一，保证重跑不重复留存（同仓库跨来源各留一条）。

**D1（edge 迁移 0007）**

- `trending_repositories` 增加 `readme_summary TEXT`（`ALTER TABLE`，幂等靠迁移只执行一次）。

### 3.2 质量评分（`summary_quality.py`）

纯函数 `evaluate_summary(summary, *, max_chars, source)` 输出 `score`、`verdict`、`checks`：

| 检查项 | 权重 | 说明 |
| --- | --- | --- |
| non_empty | 15（关键） | 长度 ≥ 20，空摘要直接不通过 |
| length | 15 | 40 ≤ 长度 ≤ `max_chars`（允许 10% 余量） |
| chinese | 25（关键） | 中文字符占非空白字符 ≥ 30%（技术名词英文不扣分） |
| coverage | 20 | 功能 / 技术栈 / 适用场景三组关键词至少覆盖两组 |
| no_fallback | 15（关键） | 来源不是 `truncated`，且不含「LLM 暂不可用」 |
| no_noise | 5 | 不含代码围栏、Markdown 图片 / HTML 图片 |
| not_repetitive | 5 | 10 字符滑窗重复率 ≤ 25% |

- 关键项失败：`verdict=fail` 且总分封顶 40；
- 否则 `score >= SUMMARY_QUALITY_PASS_SCORE`（默认 70）为 `pass`。

### 3.3 抽样策略

- 确定性哈希：`sha256(f"{batch_id}:{repo_source}:{repo_id}")` 映射到 `[0,1)`，小于 `SUMMARY_SAMPLE_RATE`（默认 0.1）即抽样；
- **低质量强制留存**：`score < SUMMARY_SAMPLE_ALWAYS_BELOW`（默认 60）的样本无条件抽样；
- 单次任务最多留存 `SUMMARY_SAMPLE_MAX_PER_RUN`（默认 50）条，避免样本表膨胀；
- 同一 `(batch_id, repo_source, repo_id)` 重跑只更新，不新增。

### 3.4 批量管线

`summarize_repositories(..., source="my" | "trending" | "all")`：

- `my`：沿用现有 `MyRepository` 选择与 `/api/repos/summaries` 回写；
- `trending`：按 `stars_today DESC` 选择摘要为空的 `TrendingRepository`，回写 `/api/trending/summaries`；
- `all`：先 `my` 后 `trending` 串行执行（不并行，遵守 2G 预算）；
- 每条成功摘要后调用质量评分与抽样，统计增加 `sampled`、`quality`（平均分 / 通过 / 不通过 / 待复核）；
- Celery 任务 `summarize_readmes` 增加 `source` 参数，批次 id 使用 `self.request.id`。

`crawl_trending` 增加 `with_summary=True`：抓取 upsert 后把本次变化的热榜仓库入队 `summarize_readmes(source="trending", repo_ids=...)`，返回 `summaryTaskId`。

### 3.5 API

VPS（内部 token，沿用 `X-Internal-Token`）：

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/tasks/summarize?source=my\|trending\|all` | POST | 入队摘要任务（新增 source 参数） |
| `/api/trending/summarize` | POST | 热榜摘要入队便捷别名 |
| `/api/summaries/quality/samples` | GET | 抽检样本列表（status / repoSource / batchId / limit / offset） |
| `/api/summaries/quality/samples/{id}/review` | POST | 人工复核：`{result: passed\|failed, reviewer?, note?}` |
| `/api/summaries/quality/stats` | GET | 质量统计（总数 / 待复核 / 通过率 / 平均分 / 来源分布 / 最近批次） |
| `/api/summaries/quality/sample-existing` | POST | 对存量摘要补抽样（用于历史数据评估） |

edge：

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/trending` | GET | 返回 `summary` 字段（`readme_summary`） |
| `/api/trending/summaries` | POST | VPS 批量回写热榜摘要（内部 token，单批 ≤ 500） |

### 3.6 配置

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `SUMMARY_SAMPLE_RATE` | 0.1 | 常规抽样比例（0~1） |
| `SUMMARY_SAMPLE_MAX_PER_RUN` | 50 | 单次任务最多留存样本数 |
| `SUMMARY_SAMPLE_ALWAYS_BELOW` | 60 | 低于该分数强制留存 |
| `SUMMARY_QUALITY_PASS_SCORE` | 70 | 自动判定通过线 |
| `SUMMARY_QUALITY_MIN_CHARS` | 40 | 摘要最小长度 |

## 4. 文件清单

- `vps/app/services/summary_quality.py`（新增：评分 / 抽样 / 样本落库）
- `vps/app/services/summary_pipeline.py`（多来源批量摘要 + 抽样接入）
- `vps/app/models.py`、`vps/app/db.py`（热榜摘要列、样本表、旧库幂等补列）
- `vps/app/config.py`、`vps/.env.example`（抽样与质量阈值）
- `vps/app/tasks/jobs.py`（source 参数、crawl_trending 自动入队）
- `vps/app/api/summaries.py`（新增质量抽样 API）、`vps/app/api/tasks.py`、`vps/app/api/trending.py`、`vps/app/main.py`
- `vps/app/schemas.py`（样本 / 统计出参）
- `vps/tests/test_summary_quality.py`（新增：评分 / 抽样 / 样本去重 / 补抽样 / 多来源管线 / 质量 API）
- `edge/migrations/0007_trending_summary.sql`、`docs/assets/d1-schema.sql`
- `edge/src/types.ts`、`edge/src/routes/trending.ts`
- 文档：`docs/architecture/overview.md`、`docs/architecture/data-model.md`、`docs/requirements/backlog.md`、`docs/planning/task-planning.md`、`docs/README.md`、`vps/README.md`、`edge/README.md`、本计划

## 5. 验证计划

- `cd vps && .venv/bin/pytest -q`：新增评分、抽样、样本复核、多来源批量、API 用例，全部通过；
- `cd edge && npm run typecheck`：0 error；
- `cd admin && npm run lint && npm run build && npm run test`：基线通过（本需求不改 admin）；
- `git diff --check`；确认无密钥入库。

## 6. 边界与待人工事项

1. 本需求不改变模型选型（M3-01 仍待定），沿用 `OLLAMA_MODEL` 与降级链；
2. 质量评分是启发式规则，不替代人工复核；样本列表暂以内部 API 提供，admin 可视化页面可在后续需求接入；
3. 热榜摘要回写依赖 edge 迁移 0007 与 `INTERNAL_TOKEN` 配置；
4. 抽检比例与阈值均为可配置项，上线后可按样本评估结果调整。
