# 安全加固运维手册（M5-05 / REQ-202610-0943）

覆盖接口限流、登录防护与内部令牌轮换。所有操作均不回显令牌明文，只输出 sha-256 前 12 位指纹。

## 1. 限流

### edge（Cloudflare Workers + D1）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | `true` | `0` / `false` / `off` / `no` 关闭 |
| `RATE_LIMIT_READ_PER_MINUTE` | `300` | GET / HEAD / OPTIONS |
| `RATE_LIMIT_WRITE_PER_MINUTE` | `60` | POST / PUT / PATCH / DELETE |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | `/api/auth/*` |
| `RATE_LIMIT_WINDOW_SECONDS`（代码内固定） | `60` | 固定窗口长度 |

- 桶键：`<scope>:<sha256(scope:user:<id> | scope:ip:<ip>)>`，不存明文 IP；
- 响应头：`X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset`；超限 429 + `Retry-After`；
- `/api/internal/*` 不限流，由 `X-Internal-Token` 保护；
- D1 异常时 fail-open（放行并写 `console.error`），避免限流故障拖垮登录与业务。

### VPS（FastAPI 进程内滑动窗口）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | `true` | 关闭后完全放行 |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | 滑动窗口长度 |
| `RATE_LIMIT_MAX_REQUESTS` | `600` | 普通接口上限 / 窗口 |
| `RATE_LIMIT_HEAVY_MAX_REQUESTS` | `120` | 重接口上限 / 窗口（`/api/tasks`、`/api/vector-index`、`/api/search`、`/api/recommend/eval`） |
| `RATE_LIMIT_TRUST_PROXY` | `true` | 信任 `X-Forwarded-For` 第一跳；仅当 VPS 位于可信反向代理后开启 |

> 进程内计数按 worker 独立；多 worker / 多机部署需改用 Redis 全局限流（见 open-questions Q14）。

## 2. 登录防护

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LOGIN_MAX_FAILURES` | `10` | 失败窗口内阈值 |
| `LOGIN_FAILURE_WINDOW_SECONDS` | `900` | 失败统计窗口 |
| `LOGIN_LOCKOUT_SECONDS` | `900` | 触发后的锁定时长 |

- 失败原因：`invalid_oauth_state` / `github_token_exchange_failed` / `github_user_fetch_failed`；
- 锁定期内回调返回 429 `login_locked` + `Retry-After`；
- 登录成功清除该 IP 哈希的失败计数；
- 身份仅存 `sha256('login:' + IP)`，事件写入 `security_events`。

## 3. 内部令牌轮换（两阶段）

前置：运行目录 `.env`（默认 `/opt/openfactory/.env`，600）已由 `bootstrap-runtime.sh` 初始化。

```bash
# 1) 生成新令牌（写入 600 临时文件，仅输出指纹）
deploy/scripts/rotate-internal-token.sh --generate

# 2) 应用双令牌：新令牌 → INTERNAL_TOKEN，旧令牌 → INTERNAL_TOKEN_PREVIOUS
deploy/scripts/rotate-internal-token.sh --apply --token-file /opt/openfactory/.internal-token.new

# 3) 同步 edge 机密并重启 VPS
deploy/scripts/deploy-edge.sh --env-file deploy/env/deploy.env
systemctl restart openfactory-api openfactory-worker openfactory-beat

# 4) 验证两端（把 <token> 换成新令牌，命令本身不要写进日志/脚本历史）
curl -H "X-Internal-Token: <token>" https://api.<domain>/api/internal/security/status
curl -H "X-Internal-Token: <token>" http://127.0.0.1:8000/api/security/status

# 5) 全链路验证通过后清空过渡位并再次部署
sed -i 's/^INTERNAL_TOKEN_PREVIOUS=.*/INTERNAL_TOKEN_PREVIOUS=/' /opt/openfactory/.env
deploy/scripts/deploy-edge.sh --env-file deploy/env/deploy.env
systemctl restart openfactory-api openfactory-worker openfactory-beat

# 随时查看指纹（不显示明文）
deploy/scripts/rotate-internal-token.sh --status
```

注意：

- 第 2~4 步之间两端都接受新旧两枚令牌，任何一端先重启都不会中断内部调用；
- 过渡位存在期间 `rotationPending=true`，完成后应为 `false`；
- 令牌不得写入仓库、命令行历史或聊天记录；`--generate` 的临时文件用后即删。

## 4. 安全数据清理

- edge 每 200 次受保护请求触发一次机会式清理；也可手动调用
  `POST /api/internal/security/cleanup`（带 `X-Internal-Token`）；
- 清理范围：过期的 `rate_limit_counters`、30 天前的 `login_attempts`、90 天前的 `security_events`；
- 返回 `{ok:true, deleted:{counters, loginAttempts, securityEvents}}`。

## 5. 排查

| 现象 | 排查 |
| --- | --- |
| 大量 429 `rate_limited` | 查 `security_events` 的 `event_type=rate_limited` 与 `detail` 中的 scope；确认是否单一 IP / 用户 |
| 登录 429 `login_locked` | 查 `login_attempts` 最近失败原因；确认阈值是否过低 |
| 内部调用 401 | 核对两端令牌指纹是否一致；轮换过渡期确认 `INTERNAL_TOKEN_PREVIOUS` 已同步 |
| 内部调用 503 `internal_token_not_configured` | 目标端未配置 `INTERNAL_TOKEN`，按部署手册注入 secret |
