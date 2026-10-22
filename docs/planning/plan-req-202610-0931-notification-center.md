# 实施计划 · REQ-202610-0931 站内通知中心（edge + admin）

> 需求：REQ-202610-0931（backlog M4-02）｜ 分支：`feat/req-202610-0931-notification-center`
> 依赖：M4-01 每日评估任务（REQ-202610-0930）｜ 范围：`edge/` + `admin/`（不改 VPS 代码）
> 目标：把每日评估后标记为 `pushed` 的推荐，以站内通知的形式呈现给用户，并提供未读数、已读 / 忽略等闭环操作。

## 1. 背景与现状

- M4-01 的评估任务会把通过质量分与匹配度门槛的推荐标记为 `qualified`，推送准备任务再把 `qualified` 标记为 `pushed`；
- D1 `recommendations.status` 已预留 `new / qualified / filtered / pushed / saved / dismissed / expired` 等状态；
- 现有 edge 只有 `GET /api/recommendations`，没有通知表、未读数与已读操作；
- 现有 admin 只有推荐列表页，没有通知中心入口。

本需求在 edge 增加通知中心 API 与 D1 通知表，在 admin 增加通知中心页面与未读徽标；通知数据从 D1 中 `status='pushed'` 的推荐惰性物化，避免依赖 VPS 额外回调，也不改变 M4-01 的评估口径。

## 2. 数据模型（D1）

新增迁移 `edge/migrations/0010_notifications.sql`：

`notifications`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | 通知 id（随机） |
| user_id | TEXT | 接收用户 |
| type | TEXT | `recommendation` / `system`，默认 `recommendation` |
| title | TEXT | 标题（推荐通知为 `owner/name`） |
| body | TEXT | 正文（简介或推荐理由） |
| url | TEXT | 项目外链 |
| repo_id | TEXT | 仓库 id（`owner/name`） |
| recommendation_id | TEXT | 关联推荐 id，用于幂等物化 |
| dedupe_key | TEXT | 业务去重键（内部推送使用） |
| score | REAL | 匹配度 |
| reason | TEXT | 推荐理由 |
| language | TEXT | 主语言 |
| stars | INTEGER | Star 数 |
| status | TEXT | `unread` / `read` / `dismissed`，默认 `unread` |
| payload | TEXT | 扩展 JSON（如 `basedOn`） |
| created_at | DATETIME | 创建时间（推荐通知沿用推荐生成时间） |
| read_at | DATETIME | 已读 / 忽略时间 |

索引：

- `(user_id, status, created_at DESC)`：列表与未读数；
- `(user_id, recommendation_id)` 唯一：同一用户同一推荐只物化一次；
- `(user_id, dedupe_key)` 唯一：内部推送幂等。

## 3. Edge API

### 3.1 登录态接口（Cookie 会话）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/notifications?status=all\|unread\|read&limit=20&offset=0` | GET | 通知列表；返回 `items / total / unread / hasMore` |
| `/api/notifications/unread-count` | GET | 未读数 |
| `/api/notifications/:id/read` | POST | 标记单条已读（幂等） |
| `/api/notifications/read-all` | POST | 全部标记已读 |
| `/api/notifications/:id/dismiss` | POST | 忽略通知，并同步把关联推荐置为 `dismissed` |

### 3.2 内部接口（`X-Internal-Token`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/internal/notifications` | POST | 批量写入通知（≤100 条），按 `(user_id, dedupe_key)` 幂等 |
| `/api/internal/notifications/sync-recommendations` | POST | 按 `user_id` 把 D1 中 `pushed` 推荐物化为通知，供 VPS / 运维调用 |

### 3.3 物化规则

- `GET /api/notifications` 与 `GET /api/notifications/unread-count` 前先执行一次惰性物化：
  - 查询 `(user_id = 当前用户 OR user_id IS NULL) AND status = 'pushed'` 且尚未生成通知的推荐；
  - 每条生成一条 `type='recommendation'` 通知，`recommendation_id` 唯一约束保证幂等；
  - 通知标题为 `owner/name`，正文优先 `description`，其次 `reason`，并保存匹配度 / 理由 / 语言 / Star / `basedOn`。
- 已读只改 `notifications.status`，不回写推荐状态；忽略会同步把关联推荐置为 `dismissed`，避免后续再次推送。

## 4. Admin

- 新增 `features/notifications/`：`api.ts`（含演示数据兜底与纯函数）、`index.tsx`（通知中心页面）、`notifications.test.ts`；
- 新增路由 `routes/_authenticated/notifications/index.tsx`（路径 `/notifications`）；
- 侧边栏「总览」增加「通知中心」，AppSidebar 轮询未读数并显示徽标；
- 页面能力：
  - 全部 / 未读 / 已读筛选；
  - 未读数、分页、加载 / 空态 / 错误提示；
  - 单条标记已读、全部已读、忽略；
  - 展示匹配度、推荐理由、语言 / Star、相对时间与外链。

## 5. 文件清单

- `edge/migrations/0010_notifications.sql`（新增）
- `edge/src/notifications/helpers.ts`（新增：DTO、状态归一化、物化行构造等纯函数）
- `edge/src/routes/notifications.ts`（新增：登录态 + 内部接口）
- `edge/src/index.ts`、`edge/src/types.ts`、`edge/package.json`、`edge/scripts/notification-route.test.mjs`
- `admin/src/features/notifications/{api.ts,index.tsx,notifications.test.ts}`（新增）
- `admin/src/routes/_authenticated/notifications/index.tsx`（新增）
- `admin/src/components/layout/app-sidebar.tsx`、`admin/src/components/layout/data/sidebar-data.ts`、`.gitignore`
- 文档：`docs/architecture/{overview,data-model}.md`、`docs/assets/d1-schema.sql`、`docs/requirements/backlog.md`、`edge/README.md`、`admin/README.md`

## 6. 验证计划

- `cd edge && npm run typecheck`：0 error；
- `cd edge && npm run test:notifications`：纯函数用例通过；
- `cd admin && npm run lint && npm run build && npm run test`：全绿；
- `git diff --check`：无空白错误；
- 不访问网络：admin 演示数据兜底，edge 测试只测纯函数。

## 7. 风险与边界

- M4-01 / M3-05 尚未合并时，D1 中没有 `pushed` 推荐，通知中心显示空态；合并后自动生效，无需改代码；
- 惰性物化在列表 / 未读数请求时执行，单次最多 100 条，避免大查询；后续如需实时推送可由内部接口写入；
- 通知只存 D1，不涉及 Bark / Telegram / Email（M4-03~05）；
- 推送偏好、去重与静默策略、送达回执分别由 M4-06~08 承接，本需求只提供站内通道基础。
