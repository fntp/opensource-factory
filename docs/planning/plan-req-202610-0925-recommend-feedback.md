# 实施计划 · REQ-202610-0925 推荐页闭环（收藏 / 忽略 / 反馈回流）

> 需求：REQ-202610-0925（backlog M3-07）｜ 分支：`feat/req-202610-0925-recommend-feedback`
> 依赖：M3-05（每日推荐生成任务）。本分支基于 M3-04 语义搜索分支（含 M3-02 / M3-03），
> 推荐生成侧沿用现有 `generate_recommendations` 骨架；M3-05 合并后可在同一入口继续复用。

## 1. 目标

把推荐卡片从「只读展示」做成可闭环的推荐页：

1. **收藏**：点击后真实写入当前用户的 `my_repositories`，推荐状态置为 `saved`，并写入反馈记录；
2. **忽略**：点击后推荐状态置为 `dismissed`，可携带原因，列表即时移除；
3. **反馈回流**：反馈落库到 D1 `recommendation_feedback`，VPS 生成推荐时拉取该用户的
   `saved` / `dismissed` 仓库并从候选中排除，避免重复推荐；
4. **数据回流**：VPS 生成推荐后通过内部接口把结果 upsert 到 D1，推荐页读到的是真实数据；
5. **可观测**：推荐页支持「待处理 / 已收藏 / 已忽略」筛选，接口返回状态与反馈统计；
6. **可降级**：edge 未配置内部令牌或 VPS 不可达时，各自保留本地能力并返回明确状态，不阻塞主流程。

## 2. 现状与缺口

- `admin/src/features/recommend/` 仍是演示骨架：`fetchWithFallback` + `MOCK_RECOMMENDATIONS`，
  收藏按钮只弹「已加入收藏（演示）」，忽略只改本地 state；
- `edge/src/routes/recommend.ts` 只有 `GET /api/recommendations`，没有收藏 / 忽略 / 反馈接口，
  也不返回 `status`；
- D1 `recommendations` 已有 `status`，但没有 `repo_id`（无法稳定回传反馈）与反馈明细表；
- VPS `generate_recommendations` 只写本地 SQLite，既不推送 D1，也不消费用户反馈；
- 推荐页没有加载态 / 错误态 / 空态，也没有「已收藏 / 已忽略」视图。

## 3. 方案

### 3.1 数据模型（D1）

新增迁移 `edge/migrations/0009_recommendation_feedback.sql`：

- `recommendations` 增加 `repo_id TEXT`（`owner/name`，历史行可空）与 `updated_at DATETIME`；
- 新增 `recommendation_feedback`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | 反馈 id（UUID） |
| user_id | TEXT | 用户 |
| recommendation_id | TEXT | 推荐 id |
| repo_id | TEXT | 仓库 id（`owner/name`） |
| action | TEXT | `saved` / `dismissed` / `clicked` |
| reason | TEXT | 忽略原因（可空，≤200 字） |
| created_at | DATETIME | 创建时间 |

- 唯一约束 `(user_id, recommendation_id, action)`，重复点击幂等；
- 索引 `(user_id, created_at DESC)`、`(user_id, repo_id)`。

### 3.2 Edge API

`edge/src/routes/recommend.ts` 扩展：

- `GET /api/recommendations?status=new|saved|dismissed|all&limit=50`
  - 默认只返回 `new`；`saved` / `dismissed` 用于反馈视图；
  - 返回项增加 `status`、`repoId`、`createdAt`。
- `POST /api/recommendations/:id/save`
  - 校验归属（`user_id = 当前用户` 或全局 `NULL`），404 不存在、409 已属于他人；
  - 状态置 `saved`，写 `saved` 反馈，并 upsert 到 `my_repositories`（平台 `github`）；
  - 幂等：重复收藏返回同一结果。
- `POST /api/recommendations/:id/dismiss`（body：`{reason?}`）
  - 状态置 `dismissed`，写 `dismissed` 反馈；幂等。
- `POST /api/recommendations/:id/click`
  - 记录 `clicked` 反馈（不改变状态），用于后续质量评估。
- `GET /api/recommendations/stats`
  - 返回当前用户 `new` / `saved` / `dismissed` / `clicked` 计数。

`edge/src/routes/internal-recommendations.ts`（内部，`X-Internal-Token`）：

- `POST /api/internal/recommendations/upsert`：VPS 推送推荐快照，按 `id` upsert；
  已 `saved` / `dismissed` 的推荐保留用户状态，不被生成任务覆盖；
