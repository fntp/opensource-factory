# 实施计划 · REQ-202610-0896 会话安全加固

> 对应需求：REQ-202610-0896（backlog M1-04）｜ 分支：`feat/req-202610-0896-session-security`｜ 日期：2026-10-22｜ 状态：已完成

## 1. 目标

在现有 GitHub OAuth + D1 会话基础上补齐三块安全能力：

1. **Secure Cookie**：生产 HTTPS 下会话 Cookie 强制 `Secure`，并保留 `HttpOnly` / `SameSite=Lax` / `Path=/`；提供 `COOKIE_SECURE` 显式覆盖，兼容反向代理与本地开发；
2. **过期清理**：会话过期后除请求时惰性删除外，增加登录时的用户级清理与 Worker 每日定时清理，避免 `sessions` 表无限增长；
3. **登出全端**：`POST /api/auth/logout` 支持 `{ "all": true }`（或 `?all=true`），删除当前用户全部会话；admin 退出确认框提供「同时退出所有设备」选项。

## 2. 现状与约束

- `edge/src/auth.ts` 已有随机 token + SHA-256 存储、30 天过期时间与 Cookie 基础属性；但 `Secure` 仅按请求协议判断，且没有全局清理任务；
- `POST /api/auth/logout` 只删除当前会话；
- `sessions` 表已有 `(user_id)` 与 `(expires_at)` 索引，无需新增迁移；
- 安全红线见 `docs/standards/project-spec.md` §7 与 `docs/standards/code-constraints.md`：token 不落明文、Cookie `httpOnly`、生产 `Secure`；
- 本需求不改表结构，避免与 M1-02（D1 迁移）产生迁移顺序耦合。

## 3. 方案

### 3.1 Cookie 加固（edge）

- 抽出 `cookieSecure(c)`：优先读 `COOKIE_SECURE`（`true` / `false`），缺省按请求 URL 是否为 `https:` 判断；
- 会话与 OAuth state Cookie 统一走 `buildSetCookie`：`HttpOnly; SameSite=Lax; Path=/`，生产追加 `Secure`；
- 清除 Cookie 时复用同一组属性（含 `Secure`），确保浏览器能正确覆盖；
- 认证路由统一返回 `Cache-Control: no-store`，避免登录态被中间层缓存。

### 3.2 过期会话清理（edge）

- `cleanupExpiredSessions(db)`：按 `expires_at <= now(ISO)` 删除全部过期会话，返回删除条数；
- `cleanupExpiredSessionsForUser(db, userId)`：登录建会话前清理该用户过期会话；
- `getSessionUser` 对非法 `expires_at`（`NaN`）按过期处理并删除，避免异常数据被当作有效会话；
- `wrangler.toml` 增加 `[triggers] crons = ["17 3 * * *"]`，`index.ts` 导出 `scheduled` 处理器调用全局清理。

### 3.3 登出全端（edge + admin）

- `POST /api/auth/logout` 解析 JSON body（容错空 body）与查询参数：
  - `{ "all": true }` / `?all=true` / `?scope=all` → `DELETE FROM sessions WHERE user_id = ?`；
  - 否则维持原有单会话删除；
  - 两种情况都清除浏览器 Cookie，返回 204；
- admin `logout({ all })` 按需发送 JSON body；退出确认框新增「同时退出所有设备」复选框，默认不勾选，保持原行为。

## 4. 文件清单

| 文件 | 说明 |
| --- | --- |
| `edge/src/auth.ts` | Cookie Secure 策略、过期清理、全端登出辅助、非法过期时间兜底 |
| `edge/src/routes/auth.ts` | 登出全端参数解析、认证响应 no-store |
| `edge/src/index.ts` | 导出 `scheduled` 处理器 |
| `edge/src/types.ts` | `Env.COOKIE_SECURE` |
| `edge/wrangler.toml` | 每日 Cron Trigger |
| `edge/README.md` | 环境变量与接口说明 |
| `admin/src/lib/api.ts` | `logout({ all })` |
| `admin/src/components/sign-out-dialog.tsx` | 全端退出选项 |
| `admin/src/components/sign-out-dialog.test.tsx` | 覆盖全端退出调用 |
| `docs/architecture/overview.md` | 安全边界与接口契约 |
| `docs/architecture/data-model.md` | 会话清理说明 |
| `docs/planning/plan-req-202610-0896-session-security.md` | 本计划 |

## 5. 验收标准

1. 生产 HTTPS 下 `Set-Cookie` 含 `Secure`，本地 HTTP 开发不强制，`COOKIE_SECURE` 可覆盖；
2. 过期会话在请求、登录、每日 Cron 三个路径均会被清理；
3. `POST /api/auth/logout {"all":true}` 后该用户全部会话失效，其他设备再请求 `/api/auth/me` 返回 401；
4. admin 退出框勾选「同时退出所有设备」时调用全端登出，不勾选时行为不变；
5. `cd edge && npm run typecheck`、`cd admin && npm run lint && npm run build && npm run test` 全绿；
6. 文档同步完成，无密钥入库。

## 6. 风险与人工事项

- Cloudflare Cron Trigger 需在部署后由平台生效，本地 `wrangler dev` 不触发；部署检查清单需确认 `triggers` 已随 Worker 发布；
- `COOKIE_SECURE` 未设置时按请求协议自动判断，若生产经非 HTTPS 反代终止 TLS，需显式设为 `true`；
- 全端登出依赖当前会话能解析出 `user_id`；Cookie 已失效时仅清理本地 Cookie（幂等）。

## 7. 验证结果（2026-10-22）

- `cd edge && npm run typecheck`：通过（0 error）；
- `cd admin && npm run lint`：通过；
- `cd admin && npm run build`：通过（含 `routeTree.gen.ts` 重新生成）；
- `cd admin && npm run test`：10 个测试文件、74 条用例全部通过；
- 本地 `wrangler dev` 冒烟：`/api/auth/me` 200 且 `Cache-Control: no-store`；`POST /api/auth/logout {"all":true}` 后同用户另一会话访问 `/me` 返回 401；`COOKIE_SECURE=true` 时清除 Cookie 带 `Secure`；`/__scheduled` 触发后过期会话计数归零。
- 附带修复：`.gitignore` 的 `**/data/` 误伤 `admin/src/components/layout/data/sidebar-data.ts`，导致 admin 构建基线失败；已加例外并补回导航数据文件。
