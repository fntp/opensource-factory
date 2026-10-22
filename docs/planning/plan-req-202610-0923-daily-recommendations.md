# 实施计划 · REQ-202610-0923 每日推荐生成任务（阈值 / 去重已收藏 / 打分）

> 需求：REQ-202610-0923（backlog M3-05）｜ 分支：`feat/req-202610-0923-daily-recommendations`
> 依赖：M3-02 向量化管线（本地 `repo_vectors`）；M3-03 Vectorize 同步已合入，本需求只使用本地向量。

## 1. 目标与范围

把现有「一次性、无过滤」的推荐生成任务升级为可每日定时执行的推荐流水线：

1. **每日定时**：Celery beat 每天 08:30（Asia/Shanghai）生成推荐，早于 09:00 的每日推送准备；
2. **阈值过滤**：按最终推荐得分设置最低阈值，过滤低质量候选，阈值可通过环境变量 / 接口参数调整；
3. **去重已收藏**：候选热榜仓库中排除 `my_repositories` 已收藏的仓库；同时把历史上已变成「已收藏」的 `new` 推荐标记为 `expired`；
4. **综合打分**：以用户收藏库的平均向量为画像，候选得分 = 相似度 × 权重 + 热榜热度 × 权重，热度按 `log1p(stars_today)` 归一化，避免单个超高星项目压倒性支配；
5. **幂等落库**：按 `(user_id, repo_id)` 更新已有推荐而不是重复插入；未入选的旧 `new` 推荐标记 `expired`；
6. **复用 M3-02 向量**：优先读取 `repo_vectors` 中模型 / 后端兼容的向量，缺失时按 `build_repo_text` 现场编码并回写，避免每日重复编码全量文本；
7. **可观测**：任务返回候选数、已收藏排除数、阈值过滤数、新增 / 更新 / 过期数，便于后续 M3-08 调参。

不在本次范围：推荐页收藏 / 忽略交互（M3-07）、LLM 推荐理由（M3-06，当前沿用模板理由）、按用户独立画像（VPS 本地 `my_repositories` 暂未带 `user_id`，仍为单用户镜像口径）、Vectorize 语义检索（M3-04）。

## 2. 现状与缺口

- `vps/app/tasks/jobs.py` 已有 `generate_recommendations`，但只按余弦相似度排序：
  - 没有最低阈值，弱相关候选也会进入推荐；
  - 没有排除 `my_repositories`，可能推荐已收藏项目；
  - 没有热榜热度权重，排序只反映语义相似度；
  - 没有 Celery beat 计划，只能手动触发；
  - 每个用户 × 每个候选都单独查询一次 `Recommendation`，重复查询多；
  - 未使用 M3-02 已持久化的 `repo_vectors`，每天重新编码全部收藏库与热榜。
- `Recommendation.status` 只有 `new / pushed` 等语义，缺少「本轮未入选」的过期状态。

## 3. 方案

### 3.1 数据流

```text
my_repositories ──平均向量──► 用户画像 profile_vec
        │                         │
        └─ id 集合 ──┐            │ cosine
                     ▼            ▼
trending_repositories ──排除已收藏──► 候选集
                                      │
                          score = 0.8 × similarity + 0.2 × heat
                                      │
                              score >= RECOMMEND_MIN_SCORE
                                      │
                                 按 score 降序取 top_k
                                      │
                     upsert recommendations（new / 保留 saved、dismissed、pushed）
                     old new 未入选或已收藏 → expired
```

### 3.2 画像向量

- 取收藏库按 `stars DESC, id ASC` 的前 `1000` 条（`PROFILE_LIMIT`），避免超大收藏库拖慢任务；
- 优先从 `repo_vectors(source='my')` 读取 `model + backend` 与当前 `EmbeddingService` 一致的向量；
- 缺失 / 模型或后端不一致时，按 `build_repo_text('my', row)` 现场编码，并 upsert 回 `repo_vectors`；
- 对有效向量做逐维平均后再 L2 归一化；维度不一致或全部为空时跳过该用户。

