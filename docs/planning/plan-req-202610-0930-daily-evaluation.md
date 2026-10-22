# 实施计划 · REQ-202610-0930 每日评估任务（质量分 + 匹配度阈值）

> 需求：REQ-202610-0930（backlog M4-01）｜ 分支：`feat/req-202610-0930-daily-evaluation`
> 依赖：M3-05 每日推荐生成任务（REQ-202610-0923）
> 目标：每天对生成的推荐做一次统一评估，输出可解释的质量分，并按匹配度阈值筛出可推送项，为 M4-02 站内通知中心提供稳定输入。

## 1. 现状与缺口

- M3-05 已实现每日 08:30 生成推荐：`Recommendation` 落库，保存综合 `score`、中文 `reason`，状态为 `new`；
- 现有 `daily_push`（09:00）只是占位：直接把 `new` 按分数取前 N 条改成 `pushed`，没有质量评估，也没有匹配度门槛；
- `Recommendation` 只保存综合分，未保留原始余弦相似度，无法区分「热度高」与「真的匹配」；
- 没有评估运行记录，无法回答「今天评估了多少条、多少条合格、为什么被过滤」。

## 2. 方案总览

```
08:30 生成推荐（M3-05） → Recommendation(status=new, match_score=余弦相似度)
08:45 每日评估（本需求）
        ├─ 读取 new / qualified / filtered 推荐
        ├─ 计算质量分 = 仓库质量 × 0.7 + 理由质量 × 0.3
        ├─ 双重门槛：match_score ≥ EVAL_MATCH_THRESHOLD 且 quality_score ≥ EVAL_QUALITY_THRESHOLD
        ├─ 合格 → status=qualified；不合格 → status=filtered
        └─ 写入 recommendation_evaluation_runs（运行统计 / 阈值 / 错误）
09:00 推送准备 → 只把 qualified 标记为 pushed（M4-02 负责真正下发）
```

状态生命周期：

| 状态 | 含义 | 由谁写入 |
| --- | --- | --- |
| `new` | 当日新生成、待评估 | M3-05 生成任务 |
| `qualified` | 通过质量分 + 匹配度门槛，可推送 | 本需求评估任务 |
| `filtered` | 未通过评估（低匹配 / 低质量） | 本需求评估任务 |
| `pushed` | 已进入推送流程 | 推送准备任务 |
| `saved` / `dismissed` | 用户反馈，评估与生成都不得覆盖 | 用户操作 |
| `expired` | 当日未入选或已收藏 | M3-05 生成任务 |

重新生成时，`new / qualified / filtered / expired` 均可被重置为 `new` 并重新评估；
`saved / dismissed / pushed` 保留用户 / 推送语义。

## 3. 质量分口径

### 3.1 两个分量（匹配度单独作硬门槛）

| 分量 | 取值 | 说明 |
| --- | --- | --- |
| `match` | 0~1 | 原始余弦相似度；生成时写入 `Recommendation.match_score`，历史数据缺失时回退到综合 `score`。只参与 `EVAL_MATCH_THRESHOLD` 硬门槛，不混入质量分 |
| `repo` | 0~1 | 仓库内容质量：名称 0.05、简介完整度 0.35、技术栈 0.25、今日 Star 0.25、README 摘要 0.10、语言 0.05（字段缺失的项按 0 计，总分封顶 1） |
| `reason` | 0~1 | 推荐理由质量：非空基础分 0.35、长度分档（≥30 / ≥60 / ≥100 字）、是否含相似度 / 语言 / 技术栈 / 简介等依据 |

### 3.2 综合质量分

```
quality = repo × EVAL_REPO_WEIGHT + reason × EVAL_REASON_WEIGHT
```

默认权重 `0.7 / 0.3`，默认门槛：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `EVAL_MATCH_THRESHOLD` | 0.35 | 匹配度硬门槛，低于该值直接 `filtered` |
| `EVAL_QUALITY_THRESHOLD` | 0.55 | 综合质量分门槛 |
| `EVAL_REPO_WEIGHT` | 0.7 | 仓库质量权重 |
| `EVAL_REASON_WEIGHT` | 0.3 | 理由质量权重 |

