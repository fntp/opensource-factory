# 实施计划 · REQ-202610-0952 项目健康度追踪（最后提交 / issue 活跃 / 归档标记）

> 需求：REQ-202610-0952（backlog M6-05）｜ 分支：`feat/req-202610-0952-repo-health-tracking`
> 依赖：M1-05 Starred 全量同步（已落地，`my_repositories` 镜像与 GitHub 客户端可用）
> 目标：为收藏 / 自有仓库补充 GitHub 元数据（最后提交、未关闭 issue、归档 / 禁用标记），
> 计算可解释的健康度评分与状态，并在 VPS / edge / admin 三端提供查询、刷新与展示。

## 1. 现状与缺口

- `vps/app/services/github_service.py` 的 `normalize_repo` 只保留 id / name / description /
  html_url / stars / language / forks，GitHub 返回的 `pushed_at`、`open_issues_count`、
  `archived`、`disabled` 等字段全部丢弃；
- `my_repositories`（VPS SQLite 与 D1）没有健康度相关列，无法回答「哪些收藏已经停更 / 已归档」；
- admin 仓库列表只有 Stars 与更新时间，没有健康度视图，也没有刷新入口；
- M6-05 备注要求「GitHub API 补充字段」，需要一条可重跑的元数据刷新链路，而不是一次性脚本。

## 2. 方案总览

```
admin 仓库页
  ├─ GET /api/repos（edge，D1）→ 每条仓库带 health 对象（本地计算，无额外请求）
  └─ POST /api/repos/health/refresh（edge，登录态）
        → 取当前用户 D1 仓库 id（≤200）
        → VPS POST /api/repos/health/refresh（X-Internal-Token）
             → Celery refresh_repo_health
             → GitHub GET /repos/{owner}/{repo}（GITHUB_TOKEN）
             → 更新 VPS my_repositories 元数据 + health_* 列
             → POST {edge}/api/repos/health 批量回写 D1（X-Internal-Token）
        → admin 重新拉取 /api/repos 展示最新健康度
```

设计要点：

- **GitHub 元数据补齐**：`pushed_at` / `open_issues_count` / `archived` / `disabled` /
  `updated_at` 进入统一标准化结构，同步任务与健康刷新共用；
- **健康度可解释**：状态 `active` / `attention` / `stale` / `archived` / `unknown`，
  分数 0~100 由「最后提交距今天数」为主、未关闭 issue 占比与归档标记为辅计算，
  同时返回中文 `label` 与 `reasons`，前端不重复实现业务规则；
- **两处计算口径一致**：VPS 服务计算并落库；edge 对尚未刷新的 D1 行用同一套阈值做本地降级计算，
  保证页面永远有值、不会因 VPS 不可达而空白；
- **刷新异步化**：GitHub 调用走 Celery，HTTP 请求只负责入队；回写 D1 失败不影响 VPS 本地结果；
- **可配置阈值**：`REPO_HEALTH_ACTIVE_DAYS` / `REPO_HEALTH_ATTENTION_DAYS` /
  `REPO_HEALTH_STALE_DAYS` / `REPO_HEALTH_MAX_PER_RUN` / 每日刷新时间；
- **幂等补列**：VPS `init_db()` 与 D1 migration `0014_repo_health.sql` 都为既有库补列，不重建表。

## 3. 数据模型

`my_repositories` 新增列（VPS SQLite 与 D1 同名同义）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `pushed_at` | DATETIME / TEXT | 最后一次 push 时间（GitHub `pushed_at`） |
| `open_issues_count` | INTEGER | 未关闭 issue + PR 数（GitHub 口径） |
| `archived` | INTEGER / BOOLEAN | 仓库是否已归档 |
| `disabled` | INTEGER / BOOLEAN | 仓库是否被禁用 |
| `health_status` | TEXT | `active` / `attention` / `stale` / `archived` / `unknown` |
| `health_score` | INTEGER | 0~100，越大越健康 |
| `health_checked_at` | DATETIME / TEXT | 最近一次健康度计算时间 |

健康度口径：

- 最后提交 ≤ `REPO_HEALTH_ACTIVE_DAYS`（默认 90 天）→ `active`；
- ≤ `REPO_HEALTH_ATTENTION_DAYS`（默认 180 天）→ `attention`；
- ≤ `REPO_HEALTH_STALE_DAYS`（默认 365 天）→ `stale`；
- 超过 365 天或 `disabled=true` → `stale`；
- `archived=true` → `archived`（优先于时间判断）；
- 无 `pushed_at` → `unknown`。
- 分数：按天数分档（100 / 70 / 45 / 20）后按未关闭 issue 占 Star 比例扣分
  （≥50% 扣 20、≥20% 扣 10、0 issue 加 5），最终夹取 0~100。

