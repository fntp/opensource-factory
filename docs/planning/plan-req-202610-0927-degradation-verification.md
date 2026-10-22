# 实施计划 · REQ-202610-0927 降级路径验证（模型缺失 / 超预算 → hash 向量 / 截断摘要）

> 需求：REQ-202610-0927（backlog M3-09）｜ 分支：`feat/req-202610-0927-degradation-verification`
> 依赖：M3-02 向量化管线（REQ-202610-0920）；预算口径来自 M3-01（REQ-202610-0919）
> 目标：把「模型缺失 / 超预算」两类故障的降级行为做成可重复验证的能力，测试全程不依赖模型与网络。

## 1. 现状与缺口

- `EmbeddingService` 已有 hash 兜底（256 维、字符 trigram、L2 归一化），但只在
  `EMBEDDING_FORCE_FALLBACK=true` 或真实模型导入 / 加载失败时触发；
- `summarize()` 已有「Ollama → DeepSeek → 截断原文」降级链，但没有测试覆盖；
- M3-01 已定义模型预算（`MODEL_BUDGET_MB`）与 `model_budget` 选型表，但向量 / 摘要
  服务尚未在加载前检查「配置模型是否超预算」；
- 没有统一的降级自检入口，运维无法一键确认当前环境会走 hash 向量还是真实模型。

## 2. 方案

### 2.1 预算前置检查（模型缺失 / 超预算 → hash 向量）

- 合入 M3-01 的 `app/services/model_budget.py` 与配置项
  （`MODEL_BUDGET_MB` / `EMBEDDING_QUANTIZATION` / `EMBEDDING_DEVICE`）；
- `EmbeddingService._load_backend()` 在导入重型依赖前调用
  `resolve_embedding_spec(model, quantization)`：已收录且 `resident_mb > MODEL_BUDGET_MB`
  时直接走 hash，并记录告警；未收录模型不阻断（保持可配置）；
- 模型缺失（ImportError / 加载异常）继续走既有 hash 降级。

### 2.2 摘要预算前置检查（超预算 → 截断摘要）

- `summarizer._summarize_with_ollama()` 先按 `resolve_llm_spec(OLLAMA_MODEL)` 校验预算，
  超预算直接跳过 Ollama（不发请求），继续 DeepSeek → 截断原文；
- 未配置 Ollama / DeepSeek、请求失败、非 200 均维持既有降级链，不抛异常。

### 2.3 降级自检服务与入口

- 新增 `app/services/degradation.py`：
  - `check_embedding_fallback()`：强制 hash，验证维度 / L2 归一化 / 跨实例确定性 / 余弦合理性；
  - `check_embedding_model_missing()`：模拟真实模型导入失败，确认后端为 `hash`；
  - `check_embedding_over_budget()`：用超预算模型配置，确认不加载模型、直接 hash；
  - `check_summary_truncated()`：无 LLM 配置，确认返回「截断原文」前缀且长度受限；
  - `check_summary_over_budget()`：Ollama 模型超预算，确认跳过请求并返回截断摘要；
  - `run_degradation_checks()`：汇总为结构化报告（PASS / FAIL / SKIP）。
- 新增 `app/degradation.py` CLI：`python -m app.degradation check [--json]`，退出码 0/1；
- 新增内部接口 `GET /api/degradation/status`（`X-Internal-Token`），返回当前配置下的
  后端选择、预算结论与自检结果，便于部署后核对。

### 2.4 测试（不依赖模型 / 网络）

- 新增 `vps/tests/test_degradation.py`：
  - hash 向量确定性、维度、归一化；
  - `sys.modules` 屏蔽 `sentence_transformers` / `FlagEmbedding` → 后端 `hash`；
  - 超预算 embedding 配置 → 后端 `hash`，且不尝试导入模型；
  - 无 Ollama / DeepSeek → 截断摘要前缀与 `max_chars` 边界；
  - Ollama 超预算 → 不发起 HTTP 请求（`httpx.Client` 打桩断言零调用）；
  - 自检报告全 PASS、CLI `--json` 输出与退出码、API 鉴权与响应字段；
  - 向量化管线在 hash 后端下落库 `backend=hash` / `dim=256`（复用既有夹具）。

## 3. 文件清单

- `vps/app/services/degradation.py`（新增）
- `vps/app/degradation.py`（新增 CLI 入口）
- `vps/app/api/degradation.py`（新增内部接口）
- `vps/app/services/embedding.py`、`vps/app/services/summarizer.py`（预算前置检查）
- `vps/app/config.py`、`vps/app/runtime.py`、`vps/.env.example`、`deploy/env/openfactory.env.example`
- `vps/app/services/model_budget.py`、`vps/app/model_budget.py`（随 M3-01 合入）
- `vps/tests/test_degradation.py`（新增）
- `docs/architecture/overview.md`、`docs/requirements/backlog.md`、`docs/planning/task-planning.md`、
  `vps/README.md`、本计划文档

## 4. 验证计划

- `cd vps && bacs-heavy .venv/bin/pytest -q`：全量用例通过（新增降级用例）；
- `cd vps && .venv/bin/python -m app.degradation check`：全 PASS；
- `python -m compileall vps/app`、`git diff --check`；
- `cd edge && npm run typecheck`（未改 edge 契约，回归）；
- `cd admin && npm run lint && npm run build && npm run test`（未改 admin，回归基线）。

## 5. 风险与边界

- 预算值为选型估算，生产以 M5-06 实测 RSS 为准；`MODEL_BUDGET_MB` 可调；
- 未收录模型不做预算阻断，避免自定义模型被误降级；
- 本需求只验证「模型缺失 / 超预算」两类降级，不覆盖网络抖动、向量维度漂移等场景；
- hash 向量仅反映字符 trigram 相似度，生产仍应使用 BGE-M3；本需求不改变默认选型。