`quality_detail` 以 JSON 保存各分量、阈值与是否通过，便于排障与后续调参。

## 4. 数据模型

### 4.1 `recommendations` 扩展列（VPS SQLite）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `match_score` | REAL | 原始余弦相似度（0~1） |
| `quality_score` | REAL | 评估后的综合质量分（0~1） |
| `quality_detail` | TEXT | 评估明细 JSON |
| `evaluation_run_id` | TEXT | 最近一次评估运行 id |
| `evaluated_at` | DATETIME | 最近一次评估时间 |

`init_db` 对旧 SQLite 库做幂等补列（`ALTER TABLE ... ADD COLUMN`），不要求手工迁移。

### 4.2 `recommendation_evaluation_runs`（新增）

| 字段 | 说明 |
| --- | --- |
| `id` TEXT PK | 运行 id（UUID hex） |
| `user_id` TEXT | 目标用户；NULL 表示全部用户 |
| `status` TEXT | `running` / `completed` / `failed` |
| `match_threshold` / `quality_threshold` | 本次运行阈值 |
| `total` / `qualified` / `filtered` / `skipped` / `failed` | 计数 |
| `error` TEXT | 失败原因（截断） |
| `created_at` / `finished_at` | 时间 |

## 5. 接口

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/tasks/evaluate-recommendations` | POST | 入队评估任务（`user_id` / `match_threshold` / `quality_threshold` 可选，内部令牌鉴权） |
| `/api/recommend/evaluate` | POST | 同上便捷别名 |
| `/api/recommend/evaluations` | GET | 最近评估运行列表（`limit` 默认 20） |
| `/api/recommend/evaluations/{runId}` | GET | 单次运行详情 |
| `/api/recommend/qualified` | GET | 查询通过评估的推荐（`user_id` / `limit`），供 M4-02 通知中心消费 |

## 6. 文件清单

- `vps/app/models.py`：Recommendation 扩展列 + `RecommendationEvaluationRun`
- `vps/app/db.py`：旧 SQLite 幂等补列
- `vps/app/services/recommendation_eval.py`（新增）：质量分纯函数、单用户 / 全量评估、运行记录
- `vps/app/services/recommendation_service.py`：生成时写入 `match_score`，重置评估状态
- `vps/app/tasks/jobs.py`：`evaluate_recommendations` 任务；`daily_push` 只推送 `qualified`
- `vps/app/tasks/celery_app.py`：每日 08:45 评估计划
- `vps/app/api/tasks.py`、`vps/app/api/recommend.py`、`vps/app/schemas.py`：入队与查询接口
- `vps/app/config.py`、`vps/app/runtime.py`、`vps/.env.example`、`deploy/env/openfactory.env.example`：4 个 `EVAL_*` 配置项
- `vps/tests/test_recommendation_eval.py`（新增）：纯函数、门槛、状态、幂等、运行记录、迁移补列、任务与 API
- 文档：`docs/architecture/{overview,data-model}.md`、`docs/requirements/{backlog,open-questions}.md`、`docs/planning/task-planning.md`、`vps/README.md`

## 7. 验证计划

- `cd vps && .venv/bin/pytest -q`：质量分纯函数、双重门槛、状态保留、幂等重跑、运行记录、API、Celery 任务；
- `cd edge && npm run typecheck`：确认未破坏 edge 契约（本需求不改 edge）；
- `cd admin && npm run lint && npm run build && npm run test`：回归；
- `python -m compileall vps/app`、`git diff --check`。

## 8. 风险与边界

- 本需求只做 VPS 评估与状态流转；站内通知中心（M4-02）负责 edge / admin 展示与真实下发；
- 历史推荐没有 `match_score` 时回退到综合 `score`，属于保守近似，下一次生成后自动补齐；
- 质量分为规则口径，阈值需在 M4 验收时用真实样本复核；已配置化，无需改代码；
- 评估只处理 `new / qualified / filtered`，不触碰 `saved / dismissed / pushed / expired`；
- 单用户失败不拖垮整轮评估，运行记录保留错误摘要。
