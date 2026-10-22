# 实施计划 · REQ-202610-0900 同步任务状态回传与可视化

> 对应需求：REQ-202610-0900（backlog M1-08 / 依赖 M1-05）｜ 分支：`feat/req-202610-0900-sync-task-status`｜ 日期：2026-10-22｜ 状态：已完成

## 1. 目标

把「同步任务」从一次性的 `POST /api/sync` 调用升级为**可追踪、可查询、可视化**的闭环：

1. **任务表**：D1 新增 `sync_tasks`，记录任务 id、触发用户、类型、状态、进度、结果、错误与时间戳；
2. **状态回传**：edge 入队后保存 `taskId`；`GET /api/tasks/{taskId}` 按 VPS `/api/tasks/{taskId}` 契约拉取状态并回写 D1；
3. **任务列表**：`GET /api/tasks` 返回当前用户最近任务，供 admin 展示历史；
4. **admin 进度**：新增「同步任务」页面，展示状态徽章、进度条、结果摘要与耗时；运行中任务自动轮询刷新；
5. **入口联动**：仓库页「同步仓库」改为真实调用 `POST /api/sync`，成功后跳转任务页查看进度。

## 2. 现状与约束

- `edge/src/routes/sync.ts` 目前只转发 VPS，丢弃了 VPS 返回的 `taskId`，也没有落库；
- `vps/app/api/tasks.py` 已提供 `GET /api/tasks/{task_id}`（`pending/started/success/failure`），M1-05 会扩展 `progress`；本需求对 `progress` 做可选兼容；
- admin 侧无任务页面，仓库页「同步仓库」仅弹演示 toast；
- 约束：D1 表结构变更必须新增迁移文件并同步 `docs/assets/d1-schema.sql`；admin 演示模式（无 `VITE_API_BASE_URL`）仍需可用；测试不得访问网络。

## 3. 方案

### 3.1 D1 任务表（`edge/migrations/0002_sync_tasks.sql`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | VPS 返回的 taskId（Celery task id） |
| `user_id` | TEXT | 触发用户（admin 只能看自己的任务） |
| `task_type` | TEXT | `sync` / `sync-starred` 等，默认 `sync` |
| `status` | TEXT | `pending` / `started` / `progress` / `success` / `failure` / `unknown` |
| `progress` | TEXT | 进度快照 JSON（camelCase，与 VPS 契约一致） |
| `result` | TEXT | 结果 JSON |
| `error` | TEXT | 错误摘要（截断 500 字符） |
| `created_at` / `updated_at` / `finished_at` | DATETIME | 创建 / 最近刷新 / 结束时间 |

索引：`(user_id, created_at DESC)` 用于任务列表；`(status)` 用于活跃任务筛选。

### 3.2 edge 任务 API（`edge/src/routes/tasks.ts`）

- `POST /api/sync`（改造 `sync.ts`）：
  - 转发 VPS，解析 `202 {"taskId"}`；
  - 写入 `sync_tasks`（同 id 冲突则更新）；
  - 返回 `202 {"status":"queued","taskId":"..."}`；
  - VPS 未配置时保持原有 `accepted` 行为。
- `GET /api/tasks?limit=20`：当前用户任务，按创建时间倒序；
- `GET /api/tasks/{taskId}`：
  - 校验登录与归属，未找到返回 404；
  - 非终态任务向 VPS `GET /api/tasks/{taskId}` 拉取最新状态（带 `X-Internal-Token`）；
  - 归一化 Celery 状态（`PENDING/STARTED/PROGRESS/SUCCESS/FAILURE/RETRY/REVOKED`），回写 D1；
  - VPS 不可达时返回 D1 中的最后一次快照，并附 `stale: true`；
  - 响应统一 camelCase：`{taskId,type,status,progress,result,error,createdAt,updatedAt,finishedAt,stale}`。

### 3.3 VPS 契约补齐（`vps/app/api/tasks.py`、`vps/app/schemas.py`）

- `TaskStatus` 增加可选 `progress` 字段；
- `GET /api/tasks/{task_id}` 在 Celery `PROGRESS` 状态时透出 `result.info`，与 M1-05 的进度快照一致；
- 其余状态语义不变，保持向后兼容。

### 3.4 admin 任务页（`admin/src/features/tasks/`）

