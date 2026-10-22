# 实施计划 · REQ-202610-0967 个人数据微调评估（LoRA 可行性）

> 需求：REQ-202610-0967（backlog M7-08）｜ 分支：`feat/req-202610-0967-lora-evaluation`
> 依赖：M7-06 模型路由与升级（REQ-202610-0965）
> 目标：对「用个人收藏 / 摘要 / 反馈数据做 LoRA 微调」给出**预算**与**效果**双评估，形成可复跑的评估工具和明确的实施结论，而不是只写一份主观判断。

## 1. 现状与约束

- 本机 AI 推理预算固定为 **2G**（`docs/planning/resource-plan.md` §3），同一时刻只加载 1 个模型；
- 默认摘要模型 `qwen2.5:1.5b-instruct-q4_K_M`（约 1.3G），默认向量模型 `BAAI/bge-m3` int8（约 1.1G）；
- 本机无独立 GPU，`vps/requirements.txt` 不含 torch；`requirements-ml.txt` 仅用于可选的重型 ML 依赖；
- 个人数据（收藏、README 摘要、分类、标签、推荐反馈）全部在本机 SQLite，适合做私有微调，但当前运行库尚未导入收藏（0 条）；
- M7-06 的目标是建立「按任务选择模型」的路由边界：微调产物应作为可选模型注册到路由层，而不是替换默认模型。

## 2. 评估问题拆解

| # | 问题 | 产出 |
| --- | --- | --- |
| 1 | 个人数据够不够训 LoRA | 数据画像与最低 / 推荐样本量门槛 |
| 2 | 本机能不能训 | 训练显存 / 时长 / 预算判定 |
| 3 | 云端训一次要多少钱 | 不同模型 × GPU × 样本量的成本矩阵 |
| 4 | 训完能不能在本机跑 | 量化后推理驻留是否 ≤ 2G |
| 5 | 效果怎么证明 | 留出集 + 盲评 + 显著性检验的评测协议 |
| 6 | 现在做不做 | 决策矩阵与触发条件 |

## 3. 实现方案

### 3.1 评估工具（新增）

`vps/app/services/lora_eval.py`（仅标准库，不依赖 torch / GPU，可在任意机器复跑）：

- `MODEL_CATALOG`：候选底座模型（Qwen2.5-1.5B / 3B / 7B、Llama 3.1-8B）的 QLoRA 训练显存、q4 推理驻留、适配器体积；
- `GPU_CATALOG`：本机 CPU、RTX 4090 24G、A100 40G / 80G 的显存、时价与训练吞吐；
- `estimate_training(config)`：按样本数 × 平均 token × epoch 估算 token 总量、训练步数、GPU 小时、费用、可训练参数与存储；
- `assess_dataset(repos, summaries, feedback_pairs)`：可用样本量 = 摘要样本 + 反馈偏好对，分 `insufficient / minimum / recommended` 三档；
- `compare_effect(baseline, tuned)`：配对评分对比，输出均值差、胜 / 平 / 负、胜率与精确二项符号检验 p 值；
- `build_feasibility_report(...)`：汇总场景、云端试验预算、本机训练 / 推理可行性、效果证据与最终决策；
- CLI：
  ```bash
  cd vps
  .venv/bin/python -m app.lora_eval report
  .venv/bin/python -m app.lora_eval report --db data/opensource_factory.db --feedback 20
  .venv/bin/python -m app.lora_eval report --repos 120 --summaries 80 --feedback 20 --json
  .venv/bin/python -m app.lora_eval compare --baseline baseline.json --tuned tuned.json
  ```

### 3.2 评估报告（新增）

`docs/architecture/lora-finetuning-evaluation.md`：

- 数据画像与隐私边界；
- LoRA / QLoRA 技术路线与底座选型；
- 预算矩阵（本机 / 云端训练 / 本机推理 / 存储）；
- 效果评测协议（任务、指标、样本量、显著性门槛）；
- 决策矩阵、结论与触发条件；
- 复跑方式与参数口径，数值与 `lora_eval.py` 常量保持一致。

### 3.3 文档同步

- `docs/README.md` 增加评估报告与计划入口；
- `docs/planning/roadmap.md` 勾选 M7-08；
- `docs/planning/task-planning.md` 新增 IT-0051 与交付记录；
- `docs/requirements/backlog.md` 标注 M7-08 完成；
- `docs/requirements/open-questions.md` 新增 Q29（底座模型 / 数据授权 / 云端 GPU 供应商待确认）。

## 4. 文件清单

- 新增 `vps/app/services/lora_eval.py`（评估逻辑）
- 新增 `vps/app/lora_eval.py`（`python -m app.lora_eval` CLI 入口转发）
- 新增 `vps/tests/test_lora_eval.py`
- 新增 `docs/planning/plan-req-202610-0967-lora-evaluation.md`（本文件）
- 新增 `docs/architecture/lora-finetuning-evaluation.md`
- 修改 `docs/README.md`、`docs/planning/roadmap.md`、`docs/planning/task-planning.md`、`docs/requirements/backlog.md`、`docs/requirements/open-questions.md`

## 5. 验证计划

```bash
cd vps && .venv/bin/pytest -q tests/test_lora_eval.py
cd vps && .venv/bin/pytest -q
cd vps && .venv/bin/python -m app.lora_eval report
cd vps && .venv/bin/python -m app.lora_eval report --json
git diff --check
```

## 6. 边界

- 本需求**不实际训练模型、不引入 GPU 依赖、不改变默认模型路由**；产出是可复跑的评估工具与决策报告；
- 预算数字为 2026-10 公开云 GPU 时价的量级估算，下单前需按实际供应商报价复核；
- 效果评估需要真实留出集；没有实测数据时报告只给评测协议与门槛，不编造提升幅度。
