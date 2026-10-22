# 实施计划 · REQ-202610-0906 admin 关闭演示模式、真实接口联调

> 需求：REQ-202610-0906（backlog M1-14）｜ 分支：feat/req-202610-0906-admin-real-api
> 依赖：M1-05~13（同步 / 分类 / 标签 / 检索 / 摘要；对应分支并行开发，本分支基于共同集成基线 `feat/req-202610-0746-writeback`）

## 1. 目标与范围

把 admin 从「演示数据兜底」切换为「真实边缘 API + 明确的状态呈现」：

1. **关闭演示模式**：移除 `VITE_DEMO_MODE`、演示登录入口、演示会话 Cookie 与所有 `MOCK_*` 数据兜底；API 失败时不再静默展示假数据。
2. **登录态**：启动时通过 `GET /api/auth/me` 恢复会话；401 跳转登录页；网络 / 5xx 显示可重试错误态；退出登录清理本地状态与查询缓存。
3. **空态**：仓库、热榜、推荐、分类 / 标签、仪表盘热榜均区分「加载中 / 空数据 / 搜索无结果」。
4. **错误态**：统一 `ApiHttpError`（状态码 + 后端错误码），页面级错误卡片支持重试；全局 401 / 403 / 5xx / 网络错误统一提示。
5. **真实接口联动**：仓库页「同步仓库」调用 `POST /api/sync`，展示排队 / VPS 未配置 / 失败结果；仪表盘 Star 图改为真实仓库数据分布。

不在本次范围：分类 / 标签 CRUD、同步任务页（分别由 M1-08~10 分支交付，本分支只提供可复用的请求与状态组件）。

## 2. 现状问题

- `lib/api.ts` 在 `VITE_API_BASE_URL` 为空时自动进入演示模式，`fetchWithFallback` 吞掉所有错误并返回 `MOCK_*`；
- 登录页提供「进入演示模式」，`auth-store` 用明文 Cookie 持久化假用户；
- 各页面 `data ?? MOCK_*`，接口失败时用户无法感知；
- 全局 QueryCache 只识别 `AxiosError`，而项目实际使用 `fetch`，401 不会触发重新登录；
- 仓库同步按钮只弹「演示」toast。

## 3. 方案

### 3.1 API 层

- `API_BASE = VITE_API_BASE_URL || ''`（空值表示同源，开发期由 Vite 代理 `/api` 到 edge）；
- 删除 `DEMO_MODE` / `fetchWithFallback`；
- `ApiHttpError` 增加 `code` / `detail`，解析后端 `{ error, message }`；
- `apiFetch` 统一 `Accept: application/json`、15s 超时、204 处理；
- 新增 `apiErrorMessage(error, fallback)` 中文文案映射。

### 3.2 登录态

- `auth-store` 只保留内存态 `user`，删除演示 Cookie 与 `saveDemoSession`；
- `AuthenticatedLayout` 状态机：`checking → ready | unauthenticated | error`；401 跳登录、其他错误显示重试；
- `main.tsx` QueryCache 改用 `ApiHttpError`：401 重置并跳登录、403 提示无权限、5xx 提示服务异常、网络错误提示无法连接；
- 登录页删除演示入口，展示 OAuth 回调错误提示。

### 3.3 空态 / 错误态

- 新增 `components/data-state.tsx`：`LoadingState` / `EmptyState` / `ErrorState`；
- 所有列表页使用 `isPending` / `isError` / `data.length === 0` 三态渲染；
- 搜索无结果与「尚无数据」使用不同文案与操作。

### 3.4 真实接口联动

- 仓库页：`useMutation` 调用 `POST /api/sync`；`202 queued` → 成功提示（含 taskId）；`accepted + vps node not configured` → 警告；失败 → 错误提示；成功后失效仓库查询；
- 仪表盘：Star 图改为基于 `/api/repos` 的真实 Star 分布（Top 8），移除硬编码演示序列；
- 推荐页：移除「加入收藏（演示）」占位按钮。

## 4. 文件清单

- `admin/src/lib/api.ts`、`admin/src/lib/handle-server-error.ts`、`admin/src/main.tsx`
- `admin/src/stores/auth-store.ts`、`admin/src/components/layout/authenticated-layout.tsx`
- `admin/src/components/data-state.tsx`（新增）
- `admin/src/features/auth/sign-in/components/github-auth-form.tsx`
- `admin/src/features/dashboard/*`、`repos/*`、`trending/*`、`recommend/*`、`categories/*`
- `admin/src/components/layout/data/sidebar-data.ts`（补回被 .gitignore 误伤的构建基线）
- `.gitignore`、`admin/.env.example`、`admin/vite.config.ts`
- 测试：`admin/src/lib/api.test.ts`、`admin/src/components/data-state.test.tsx`、更新 `auth-store.test.ts` / `handle-server-error.test.ts`
- 文档：`docs/architecture/overview.md`、`docs/guides/dev-cycle.md`、`docs/requirements/open-questions.md`（Q6）、`docs/standards/code-constraints.md`、`docs/planning/task-planning.md`、`docs/requirements/backlog.md`

## 5. 验证

- `cd admin && npm run lint && npm run build && npm run test`
- `cd edge && npm run typecheck`
- 本地联调：`wrangler dev` + 本地 D1 种子数据，curl 验证 `/api/auth/me` 401、登录后 200、`/api/repos` 空态与数据态、`POST /api/sync`；
- admin dev server 走 Vite `/api` 代理，浏览器验证登录跳转、空态、错误态与重试。

## 6. 风险与人工事项

1. 依赖分支（M1-08~13）尚未合并，其新增页面需在合并后沿用本分支的 `apiFetch` / `DataState` 模式；
2. 真实 GitHub OAuth App 仍待 Q3 人工资源；本地用 mock / 种子会话验证；
3. 生产部署必须配置 `VITE_API_BASE_URL`（或与 edge 同源），否则请求会打到静态站点同源路径。
