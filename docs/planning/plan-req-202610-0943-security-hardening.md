# 实施计划 · REQ-202610-0943 接口限流与安全加固

> 需求：REQ-202610-0943（backlog M5-05）｜ 分支：`feat/req-202610-0943-security-hardening`
> 依赖：M5-01（REQ-202610-0939 正式部署工具链）｜ 基线：`feat/req-202610-0939-production-deploy` @ `93dc6cb`

## 1. 现状与缺口

- edge 公开 API 没有任何限流：`/api/auth/*`、`/api/*` 可被脚本高频刷取；D1 写接口（收藏 / 同步 / 反馈）同样无频控；
- 登录链路只校验 OAuth state，没有失败计数与锁定，攻击者可反复触发回调 / 换 token；
- `X-Internal-Token` 校验在 5 个 edge 路由中各自实现，使用普通字符串比较，且只支持单一令牌，轮换必须停机；
- VPS 内部接口同样只支持单一 `INTERNAL_TOKEN`，无进程级限流；
- 缺少安全事件与轮换操作的可观测口径。

## 2. 方案总览

```
公网请求
  → edge Worker
      ├─ 会话解析（现有）
      ├─ 限流中间件（D1 固定窗口，按 用户/匿名 IP 哈希 + 策略桶）
      │    ├─ auth  ：10 次/分钟（登录跳转 + 回调）
      │    ├─ write ：60 次/分钟（POST/PUT/DELETE）
      │    └─ read  ：300 次/分钟（GET）
      ├─ 登录防护（失败计数 → 锁定；成功清零；security_events 审计）
      └─ 内部接口（双令牌校验：INTERNAL_TOKEN + INTERNAL_TOKEN_PREVIOUS）

本机 VPS
  → FastAPI 限流中间件（进程内滑动窗口，按 IP + 路径前缀）
  → require_internal_token（双令牌，hmac.compare_digest）
  → GET /api/security/status（内部令牌保护，输出配置与指纹，不输出令牌）
```

设计要点：

1. **限流状态放 D1**：Workers 无状态，固定窗口计数表 `rate_limit_counters` 以 `(scope, identity_hash, window_start)` 为键，单条 UPSERT 原子累加；D1 异常时 fail-open（记日志），优先保证可用性。
2. **不落明文 IP**：限流与登录失败均只存 `sha256(scope:ip)` 或 `sha256(user:<id>)`，满足隐私边界；响应头只暴露配额与重置时间。
3. **登录防护分级**：同一 IP 在 `LOGIN_FAILURE_WINDOW_SECONDS` 内失败 `LOGIN_MAX_FAILURES` 次后锁定 `LOGIN_LOCKOUT_SECONDS`；成功登录清零；失败原因只记枚举（`invalid_state` / `token_exchange_failed` / `user_fetch_failed`）。
4. **双令牌轮换**：两端同时接受 `INTERNAL_TOKEN`（当前）与 `INTERNAL_TOKEN_PREVIOUS`（上一枚）；轮换分两阶段：新令牌写入当前、旧令牌降为 previous → 全链路验证 → 删除 previous。提供 `deploy/scripts/rotate-internal-token.sh` 生成 / 应用。
5. **VPS 限流为进程内滑动窗口**：单节点 uvicorn 部署，无需 Redis；`RATE_LIMIT_ENABLED=0` 可关闭（测试 / 排障），默认开启且阈值高于 edge。

## 3. 数据模型（edge D1，迁移 `0011_security_hardening.sql`）

| 表 | 字段 | 说明 |
| --- | --- | --- |
| `rate_limit_counters` | `bucket` TEXT PK、`window_start` INTEGER、`count` INTEGER、`expires_at` TEXT | 固定窗口计数；bucket = `scope:identityHash` |
| `login_attempts` | `id` INTEGER PK、`ip_hash` TEXT、`outcome` TEXT、`reason` TEXT、`created_at` TEXT | 登录失败 / 成功审计；索引 `(ip_hash, created_at)` |
| `security_events` | `id` INTEGER PK、`event_type` TEXT、`actor_hash` TEXT、`detail` TEXT、`created_at` TEXT | 限流触发 / 令牌状态 / 清理等安全事件 |

