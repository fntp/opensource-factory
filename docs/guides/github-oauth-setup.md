# GitHub OAuth App 注册与登录全链路联调指南

> 对应需求：REQ-202610-0895（backlog M1-03 / IT-0005）｜ 适用：`edge/` + `admin/`｜ 更新：2026-10-22
>
> 本期仅支持 GitHub 授权登录（不提供邮箱密码 / Gitee 登录）。本地回调先行，正式域名后置。

## 1. 两种联调模式

| 模式 | 是否需要真实 OAuth App | 覆盖范围 | 入口 |
| --- | --- | --- | --- |
| 本地 mock 全链路 | 否 | 授权跳转、state 校验、换 token、拉用户、建会话、me、登出、CSRF / 开放重定向 / 拒绝授权负例 | `cd edge && npm run test:oauth` |
| 真实 OAuth App | 是（人工注册） | 额外覆盖 GitHub 授权页、真实 Client Secret、真实用户资料 / 私有邮箱 | 本文第 4 节 |

建议顺序：先跑 mock 全链路（CI 同款），确认代码与配置无误，再注册真实 OAuth App 做人工点检。

## 2. 本地 mock 全链路（无需真实 OAuth App）

```bash
cd edge
npm ci
npm run test:oauth
```

脚本会：

1. 用 `wrangler d1 migrations apply --local` 在独立目录 `.wrangler/e2e-state-<pid>/` 建库；
2. 启动 `scripts/mock-github-oauth.mjs`（授权页 / token / user / user/emails）；
3. 启动独立端口的 `wrangler dev`，注入测试用 `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`；
4. 用真实 HTTP 走完整链路并断言 9 项检查。

预期结尾：

```
全部 9 项 OAuth 全链路检查通过。
```

排查时可加 `--keep` 保留本地 D1 状态目录：

```bash
node scripts/oauth-e2e.mjs --keep
```

## 3. 注册真实 OAuth App（本地开发）

1. 打开 GitHub → **Settings → Developer settings → OAuth Apps → New OAuth App**
   （直达：<https://github.com/settings/applications/new>）。
2. 按下表填写（**回调地址必须完全一致**，包括协议、主机、端口、路径）：

   | 字段 | 本地开发值 |
   | --- | --- |
   | Application name | `OpenFactory Local` |
   | Homepage URL | `http://localhost:5173` |
   | Application description | 可选，例如「OpenFactory 本地开发」 |
   | Authorization callback URL | `http://localhost:8787/api/auth/github/callback` |

3. 点击 **Register application**，复制 **Client ID**（非机密）。
4. 点击 **Generate a new client secret**，复制 **Client Secret**（只显示一次，按机密处理）。

### 3.1 配置 edge

```bash
cd edge
cp .dev.vars.example .dev.vars
```

编辑 `edge/.dev.vars`（已被 `.gitignore` 忽略）：

```dotenv
GITHUB_CLIENT_SECRET=<粘贴 Client Secret>
SESSION_SECRET=<openssl rand -hex 32 生成>
```

在 `edge/wrangler.toml` 的 `[vars]` 填入 Client ID：

```toml
GITHUB_CLIENT_ID = "Iv1.xxxxxxxxxxxxxxxx"
```

> `GITHUB_OAUTH_BASE_URL` / `GITHUB_API_BASE_URL` 保持空字符串（使用 GitHub 官方地址）；
> 仅 `npm run test:oauth` 会自动覆盖为本地 mock。

启动：

```bash
npm run dev          # http://localhost:8787
curl http://localhost:8787/healthz
```

### 3.2 配置 admin

在 `admin/.env.local`（本地文件，勿提交）中设置：

```dotenv
VITE_API_BASE_URL=http://localhost:8787
VITE_DEMO_MODE=false
```

启动：

```bash
cd admin
npm run dev          # http://localhost:5173
```

打开 <http://localhost:5173/sign-in>，点击「使用 GitHub 登录」：

1. 跳转 GitHub 授权页（首次会要求授权 `read:user user:email`）；
2. 同意后回到 `http://localhost:8787/api/auth/github/callback`；
3. 边缘换 token、写入 `users`、建立 `of_session` 会话；
4. 302 回前端 `redirect`（默认 `/`，登录页会带 `?redirect=`）；
5. 控制台可正常访问受保护接口，右上角显示 GitHub 用户信息。

## 4. 正式环境（域名就绪后）

建议为正式环境**单独注册**一个 OAuth App（本地 / 正式回调地址不同，避免互相覆盖）：

| 字段 | 正式值 |
| --- | --- |
| Application name | `OpenFactory` |
| Homepage URL | `https://<admin-domain>` |
| Authorization callback URL | `https://<worker-domain>/api/auth/github/callback` |