- `api.ts`：任务类型、演示数据、`fetchTasks` / `fetchTask` / `triggerSync`、状态文案 / 进度 / 耗时等纯函数；
- `index.tsx`：概览卡片（总数 / 运行中 / 失败）、任务表（状态徽章、进度条、结果摘要、耗时）、「立即同步」按钮；
- 活跃任务存在时每 3 秒轮询；任务完成后自动停止；
- 新增路由 `/tasks` 与侧边栏入口「同步任务」；
- 仓库页「同步仓库」接入真实接口，成功后跳转任务页。

### 3.5 演示模式与降级

- admin 无 `VITE_API_BASE_URL` 时继续使用 `MOCK_TASKS`，同步按钮只提示演示；
- edge 未配置 `VPS_NODE_URL` 时返回 `accepted`，不伪造任务记录；
- VPS 状态查询失败时 edge 不回 5xx，返回 D1 最后快照并标记 `stale`。

## 4. 文件清单

| 文件 | 说明 |
| --- | --- |
| `edge/migrations/0002_sync_tasks.sql` | 新增任务表与索引 |
| `docs/assets/d1-schema.sql` | 同步 Schema 副本 |
| `edge/src/types.ts` | 任务行 / 响应类型 |
| `edge/src/lib/tasks.ts` | 状态归一化、JSON 解析、VPS 查询与回写 |
| `edge/src/routes/tasks.ts` | 任务列表 / 详情接口 |
| `edge/src/routes/sync.ts` | 入队后落库并返回 taskId |
| `edge/src/index.ts` | 挂载 `/api/tasks` |
| `vps/app/schemas.py` / `vps/app/api/tasks.py` | 进度字段透出 |
| `vps/tests/test_api.py` | 进度透出契约测试 |
| `admin/src/features/tasks/api.ts` / `index.tsx` | 任务页数据层与页面 |
| `admin/src/features/tasks/api.test.ts` | 纯函数单测 |
| `admin/src/routes/_authenticated/tasks/index.tsx` | 文件式路由 |
| `admin/src/components/layout/data/sidebar-data.ts` | 侧边栏导航（补齐被忽略文件） |
| `admin/src/features/repos/index.tsx` | 同步按钮接入真实接口 |
| `admin/.gitignore` / `.gitignore` | 放行 `layout/data/` 目录 |
| `docs/architecture/overview.md` / `data-model.md` | 接口与数据模型同步 |
| `docs/requirements/backlog.md` / `docs/planning/task-planning.md` | 状态更新 |

## 5. 验收标准

1. `POST /api/sync` 返回 `taskId`，D1 `sync_tasks` 出现 `pending` 记录；
2. `GET /api/tasks/{taskId}` 能拉取 VPS 状态并回写，`progress` 原样透出，终态带 `finishedAt`；
3. `GET /api/tasks` 只返回当前用户任务，按时间倒序，limit 生效；
4. admin `/tasks` 页面在演示模式与真实模式下均可渲染；活跃任务自动刷新；
5. 仓库页同步按钮触发真实接口并跳转任务页；
6. `edge npm run typecheck`、`vps .venv/bin/pytest -q`、`admin npm run lint && npm run build && npm run test` 全绿。

## 6. 验证结果（2026-10-22）

- `edge npm run typecheck`：0 error；
- `edge` 本地 D1 迁移：`0001_init.sql` + `0002_sync_tasks.sql` 均应用成功（17 + 4 条语句）；
- `edge` 本地 e2e（mock VPS + wrangler dev）：`POST /api/sync` → 202 taskId；`GET /api/tasks` 列表可见；`GET /api/tasks/{taskId}` 返回 `success` + `progress.percent=100` + `finishedAt`；未登录访问返回 401；
- `vps .venv/bin/pytest -q`：21 passed；
- `admin npm run lint` / `npm run build` / `npm run test`：lint 通过、构建通过、78 个用例全部通过。

## 7. 风险与人工事项

- D1 迁移需在部署环境执行 `npm run db:migrate:local` / 远程迁移，否则任务落库会失败（接口会降级为 `tracked:false`）；
- 任务历史目前只保留在 D1，后续可加保留策略（M8 数据治理）；
- VPS 端 `progress` 依赖 M1-05 的 `update_state`，本需求只做兼容透出，不重复实现分页同步。