## 4. 接口

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/api/repos/health` | GET | `X-Internal-Token` | VPS：健康度列表 + 汇总（`status` / `limit` / `offset`） |
| `/api/repos/{repo_id:path}/health` | GET | `X-Internal-Token` | VPS：单仓库健康度（404 = 未收录） |
| `/api/repos/health/refresh` | POST | `X-Internal-Token` | VPS：入队元数据刷新（`repoIds` / `limit`） |
| `/api/repos/health` | GET | 登录态 | edge：当前用户健康度汇总 + 条目 |
| `/api/repos/health/refresh` | POST | 登录态 | edge：取当前用户仓库 → 转发 VPS 刷新 |
| `/api/repos/health` | POST | `X-Internal-Token` | edge：VPS 批量回写健康度到 D1 |

## 5. 交付物

| 文件 | 说明 |
| --- | --- |
| `vps/app/services/repo_health.py` | 健康度评分、元数据刷新、edge 回写 |
| `vps/app/api/repos.py` | 健康度查询 / 刷新接口 |
| `vps/app/tasks/jobs.py`、`celery_app.py` | `refresh_repo_health` 任务与每日 beat |
| `vps/app/models.py`、`db.py` | 新增列与幂等补列 |
| `vps/app/services/github_service.py` | `normalize_repo` 补齐 GitHub 字段 |
| `vps/app/config.py`、`runtime.py`、两份 env 模板 | `REPO_HEALTH_*` 配置 |
| `edge/migrations/0014_repo_health.sql` | D1 补列 |
| `edge/src/repos/health.ts` | edge 侧健康度降级计算与汇总 |
| `edge/src/routes/repos.ts` | 健康度接口与 `RepoItem.health` |
| `admin/src/features/repos/health.ts`、`api.ts`、`index.tsx` | 健康度列、汇总与刷新按钮 |
| `docs/architecture/*`、`docs/requirements/backlog.md`、`docs/planning/*` | 文档同步 |

## 6. 测试与验收

| 层 | 用例 |
| --- | --- |
| vps | `tests/test_repo_health.py`：评分分档 / 归档 / 未知、issue 扣分、`normalize_repo` 字段、刷新注入 fetcher、API 鉴权与 404 |
| edge | `scripts/repo-health.test.mjs`：状态降级、汇总、标签、日期解析 |
| admin | `src/features/repos/health.test.ts`：标签 / 汇总 / 最近提交文案 |
| 全量 | vps pytest、edge typecheck + node:test、admin lint / build / test |

验收标准：

1. 同步或刷新后，仓库具备最后提交时间、未关闭 issue 数、归档标记与健康度状态；
2. admin 仓库列表可按健康度识别停滞 / 归档项目，并能触发刷新；
3. VPS 不可达时 edge 仍能基于 D1 已有字段给出降级健康度；
4. 三端检查全绿，文档同步。

## 7. 风险与后续

- **issue 活跃口径**：GitHub REST 仓库对象只给未关闭总数，无法区分「新 issue 是否被响应」；
  当前用「未关闭数 / Star 数」做启发式，后续可接 GraphQL 的 issue 更新时间或 `issues` 事件；
- **GitHub 限流**：批量刷新按仓库逐个请求，受 token 配额限制；默认单次上限 200，
  每日 beat 只刷新缺失 / 过期数据，避免全量重复调用；
- **归档仓库仍可收藏**：只做标记与提示，不自动删除或取消收藏；
- **D1 回写依赖 EDGE_BASE_URL / INTERNAL_TOKEN**：未配置时仅更新 VPS 本地镜像，
  edge 页面继续使用已有 D1 字段做降级计算。

## 8. 实施结果（2026-10-22）

- 三端实现完成：VPS 元数据刷新 / 评分 / Celery 每日任务与 API，edge 迁移 / 降级计算 / 回写与刷新代理，
  admin 健康度汇总卡片、状态筛选、表格徽章与刷新按钮；
- 测试：VPS `248 passed`（新增 8 条健康度用例）、edge `36 passed`（新增 5 条）、
  admin `102 passed`（新增 6 条）；`edge npm run typecheck`、`admin npm run lint`、`admin npm run build` 全绿；
- 口径：健康度阈值默认 90 / 180 / 365 天，issue 压力仅修正分数不改状态；详细规则见
  `docs/architecture/overview.md` §3.13 与 `docs/architecture/data-model.md` §2.1；
- 待确认：issue 口径（GitHub `open_issues_count` 含 PR）记录在 `docs/requirements/open-questions.md` Q14。
