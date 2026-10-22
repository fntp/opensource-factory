# 实施计划 · REQ-202610-0895 GitHub OAuth App 注册与登录全链路联调

> 对应需求：REQ-202610-0895（backlog M1-03 / IT-0005）｜ 分支：`feat/req-202610-0895-github-oauth`｜ 日期：2026-10-22

## 1. 目标

在无真实 GitHub OAuth App（Q3 人工资源未就绪）的前提下，把「注册配置 → 授权跳转 → 回调换 token → 拉取用户 → 建会话 → 前端取用户 → 登出」整条链路做成**可本地复现、可自动化验证**的闭环，并给出正式 OAuth App 的注册与切换步骤。

## 2. 现状与约束

- `edge/src/routes/auth.ts` 与 `edge/src/auth.ts` 已有登录 / 回调 / me / logout 骨架，但存在三处影响真实联调的问题：
  1. 换 token 未携带 `redirect_uri`，与 authorize 阶段不一致时 GitHub 会拒绝；
  2. `/user` 的 `email` 可能为 null（用户设为私有），未回退 `/user/emails`；
  3. OAuth 端点写死官方地址，无法在本地用 mock 完成全链路验证。
- OAuth App 注册必须由维护者在 GitHub 网页完成（GitHub 不提供 OAuth App 的创建 API），本任务交付**注册清单 + 本地回调地址 + 配置步骤**，不伪造 Client ID / Secret。
- 约束：不强推、不删他人分支；任何真实 token / secret 不入库、不回显；本地验证数据写入 `.wrangler/`（已 gitignore）。

## 3. 方案

### 3.1 边缘鉴权加固（`edge/src/auth.ts`、`edge/src/routes/auth.ts`）

| 改动 | 说明 |
| --- | --- |
| 回调地址统一 | 新增 `buildCallbackUrl(c)`；authorize 与 token 交换使用**同一个** `redirect_uri`（不含业务 query，回跳目标改存 state cookie） |
| state cookie 结构化 | 存 `{state, redirect}`（URL 编码 JSON），回调时一次性校验并清除；兼容旧纯 state 值 |
| token 交换 | `exchangeGithubCode(env, code, redirectUri)` 显式携带 `redirect_uri`，并识别 GitHub 200 响应里的 `error` |
| 邮箱回退 | `/user` 无 email 时调用 `/user/emails`，优先 primary + verified |
| 可配置端点 | 新增可选 `GITHUB_OAUTH_BASE_URL` / `GITHUB_API_BASE_URL`，缺省官方地址，供本地 mock 使用 |
| 错误分支 | GitHub 返回 `error=access_denied` 时返回 `oauth_denied`，不再误报 state 错误 |

### 3.2 本地全链路联调工具

| 文件 | 说明 |
| --- | --- |
| `edge/scripts/mock-github-oauth.mjs` | 零依赖 mock GitHub：`/login/oauth/authorize`、`/login/oauth/access_token`、`/user`、`/user/emails` |
| `edge/scripts/oauth-e2e.mjs` | 启动 mock + `wrangler dev`（临时端口、本地 D1），用真实 HTTP 走完整登录链路并断言：登录 302、state 校验、token 交换、用户 upsert、会话 cookie、`/me`、登出 401、CSRF 负例、开放重定向回退 |

### 3.3 注册与配置文档

- 新增 `docs/guides/github-oauth-setup.md`：本地 / 正式两套 OAuth App 字段、回调地址、`wrangler` vars / secrets、admin 环境变量、联调清单与常见错误排查；
- 同步 `edge/README.md`、`edge/wrangler.toml`、`edge/.dev.vars.example`、`docs/architecture/overview.md`、`docs/requirements/open-questions.md`（Q3）、`docs/planning/task-planning.md`（IT-0005）。

## 4. 验证

```bash
cd edge
bacs-heavy npm ci
npm run test:oauth     # mock GitHub + wrangler dev 全链路
npm run typecheck
```

## 5. 文件清单

| 文件 | 说明 |
| --- | --- |
| `edge/src/auth.ts` / `edge/src/routes/auth.ts` / `edge/src/types.ts` | OAuth 全链路加固 |
| `edge/scripts/mock-github-oauth.mjs` / `edge/scripts/oauth-e2e.mjs` | 本地 mock 与端到端验证 |
| `edge/package.json` / `edge/wrangler.toml` / `edge/.dev.vars.example` | 脚本与配置模板 |
| `edge/README.md` / `docs/guides/github-oauth-setup.md` / `docs/architecture/overview.md` | 使用与架构文档 |
| `docs/requirements/open-questions.md` / `docs/planning/task-planning.md` | 人工事项与迭代状态 |
