# 实施计划 · REQ-202610-0919 模型选型与 2G 预算验证

> 需求：REQ-202610-0919（backlog M3-01）｜ 分支：`feat/req-202610-0919-model-selection`
> 目标：把默认模型从超预算的 `qwen2.5:7b` 切换为 ≤2B 量化模型，明确 bge-m3 的 int8 量化口径，并提供可复跑的 2G 推理预算校验。

## 1. 现状与缺口

- `vps/app/config.py` 与两份 `.env` 模板默认 `OLLAMA_MODEL=qwen2.5:7b`（q4 约 4.7G），超出 resource-plan §3 的 2G 推理预算；
- `EMBEDDING_MODEL=BAAI/bge-m3` 未标注量化口径，fp16 / fp32 权重约 2.3G，同样超预算；
- 代码没有「模型驻留内存」的统一口径，也没有可执行的预算校验入口，部署后只能靠人工估算；
- 摘要 / 向量化降级链已存在，但缺少对「当前配置是否在预算内」的自动化断言。

## 2. 选型结论

| 用途 | 选中模型 | 量化 | 估算驻留 | 估算磁盘 | 说明 |
| --- | --- | --- | --- | --- | --- |
| Embedding（首选） | `BAAI/bge-m3` | int8（ONNX / 动态量化） | ~1.1 GB | ~1.2 GB | 1024 维；fp16 约 2.3G，禁用为默认 |
| Embedding（降级） | `BAAI/bge-small-zh-v1.5` | fp32 | ~0.3 GB | ~0.1 GB | 超预算或模型缺失时切换 |
| LLM 摘要（首选） | `qwen2.5:1.5b-instruct-q4_K_M` | q4_K_M | ~1.3 GB | ~1.0 GB | ≤2B；中文摘要默认 |
| LLM 备选 | `deepseek-r1:1.5b` | q4_K_M | ~1.4 GB | ~1.1 GB | 推理型，较慢 |
| 不默认 | `qwen2.5:7b` / `deepseek-r1:7b` | q4 | ~4.7 GB | ~4.7 GB | 超预算，仅按需人工启用 |

约束口径：同一时刻仅加载 1 个模型，**峰值驻留 = max(embedding, llm) ≤ 2048 MB**；两个模型分队列串行执行，不叠加。

## 3. 实现方案

### 3.1 模型预算模块（新增）

`vps/app/services/model_budget.py`（仅标准库，可在未安装应用依赖时运行）：

- `MODEL_CATALOG`：收录上述模型及其 `resident_mb` / `disk_mb` / 维度 / 量化口径；
- `build_model_budget_report(embedding_model, ollama_model, embedding_quantization, budget_mb)`：
  - 归一化模型名（大小写、`_` / `-`、Ollama tag）；
  - bge-m3 按量化口径选择 int8 / fp16 规格；
  - 输出逐项检查、峰值驻留、预算占比与是否通过；
- `probe_ollama(base_url, budget_mb)`：可选实时探测 `/api/ps`，校验已加载模型的 `size` / `size_vram`；
- CLI：`python -m app.model_budget check [--probe] [--json]`，预算内退出码 0，超预算 / 未识别模型退出码 1。

### 3.2 默认配置切换

- `Settings.OLLAMA_MODEL` 默认改为 `qwen2.5:1.5b-instruct-q4_K_M`；
- 新增 `EMBEDDING_QUANTIZATION`（默认 `int8`）、`EMBEDDING_DEVICE`（默认 `cpu`）、`MODEL_BUDGET_MB`（默认 `2048`）；
- 同步 `vps/.env.example`、`deploy/env/openfactory.env.example`、`vps/app/runtime.py` 的 `REQUIRED_ENV_KEYS`；
- 向量服务按 `EMBEDDING_DEVICE` 加载，int8 时对 Linear 层做动态量化，CPU 上不使用 fp16。

### 3.3 部署自检

- `app.runtime.check` 增加 `model_budget` 检查项：识别的模型超预算即失败；未识别模型（如测试占位值）跳过；
- `deploy/scripts/doctor.sh` 因此自动覆盖模型预算检查；
- 文档补充 `python -m app.model_budget check --probe` 的用法。

### 3.4 测试

`vps/tests/test_model_budget.py`：

- 默认选型通过 2048 MB 预算；
- 旧默认 `qwen2.5:7b` 被判定超预算；
- bge-m3 fp16 被判定超预算，int8 通过；
- 未知模型判定为不可验证（失败）；
- 两份 `.env` 模板与 Settings 默认值一致且在预算内；
- CLI `--json` / 超预算退出码；
- `probe_ollama` 用 `httpx.MockTransport` 覆盖正常 / 不可达，不访问网络。

## 4. 文件清单

- 新增 `vps/app/services/model_budget.py`
- 新增 `vps/tests/test_model_budget.py`
- 修改 `vps/app/config.py`、`vps/app/runtime.py`、`vps/app/services/embedding.py`
- 修改 `vps/.env.example`、`deploy/env/openfactory.env.example`
- 文档：`vps/README.md`、`docs/planning/resource-plan.md`、`docs/planning/roadmap.md`、`docs/planning/task-planning.md`、`docs/requirements/backlog.md`、`docs/architecture/overview.md`、`docs/guides/deployment-baseline.md`、本计划

## 5. 验证计划

```bash
cd vps && .venv/bin/pytest -q
cd vps && .venv/bin/python -m app.model_budget check
cd vps && .venv/bin/python -m app.model_budget check --json
cd edge && npm run typecheck
cd admin && npm run lint && npm run build && npm run test
git diff --check
```

## 6. 风险与边界

- 预算值为选型阶段估算（权重 + 运行时开销），M5-06 资源实测时按实际 RSS 复核；
- int8 动态量化在 CPU 上生效，加载峰值仍可能短暂高于稳态；生产建议使用预量化 ONNX 权重；
- 实时 `--probe` 依赖本机 Ollama；未启动时只做离线预算校验，不影响降级链；
- 本需求不实现向量化管线（M3-02）与 Vectorize 同步（M3-03）。