### 3.3 候选与去重

- 候选来自 `trending_repositories`，按 `stars_today DESC, id ASC` 取前 `RECOMMEND_CANDIDATE_LIMIT` 条未收藏仓库；
- 查询时多取 `len(collected_ids)` 条再在内存中过滤，保证排除已收藏后仍有足够候选；
- 已收藏集合来自全部 `my_repositories.id`（不限于画像前 1000 条）；
- 生成前若已有 `Recommendation` 指向已收藏仓库且状态为 `new`，一并标记 `expired`。

### 3.4 打分公式

```text
heat(c)      = log1p(max(0, c.stars_today)) / log1p(max(stars_today of candidates))
score(c)     = (0.8 × max(0, cosine(profile, c.vector)) + 0.2 × heat(c)) / (0.8 + 0.2)
```

- 权重由 `RECOMMEND_SIMILARITY_WEIGHT` / `RECOMMEND_TRENDING_WEIGHT` 配置，均为 0 时退化为纯相似度；
- 相似度为负时按 0 处理；
- 阈值 `RECOMMEND_MIN_SCORE` 作用于最终 `score`（0~1），默认 `0.30`；
- 排序按 `score DESC, repo_id ASC`，保证同分结果稳定可复现；
- `reason` 中的百分比使用**相似度**而不是综合得分，避免把热度误称为兴趣相似度。

### 3.5 落库与状态

| 场景 | 处理 |
| --- | --- |
| 新推荐 | 插入 `Recommendation(status='new')` |
| 已有 `new` / `expired` 且本轮仍入选 | 更新 score / reason，状态回到 `new` |
| 已有 `saved` / `dismissed` / `pushed` 且本轮入选 | 只更新 score / reason，保留原状态，避免覆盖用户反馈 / 重复推送 |
| 旧 `new` 本轮未入选 | 标记 `expired` |
| 旧 `new` 对应仓库已收藏 | 标记 `expired` |
| 其他状态 | 不主动修改 |

### 3.6 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RECOMMEND_MIN_SCORE` | `0.30` | 最终推荐得分最低阈值（0~1） |
| `RECOMMEND_DAILY_TOP_K` | `20` | 每日任务每个用户最多生成的推荐数 |
| `RECOMMEND_CANDIDATE_LIMIT` | `500` | 单次参与打分的热榜候选上限 |
| `RECOMMEND_SIMILARITY_WEIGHT` | `0.8` | 相似度权重 |
| `RECOMMEND_TRENDING_WEIGHT` | `0.2` | 热榜热度权重 |

同时更新 `vps/app/runtime.py` 的 `REQUIRED_ENV_KEYS`、`vps/.env.example`、`deploy/env/openfactory.env.example`，由既有部署资产测试保证不漂移。

### 3.7 接口与定时

- `POST /api/tasks/generate-recommendations` 新增可选 `min_score`（0~1），`top_k` 仍为 1~100；
- `POST /api/recommend/generate` 同步支持 `min_score`；
- Celery beat 新增 `generate-recommendations-daily`：每天 08:30（Asia/Shanghai），不传参数时使用配置默认值；
- 任务返回结构：

```json
{
  "status": "ok",
  "users": ["default"],
  "userCount": 1,
  "created": 12,
  "updated": 8,
  "expired": 3,
  "minScore": 0.3,
  "topK": 20,
  "results": [
    {
      "userId": "default",
      "status": "ok",
      "created": 12,
      "updated": 8,
      "expired": 3,
      "selected": 20,
      "candidates": 480,
      "vectorizedCandidates": 480,
      "excludedCollected": 20,
      "belowThreshold": 460,
      "profileSize": 36,
      "minScore": 0.3,
      "topK": 20
    }
  ]
}
```

### 3.8 降级与边界

