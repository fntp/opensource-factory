# 实施计划 · REQ-202610-0926 推荐质量评估与调参

> 需求：REQ-202610-0926（backlog M3-08）｜ 分支：`feat/req-202610-0926-quality-eval`
> 依赖：M3-05（每日推荐生成）、M3-07（推荐反馈闭环）。本分支已合并两者的最新实现。

## 1. 目标

为推荐链路补上可重复、离线的质量评估与参数建议能力：

1. **抽样评估集**：从收藏库按固定随机种子切分「画像集 / 留出正样本」，再从热榜采样
   未收藏仓库作为负样本，形成可复现的评估折叠（fold）；
2. **排序指标**：对每个 fold 计算 Precision@K / Recall@K / HitRate / MRR / NDCG@K，
   并统计目录覆盖率、语言多样性与平均返回条数；
3. **阈值调优**：对 `RECOMMEND_MIN_SCORE` 网格 + 相似度 / 热度权重网格做二维扫描，
   按 F1（并列时覆盖率、与当前配置的接近程度）给出推荐参数；
4. **反馈质量**：汇总本地 `recommendations` 状态（saved / dismissed / new / pushed / expired），
   给出收藏率 / 忽略率，作为线上效果旁证；
5. **可解释输出**：报告包含当前参数的实际指标、每个候选参数的指标与推荐理由，
   调参后由运维写入 `.env`，不在请求内静默修改运行配置。

## 2. 现状与缺口

- `generate_recommendations` 只输出 `created / selected / belowThreshold` 等计数，
  无法回答「当前阈值是否合理」「换一组权重会更好吗」；
- 没有留出集（holdout）概念，无法离线衡量排序质量；
- 阈值 / 权重只能人工拍脑袋，缺少网格扫描与对比依据；
- M3-07 已有 `saved` / `dismissed` 状态，但尚未汇总为质量指标。

## 3. 方案

### 3.1 评估服务 `vps/app/services/recommendation_eval.py`

纯计算 + 只读采样，复用 `recommender.rank_candidates` 与 `recommendation_service.ensure_repo_vectors`：

- **评估集构建** `build_eval_samples`：
  - 读取全部 `my_repositories`，按 id 排序后用 `random.Random(seed + fold)` 打乱；
  - 每个 fold 留出 `holdout_ratio`（默认 20%）作为正样本，其余作为画像来源；
  - 负样本从热榜中排除已收藏后采样，每个正样本配 `negatives_per_positive` 条（默认 5）；
  - 向量优先复用 `repo_vectors`，缺失时编码回写；编码失败的仓库跳过并计入 `skipped`；
  - 折叠数默认 5，全部使用确定性种子，保证同输入同结果。
- **指标函数**：`precision_at_k`、`recall_at_k`、`hit_rate_at_k`、`reciprocal_rank_at_k`、
  `ndcg_at_k`、`diversity_at_k`，全部为纯函数，便于单测。
- **参数扫描** `sweep_parameters`：
  - 对每个（相似度权重, 热度权重=1-相似度权重）组合，先对候选打一次分；
  - 再按阈值网格过滤，聚合各 fold 指标；
  - 推荐规则：F1 最大 → 覆盖率最大 → 阈值最接近当前值 → 权重最接近当前值；
  - 无任何正样本入选时保留当前参数并说明原因。
- **反馈汇总** `feedback_metrics`：按 `recommendations.status` 分组计数，
  `saveRate = saved / (saved + dismissed)`，`dismissRate` 同理。
- **入口** `evaluate_recommendation_quality`：返回 camelCase 报告字典，
  数据不足时返回 `status=insufficient_data` 与 `warnings`，不抛异常。

### 3.2 API

`vps/app/api/recommend.py` 新增：

- `POST /api/recommend/eval`：请求体 `RecommendEvalRequest`
  （`sampleSize` / `topK` / `holdoutRatio` / `negativesPerPositive` / `seed` / `userId`），
  返回 `RecommendEvalReport`；参数均有上限，避免误触发大规模编码。

### 3.3 配置

新增（同步 `vps/.env.example`、`deploy/env/openfactory.env.example`、`runtime.REQUIRED_ENV_KEYS`）：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `RECOMMEND_EVAL_SAMPLE_SIZE` | `5` | 默认评估折叠数 |
| `RECOMMEND_EVAL_HOLDOUT_RATIO` | `0.2` | 每个 fold 留出正样本比例 |
| `RECOMMEND_EVAL_TOP_K` | `10` | 评估用 top_k |
| `RECOMMEND_EVAL_NEGATIVES_PER_POSITIVE` | `5` | 每个正样本配的负样本数 |
| `RECOMMEND_EVAL_SEED` | `42` | 抽样随机种子 |
| `RECOMMEND_EVAL_MIN_SCORE_GRID` | `0.20,...,0.50` | 阈值扫描网格 |
| `RECOMMEND_EVAL_WEIGHT_GRID` | `0.6,...,1.0` | 相似度权重扫描网格 |
| `RECOMMEND_EVAL_MAX_SAMPLES` | `20` | 单次请求折叠数上限 |

### 3.4 测试

`vps/tests/test_recommendation_eval.py`：

- 指标纯函数：已知排序的 Precision / Recall / HitRate / MRR / NDCG / 多样性；
- 端到端（hash 兜底向量、临时 SQLite）：种子数据 → 报告状态、数据集计数、阈值行、
  推荐参数落在网格内、同 seed 结果一致；
- 数据不足：空库返回 `insufficient_data`；
- 反馈统计：预置 saved / dismissed / new 行，校验计数与收藏率；
- API：`POST /api/recommend/eval` 200 与非法 `holdoutRatio` 422。

### 3.5 文档

- `vps/README.md`：新增「推荐质量评估（M3-08）」章节与 curl 示例、配置表；
- `docs/architecture/overview.md`：推荐流补充离线评估与调参回路；
- `docs/requirements/backlog.md`：M3-08 标记已交付；
- `docs/planning/task-planning.md`：登记本需求与验证结果。

## 4. 风险与边界

- **单用户口径**：VPS 收藏库仍是单用户镜像，评估集按仓库切分而非按用户切分；
  多用户画像落地后可在同一服务上扩展 `user_id` 维度；
- **留出集泄漏**：正样本仅从画像中剔除，但仍存在于 `my_repositories`；评估时显式不传
  `collected_ids`，确保正样本可被召回；
- **线上偏差**：离线评估基于「收藏即相关」假设，不能完全代表点击 / 收藏行为；
  报告同时给出线上反馈率作为旁证；
- **成本**：向量复用 `repo_vectors`，首次评估可能触发编码；折叠数与候选数均有上限，
  不引入网络调用；
- **不自动改配置**：推荐参数只作为建议返回，避免评估请求隐式改变生产行为。