- `GET /api/internal/recommendations/feedback?userId=`：返回该用户 `savedRepoIds` /
  `dismissedRepoIds` / `clickedRepoIds`，供 VPS 生成时排除。

### 3.3 VPS 反馈回流与推送

新增 `vps/app/services/recommendation_feedback.py`（纯逻辑 + httpx 客户端，测试用 MockTransport）：

- `merge_exclusions(local_ids, saved_ids, dismissed_ids)`：合并去重；
- `fetch_feedback(user_id, settings, client=None)`：调用 edge 内部反馈接口，
  未配置 `EDGE_BASE_URL` / `INTERNAL_TOKEN` 或网络失败时返回空反馈并标记 `source=unavailable`；
- `push_recommendations(user_id, items, settings, client=None)`：调用内部 upsert 接口，
  失败只记日志，不影响本地任务。

`vps/app/tasks/jobs.py::generate_recommendations` 接入：

- 生成前读取 edge 反馈（失败时回退本地 `saved` / `dismissed` 状态），把对应仓库从候选中排除；
- 生成后把该用户的推荐（`new` / `saved` / `dismissed`，含理由与快照）推送到 edge；
- 任务返回 `feedbackExcluded` / `pushed` 字段，便于观测。

新增配置 `EDGE_BASE_URL`（已有）与 `RECOMMEND_FEEDBACK_SYNC`（默认 `true`，可关闭），
同步 `vps/.env.example`、`deploy/env/openfactory.env.example` 与 `runtime.REQUIRED_ENV_KEYS`。

### 3.4 Admin 推荐页

`admin/src/features/recommend/api.ts`：

- 改用 `apiFetch`；仅演示模式（未配置 `VITE_API_BASE_URL`）保留内置示例兜底，生产错误照常上抛；
- `fetchRecommendations(status)`、`saveRecommendation(id)`、`dismissRecommendation(id, reason?)`、
  `trackRecommendationClick(id)`、`fetchRecommendationStats()`；
- 类型与 edge 契约对齐（`status`、`repoId`、`createdAt`）。

`admin/src/features/recommend/index.tsx`：

- 三态：加载骨架 / 错误重试 / 空态；
- 顶部「待处理 / 已收藏 / 已忽略」筛选；
- 收藏按钮：成功后 toast「已收藏，可在我的仓库查看」并从待处理列表移除；
- 忽略按钮：打开原因选择（不感兴趣 / 技术栈不匹配 / 已收藏类似项目 / 其他），确认后调用接口；
- 「查看仓库」点击记录 `clicked` 反馈（fire-and-forget）；
- 已收藏 / 已忽略卡片展示状态徽标，不再显示操作按钮。

### 3.5 测试

- `edge/scripts/recommend-feedback.test.mjs`：状态过滤、反馈行构造、快照映射纯函数；
- `vps/tests/test_recommendation_feedback.py`：合并排除、反馈拉取（MockTransport）、
  推送请求体、失败降级、生成任务排除已忽略仓库；
- `admin/src/features/recommend/api.test.ts`：接口路径 / 方法 / body 契约（mock `apiFetch`）；
- 全量：`vps pytest`、`edge typecheck`、`admin lint/build/test`。

### 3.6 文档

- `docs/architecture/data-model.md`：`recommendations` 新列与 `recommendation_feedback` 表；
- `docs/architecture/overview.md`：推荐闭环数据流与接口边界；
- `docs/requirements/backlog.md`、`docs/planning/task-planning.md`：M3-07 交付登记；
- `vps/README.md`、`edge/README.md`：新配置与内部接口说明；
- `docs/assets/d1-schema.sql`：同步迁移后的完整 schema。

## 4. 风险与边界

- **M3-05 未合并**：本分支在现有生成任务上做最小接入；M3-05 的阈值 / 打分服务合并后，
  反馈排除与推送逻辑可直接复用同一组函数；
- **D1 迁移编号**：本分支使用 `0009`，避免与并行分支的 `0002`~`0008` 冲突；
- **历史数据**：旧推荐没有 `repo_id`，反馈接口按 `owner/name` 回退推导；
- **多用户**：当前 VPS 画像仍是单用户镜像口径，反馈按 `user_id` 存储，后续同步补用户维度；
- **离线可用**：edge 未配置内部令牌 / VPS 不可达时，收藏与忽略仍可完成，仅反馈回流暂停。