- 收藏库为空 / 画像向量为空：该用户返回 `skipped`，不抛异常；
- 热榜为空：返回 `skipped`，不修改已有推荐；
- 单条候选向量编码失败：跳过该候选，不影响整批；
- 单个用户处理失败：回滚该用户事务，记录 `error`，继续处理其他用户；
- 所有外部依赖仍保持「任务返回结构化结果、不向上抛异常」的既有约定。

## 4. 文件清单

- `vps/app/services/recommender.py`：新增 `Candidate` / `RankedCandidate`、`build_profile_vector`、`score_candidate`、`rank_candidates`，`build_reason` 支持独立传入相似度
- `vps/app/services/recommendation_service.py`：新增每日推荐编排（画像、候选、去重、打分、落库、过期）
- `vps/app/tasks/jobs.py`：`generate_recommendations` 改为薄封装，新增 `min_score` 参数
- `vps/app/tasks/celery_app.py`：新增每日 08:30 beat 计划
- `vps/app/api/tasks.py`、`vps/app/api/recommend.py`：新增 `min_score` 查询参数
- `vps/app/config.py`、`vps/app/runtime.py`、`vps/.env.example`、`deploy/env/openfactory.env.example`：新增推荐配置
- `vps/tests/test_recommender.py`、`vps/tests/test_recommendation_service.py`、`vps/tests/test_api.py`：纯计算、服务集成、API 用例
- `docs/architecture/data-model.md`、`docs/architecture/overview.md`、`docs/planning/roadmap.md`、`docs/planning/task-planning.md`、`vps/README.md`：行为与状态文档

## 5. 验证计划

- `cd vps && .venv/bin/pytest -q`：新增用例全部通过，原有向量化 / 同步 / API 用例不回归；
- `cd edge && npm run typecheck`：确认没有跨端契约影响；
- `cd admin && npm run lint && npm run build && npm run test`：确认前端无影响（推荐接口参数向后兼容）；
- `python -m compileall vps/app`、`git diff --check`；
- 手工冒烟：造 1 个收藏仓库 + 若干热榜仓库，调用 `generate_recommendations.run(user_id='default')`，核对阈值、去重、排序、过期状态。

## 6. 风险与待人工事项

1. **阈值默认值需要真实数据校准**：`0.30` 基于 hash 兜底向量的相似度分布（相关项目约 0.45~0.77，不相关约 0~0.08）；BGE-M3 的分布可能不同，M3-08 调参时按抽样评估集调整。
2. **单用户画像**：VPS 本地 `my_repositories` 目前没有 `user_id`，多用户场景下所有用户共用同一画像；需要 D1 同步补用户维度后再做按用户画像。
3. **热榜数据新鲜度**：候选取当前 `trending_repositories` 全表按 `stars_today` 排序，依赖既有热榜抓取 / 清理策略；若历史行长期不清理，可能进入候选。
4. **`expired` 状态**：属于 VPS 本地推荐状态扩展，D1 `recommendations.status` 为 TEXT，无约束冲突；边缘侧若需要展示过期状态，后续在 M3-07 一并处理。

## 7. 验证记录（2026-10-22）

| 检查 | 结果 |
| --- | --- |
| `cd vps && .venv/bin/pytest -q` | ✅ 75 passed（含新增 16 个推荐用例） |
| `cd edge && npm run typecheck` | ✅ 0 error |
| `cd admin && npm run lint` | ✅ 通过 |
| `cd admin && npm run build` | ✅ 通过（3972 modules） |
| `cd admin && npm run test` | ✅ 10 files / 73 tests passed |
| `python -m compileall vps/app` | ✅ 通过 |
| `git diff --check` | ✅ 无空白错误 |

> 说明：`tests/test_vector_sync.py` 的两处原生 SQL 插入补上了 `created_at` / `updated_at`，
> 修复了 M3-02 与 M3-03 合并后 `repo_vectors` / `vector_sync_state` 非空时间字段导致的测试失败。
