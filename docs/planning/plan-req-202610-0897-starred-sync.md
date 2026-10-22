# 实施计划 · REQ-202610-0897 Starred 全量同步

> 对应需求：REQ-202610-0897（backlog M1-05 / IT-0006）｜ 分支：`feat/req-202610-0897-starred-sync`｜ 日期：2026-10-22｜ 状态：已完成

## 1. 目标

把 GitHub Starred 仓库的同步从「最多 10 页的尽力而为」升级为**可长期运行的全量同步**：

1. **分页**：按 `Link` 响应头逐页跟进，默认 `per_page=100`，不设页数上限（可显式限制）；
2. **限流**：请求间隔节流，识别 `X-RateLimit-*` 与 `Retry-After`，额度耗尽时等待重置；
3. **重试**：网络错误 / 5xx / 429 指数退避重试，401/403（非限流）/404 不重试；
4. **进度**：逐页回调进度（页码 / 总页数 / 已抓取数），Celery 任务通过 `update_state` 暴露，`GET /api/tasks/{taskId}` 可查询；
5. **落库**：批量 upsert 到 `my_repositories`，区分新增 / 更新 / 未变化，支持失败时保留已抓取部分。

## 2. 现状与约束

- `vps/app/services/github_service.py` 已有基础：`_paginate` 固定 `max_pages=10`，无 `Link` 解析、无限流感知、无重试、无进度回调；
- `vps/app/tasks/jobs.py::sync_repositories` 把「自有仓库 + Starred」混在一个任务里，Starred 最多 1000 条；
- `GET /api/tasks/{task_id}` 已具备任务状态契约（`pending/started/success/failure`），但 PROGRESS 状态没有透出 `meta`；
- 依赖 M1-01（运行基线）与 M1-03（GitHub 登录）；本需求使用 `GITHUB_TOKEN`（PAT）直接调用 REST API，不依赖 OAuth 回调；
- 测试不得访问网络：用 `httpx.MockTransport` 构造分页 / 限流 / 重试场景。

## 3. 方案

### 3.1 GitHub 客户端（`app/services/github_service.py`）

- 新增 `GitHubClient`：封装 httpx.AsyncClient、请求节流、限流等待、重试与 `Link` 分页；
- 新增 `SyncProgress` 数据类：`phase / page / pages_total / fetched / total / done / percent`；
- `GitHubClient.paginate(url, per_page, max_pages, on_progress, transform)`：
  - 首页按 `page=1` 请求，后续直接使用 `Link rel="next"` 的绝对 URL；
  - 从 `Link rel="last"` 解析总页数，用于进度百分比；
  - 每页结束回调一次进度，全部结束回调 `done=True`；
- `list_starred_repos(token, ...)`：全量拉取 `/user/starred`，兼容裸仓库对象与 `{starred_at, repo}` 包装；
- `list_user_repos` 保持兼容，自有仓库仍默认 10 页，Starred 走全量分页。

### 3.2 限流与重试策略

| 场景 | 处理 |
| --- | --- |
| 请求间隔 | 默认 `min_interval=0.2s`（可注入 `sleep` 便于测试） |
| `X-RateLimit-Remaining: 0` | 按 `X-RateLimit-Reset` 等待到重置（上限 `max_rate_limit_wait`，默认 1h） |
| 403/429 + `Retry-After` | 按 `Retry-After` 等待后重试 |
| 5xx / 网络错误 | 指数退避（`base * 2^n`，封顶 30s），默认最多 3 次 |
| 401 / 404 / 非限流 403 | 不重试，抛结构化异常 |

### 3.3 同步服务（`app/services/sync.py`）

- `sync_starred_to_db(db, token, *, per_page, max_pages, on_progress, client)`：
  - 抓取 → 批量 upsert（按 500 个 id 分块查询已有行，规避 SQLite 变量上限）；
  - 字段变化才计入 `updated`，否则计入 `unchanged`；
  - 抓取中途失败时，已抓取的条目仍落库，返回 `status="error"` + `partial=true` + 计数；
- `upsert_repositories(db, items)` 独立可测。

### 3.4 Celery 任务与接口

- 新增任务 `app.tasks.jobs.sync_starred_repositories`（`bind=True`）：
  - 通过 `update_state(state="PROGRESS", meta=...)` 上报进度，回写失败只记日志不影响同步；
  - 返回 `{status, total, created, updated, unchanged, pages, duration_ms}`；
- `sync_repositories` 复用新服务，`include_starred=True` 时走全量 Starred；
- 新增 `POST /api/tasks/sync-starred`（`202 {"taskId"}`），并保留 `/api/tasks/sync`；
- `GET /api/tasks/{task_id}` 在 `PROGRESS` 状态返回 `progress` 字段（页码 / 总页数 / 已抓取 / 百分比）。

## 4. 文件清单

| 文件 | 说明 |
| --- | --- |
| `vps/app/services/github_service.py` | GitHub 客户端：分页 / 限流 / 重试 / 进度回调 |
| `vps/app/services/sync.py` | Starred 同步编排与批量 upsert |
| `vps/app/tasks/jobs.py` | 新增 `sync_starred_repositories`，复用同步服务 |
| `vps/app/api/tasks.py` | 新增 `/api/tasks/sync-starred`，状态接口透出进度 |
| `vps/app/api/repos.py` | `/api/repos/sync-starred` 便捷别名 |
| `vps/app/schemas.py` | `TaskStatus.progress` 字段 |
| `vps/tests/test_github_service.py` | 分页 / 限流 / 重试 / 进度单测（MockTransport） |
| `vps/tests/test_sync_service.py` | upsert 与同步编排单测（内存 SQLite） |
| `vps/tests/test_api.py` | 新接口契约测试 |
| `vps/README.md` | 接口与同步说明 |
| `docs/planning/task-planning.md` | IT-0006 状态更新 |

## 5. 验收标准

1. `list_starred_repos` 能跨 3 页以上完整拉取，进度回调页序正确、`pages_total` 来自 `Link: rel="last"`；
2. 429 / 5xx 会重试，401 不重试；限流等待使用注入的 sleep，测试无真实等待、无网络；
3. 同步任务落库新增 / 更新 / 未变化计数正确，重复同步全部为 `unchanged`；
4. `GET /api/tasks/{task_id}` 在 PROGRESS 时返回进度；
5. `vps/.venv/bin/pytest -q` 全绿；`edge npm run typecheck` / `admin` 检查不受影响（本次仅 vps 改动，仍跑基线）。

## 6. 风险与人工事项

- 真实全量同步需要有效的 `GITHUB_TOKEN`（read 权限）；令牌缺失时任务返回 `skipped`，不视为失败；
- 超大 Starred 集合（数千条）会占用较多内存与 API 配额，默认 100 条/页、0.2s 间隔，属于可接受范围；
- GitHub 二级限流（secondary rate limit）等待时间可能较长，任务会阻塞 worker；后续可在 M1-08 增加任务取消 / 断点续跑；
- OAuth 用户级令牌接入属于 M1-03 范围，本需求只使用服务端 PAT。