`rate_limit_counters` 按 `expires_at` 建索引，内部清理接口与 1% 概率的请求内清理删除过期行。

## 4. 接口与配置

### 4.1 edge

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/api/internal/security/status` | GET | `X-Internal-Token` | 限流 / 登录防护 / 双令牌状态（指纹，不含明文） |
| `/api/internal/security/cleanup` | POST | `X-Internal-Token` | 清理过期限流计数与登录审计 |

新增 Worker 变量：`RATE_LIMIT_ENABLED`、`RATE_LIMIT_READ_PER_MINUTE`、`RATE_LIMIT_WRITE_PER_MINUTE`、`RATE_LIMIT_AUTH_PER_MINUTE`、`LOGIN_MAX_FAILURES`、`LOGIN_FAILURE_WINDOW_SECONDS`、`LOGIN_LOCKOUT_SECONDS`；机密新增 `INTERNAL_TOKEN_PREVIOUS`（可选）。

### 4.2 VPS

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/api/security/status` | GET | `X-Internal-Token` | 双令牌 / 限流配置状态 |

新增配置：`INTERNAL_TOKEN_PREVIOUS`、`RATE_LIMIT_ENABLED`、`RATE_LIMIT_WINDOW_SECONDS`、`RATE_LIMIT_MAX_REQUESTS`、`RATE_LIMIT_AUTH_MAX_REQUESTS`、`RATE_LIMIT_TRUST_PROXY`。

### 4.3 部署脚本

- `deploy/scripts/rotate-internal-token.sh`：`--generate`（默认）生成 32 字节令牌到 600 文件；`--apply --env-file` 原子更新运行目录 `.env`（当前 → previous，新令牌 → 当前），打印后续 `deploy-edge.sh` / 重启步骤，不回显令牌；
- `deploy/scripts/bootstrap-runtime.sh`：初始化时同时写入空的 `INTERNAL_TOKEN_PREVIOUS=`；
- `deploy/scripts/deploy-edge.sh`：若配置了 `INTERNAL_TOKEN_PREVIOUS` 则同步为 Worker 机密。

## 5. 测试与验收

| 层 | 用例 |
| --- | --- |
| edge | `scripts/security-route.test.mjs`：策略分桶、窗口计算、Retry-After、令牌双校验 / 指纹、登录锁定判定、清理 SQL 参数 |
| vps | `tests/test_security.py`：双令牌接受 / 拒绝、常量时间比较路径、限流窗口与 429、状态接口、配置与部署资产一致 |
| 部署 | `vps/tests/test_deploy_assets.py`：轮换脚本 help / 模板键一致性 |

验收标准：

1. 超过阈值的请求返回 429，带 `Retry-After` 与 `X-RateLimit-*`，D1 异常时不阻塞业务；
2. 同一 IP 连续登录失败达到阈值后被锁定，成功登录后计数清零；
3. 配置 `INTERNAL_TOKEN` 与 `INTERNAL_TOKEN_PREVIOUS` 时两枚令牌都可用，删除 previous 后旧令牌立即失效；
4. 轮换脚本不向 stdout / 日志输出令牌明文；
5. edge typecheck + node:test、vps pytest 全绿，部署资产测试通过。

## 6. 风险与后续

- D1 限流每次请求多一次读写：读接口阈值较高，写接口低频；如流量上来可迁移 Cloudflare Rate Limiting 规则，接口契约保持不变；
- 固定窗口存在临界双倍突发，安全场景可接受；后续可换滑动窗口；
- VPS 进程内限流在多 worker 部署时按进程独立计数，需在扩容时改为 Redis；
- 登录防护按 IP 计数，NAT 出口可能误伤，阈值默认 10 次 / 15 分钟，可按 open-questions 调整。