配置与发布：

```bash
cd edge
npx wrangler secret put GITHUB_CLIENT_SECRET   # 正式 App 的 secret
# wrangler.toml [vars]：GITHUB_CLIENT_ID / ALLOWED_ORIGIN=https://<admin-domain>
npm run deploy
```

admin 构建环境：

```dotenv
VITE_API_BASE_URL=https://<worker-domain>
VITE_DEMO_MODE=false
```

注意：

- HTTPS 下会话 cookie 自动附加 `Secure`；
- `ALLOWED_ORIGIN` 必须与 admin 实际 origin 完全一致（CORS 精确回显 + credentials）；
- 若 admin 与 Worker 不在同一站点（registrable domain），`SameSite=Lax` cookie 不会随跨站 XHR 发送，需部署到同一主域的不同子域；
- 修改回调地址后，GitHub 只认最新值，旧地址立即失效。

## 5. 全链路验收清单

| # | 操作 / 请求 | 期望 |
| --- | --- | --- |
| 1 | `GET /api/auth/github/login?redirect=/repos` | 302 → `https://github.com/login/oauth/authorize?...`；`Set-Cookie: of_oauth_state`（HttpOnly / SameSite=Lax / 10 分钟） |
| 2 | GitHub 授权页点击 Authorize | 302 → `https://<worker>/api/auth/github/callback?code=...&state=...` |
| 3 | 回调 | 302 → `/repos`；`Set-Cookie: of_session`；state cookie 被清除 |
| 4 | `GET /api/auth/me`（带会话） | 200 `{id, login, name, email, avatarUrl}` |
| 5 | `GET /api/repos`（带会话） | 200 数组 |
| 6 | `POST /api/auth/logout` | 204；旧 cookie 再访问 `/api/auth/me` → 401 |
| 7 | 篡改回调 `state` | 400 `{"error":"invalid_oauth_state"}` |
| 8 | `redirect=https://evil.example/...` | 登录完成后回退到 `ALLOWED_ORIGIN`，不跳外站 |
| 9 | GitHub 返回 `error=access_denied` | 400 `{"error":"oauth_denied"}` |

## 6. 常见错误排查

| 现象 / 错误码 | 常见原因 | 处理 |
| --- | --- | --- |
| 501 `github_oauth_not_configured` | `GITHUB_CLIENT_ID` 或 `GITHUB_CLIENT_SECRET` 为空 | 检查 `wrangler.toml [vars]` 与 `wrangler secret` / `.dev.vars` |
| GitHub 页面 `redirect_uri_mismatch` | 回调地址与 OAuth App 登记值不一致（`localhost` vs `127.0.0.1`、端口、路径、末尾斜杠） | 逐字符对齐；本地固定用 `http://localhost:8787/api/auth/github/callback` |
| 400 `invalid_oauth_state` | state cookie 缺失 / 过期（>10 分钟）/ 与查询参数不一致；跨站导致 cookie 未发送 | 同一浏览器窗口完成登录；检查 `SameSite` / 域名；不要刷新旧回调页重放 code |
| 502 `github_token_exchange_failed` | Client Secret 错误；code 已使用或过期；token 交换的 `redirect_uri` 不一致 | 重新生成 secret；重新走登录；确认代码已携带同一 `redirect_uri` |
| 502 `github_user_fetch_failed` | access token 无效 / 权限不足 / GitHub API 不可达 | 确认 scope 含 `read:user user:email`；查看 Worker 日志 |
| 登录成功但前端仍跳登录页 | admin `VITE_API_BASE_URL` 未配置或 `VITE_DEMO_MODE` 干扰；跨站 cookie 未带 | 配置 `VITE_API_BASE_URL`、`VITE_DEMO_MODE=false`；fetch 使用 `credentials: 'include'` |
| 邮箱为空 | 用户邮箱全部私有且未授权 `user:email` | 代码已回退 `/user/emails`；确认授权 scope 未被裁剪 |

## 7. 安全与运维注意

- **绝不提交** Client Secret / access token / `.dev.vars`；发现泄漏立即在 GitHub 重置 secret；
- 生产 secret 只放 `wrangler secret`，本地只放 `.dev.vars`（gitignored）；
- OAuth `state` 一次性使用，回调后立即清除；code 只能换一次 token；
- 仅申请最小 scope：`read:user user:email`；GitHub access token 仅在内存中使用，不落库；
- 正式 OAuth App 建议由组织账号持有，避免个人离职 / 转仓后失联；
- 本地与正式环境使用不同 OAuth App，回调地址互不覆盖。
