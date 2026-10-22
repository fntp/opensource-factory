# 实施计划 · REQ-202610-0924 推荐理由生成（中文、依据字段）

> 需求：REQ-202610-0924（backlog M3-06）｜ 分支：`feat/req-202610-0924-recommend-reason`
> 依赖：M3-05（每日推荐生成任务）——当前基线已有 `generate_recommendations` 骨架，
> 本需求在其上补齐「中文理由 + 依据字段」，M3-05 合并后可直接复用同一服务。

## 1. 目标

把现有 `build_reason()` 的通用模板升级为**可解释的推荐理由生成**：

1. **中文理由**：结合用户收藏画像（语言 / 技术栈 / 分类）、候选仓库字段（语言、技术栈、简介、
   今日热度）与语义相似度，生成自然、可读、不堆砌的中文理由；
2. **依据字段**：同步产出 `based_on`（JSON 字符串数组），记录理由实际使用的字段，
   与 D1 `recommendations.based_on` 契约一致，供 edge / admin 以标签展示；
3. **可回填**：新增理由重算任务，模板调整后可对存量推荐批量刷新 `reason` / `based_on`；
4. **可测试**：纯函数生成，不依赖模型 / 网络；任务与接口用临时 SQLite + mock 向量覆盖。

## 2. 现状与缺口

- `vps/app/services/recommender.py::build_reason()` 只输出「相似度 + 语言 + 技术栈 + 简介」固定模板，
  未使用用户画像，无法解释「为什么推荐给我」；
- 本地 `Recommendation` 模型只有 `reason`，缺少 D1 已建模的 `based_on`；
- 推荐生成任务只写本地表，存量数据没有理由回填能力；
- `/api/recommend/query` 返回 `reason`，但无 `based_on` 字段。

## 3. 方案

### 3.1 理由生成服务（`vps/app/services/recommend_reason.py`）

- `UserInterestProfile`：从收藏库聚合 `languages`（Top 3）、`tech_terms`（Top 8）、
  `categories`（分类名）、`repo_count`；
- `build_user_profile(repos, category_names=None)`：纯函数，兼容 dict / ORM；
- `build_reason_detail(repo, score, profile=None) -> ReasonDetail(reason, based_on)`：
  - 相似度分档：高（≥75%）/ 中（≥50%）/ 低，使用不同措辞；
  - 证据优先级：共同语言 → 共同技术栈（最多 2 项）→ 共同分类 → 今日热度 → 简介摘要；
  - 每条理由均包含仓库名与相似度，避免空理由；
  - `based_on` 只记录理由中实际引用的字段，最多 6 项，JSON 可序列化；
- `build_reason(repo, score)` 保留原签名，内部转调 `build_reason_detail`，兼容既有调用与测试；
- `parse_based_on(raw)` / `dump_based_on(items)`：容错解析与稳定序列化（`ensure_ascii=False`）。

### 3.2 数据与任务接入

- `vps/app/models.py`：`Recommendation` 增加 `based_on TEXT`（JSON 数组字符串）；
- `vps/app/db.py`：`init_db()` 对旧 SQLite 库幂等补 `recommendations.based_on` 列
  （`create_all` 不会自动加列）；
- `vps/app/tasks/jobs.py`：
  - `generate_recommendations` 构建用户画像，写入 `reason` + `based_on`；
  - 新增 `regenerate_recommendation_reasons` Celery 任务，对存量推荐批量重算；
- `vps/app/api/tasks.py`：新增 `POST /api/tasks/regenerate-recommendation-reasons` 入队接口；
- `vps/app/api/recommend.py`：
  - `/api/recommend/query` 返回 `based_on`（JSON 数组，与 D1 字段语义一致）；
  - 新增 `GET /api/recommend/list` 查询本地已生成推荐（含理由与依据），便于联调 / 对账。

### 3.3 契约与前端

- edge `Recommendation` / admin `Recommendation` 已含 `basedOn`，无需改字段；
- 保持 `based_on` 为 JSON 数组字符串；edge `parseBasedOn()` 已兼容逗号分隔旧格式；
- admin 推荐卡片已渲染 `basedOn` 标签，本需求不新增页面。

### 3.4 配置

无新增环境变量；理由生成是纯规则计算，不调用 LLM，不占模型预算。

## 4. 文件清单

- `vps/app/services/recommend_reason.py`（新增）
- `vps/app/services/recommender.py`（保留排序，`build_reason` 转调新服务）
- `vps/app/models.py`、`vps/app/db.py`、`vps/app/schemas.py`
- `vps/app/tasks/jobs.py`、`vps/app/api/tasks.py`、`vps/app/api/recommend.py`
- `vps/tests/test_recommend_reason.py`（新增）、`vps/tests/test_recommender.py`（兼容性）
- `vps/README.md`、`docs/architecture/overview.md`、`docs/architecture/data-model.md`、
  `docs/requirements/backlog.md`、`docs/planning/task-planning.md`、本计划文档

## 5. 验证计划

- `cd vps && .venv/bin/pytest -q`：理由分档 / 画像匹配 / 依据字段 / 空字段兜底 /
  任务写入 / 存量回填 / API 契约；
- `cd edge && npm run typecheck`：确认 `basedOn` 契约未变；
- `python -m compileall vps/app`、`git diff --check`；
- 不访问网络、不加载模型（测试使用 hash 向量与临时 SQLite）。

## 6. 风险与边界

- **M3-05 尚未合并**：本需求复用现有 `generate_recommendations` 骨架；M3-05 落地后
  只需在同一处调用 `build_reason_detail`，不重复实现阈值 / 去重逻辑；
- **画像冷启动**：收藏库为空时退化为「候选自身字段 + 相似度」理由，不虚构用户偏好；
- **技术栈提取为启发式**：`tech_stack` 可能为空或噪声，理由只引用命中的真实字段；
- **不调用 LLM**：保证 2G 预算与离线可测；后续如需更自然的措辞，可在同一接口替换实现。
