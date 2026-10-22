# 安全审计指南（M5-08 / REQ-202610-0946）

覆盖依赖漏洞扫描、配置基线检查与隐私边界复核。审计工具**只读**，不修改运行配置、不启动 / 停止服务、不输出密钥明文。

## 1. 运行方式

```bash
# 离线静态审计（默认；CI / 无网络环境）
deploy/scripts/security-audit.sh

# 机器可读报告
deploy/scripts/security-audit.sh --json

# 严格门禁：high / critical 退出码 1
deploy/scripts/security-audit.sh --strict

# 在线依赖漏洞扫描（npm audit + pip-audit；需要网络）
deploy/scripts/security-audit.sh --online --strict

# 额外检查真实运行配置（只读，不打印值）
deploy/scripts/security-audit.sh --runtime-env /opt/openfactory/.env --strict
```

也可以直接从 `vps/` 运行：

```bash
cd vps
python -m app.security_audit --root .. --json
```

退出码：`0` 通过 / 仅有 medium 及以下；`1` 存在 critical（默认）或存在 high（`--strict`）；`2` 参数 / 根目录错误。

## 2. 检查项

| 检查 ID | 维度 | 内容 | 失败级别 |
| --- | --- | --- | --- |
| `secret-scan` | 密钥 | GitHub PAT、AWS / Google / Slack / Stripe / OpenAI Key、私钥块、高熵凭据赋值 | high / medium |
| `tracked-env` | 密钥 | `.env` 是否被 git 跟踪、`.gitignore` 是否覆盖 | high / medium |
| `dependency-lock` | 依赖 | npm lockfile 版本 / integrity / HTTP 源；Python 依赖是否固定版本 | high / medium |
| `dependency-vuln` | 依赖 | `--online` 时执行 npm audit / pip-audit，仅报 high / critical | high / critical |
| `config-cors` | 配置 | 生产模板 / 运行配置禁止 `CORS_ORIGINS=*`、`ALLOWED_ORIGIN=*` | high |
| `config-rate-limit` | 配置 | 生产模板 / 运行配置不得关闭限流 | high |
| `config-internal-token` | 配置 | 运行配置内部令牌长度 ≥ 32 字符 | high / medium |
| `session-cookie` | 配置 | Cookie 必须含 `HttpOnly`、`SameSite=Lax`、HTTPS `Secure` | high |
| `security-headers` | 配置 | edge 使用 `secureHeaders`；VPS 使用 `SecurityHeadersMiddleware` | high / medium |
| `privacy-log` | 隐私 | 日志调用不得直接输出 email / token / cookie / authorization / password | high |
| `privacy-lifecycle` | 隐私 | 数据主体导出 / 删除与保留期清理（M9-06） | medium |

## 3. 2026-10-22 基线结果

基线：`feat/req-202610-0943-security-hardening` @ `65f6cc2`（含 M5-01 部署工具链与 M5-05 安全加固）。

离线审计：

```
结果: WARN
发现: CRITICAL 0 / HIGH 0 / MEDIUM 2 / LOW 0 / INFO 0 / 合计 2
- dependency-lock: Python 依赖未锁定精确版本（13 条）
- privacy-lifecycle: 缺少用户数据导出 / 删除接口
```

在线依赖扫描：

| 范围 | 工具 | 结果 |
| --- | --- | --- |
| `admin/` | `npm audit --package-lock-only` | 0 漏洞（升级 Vitest 4.1.12 前有 6 个 moderate，均为 dev 依赖） |
| `edge/` | `npm audit --package-lock-only` | 0 漏洞 |
| `vps/` | `pip-audit --path .venv/.../site-packages` | 0 个已知漏洞（47 个已安装包） |

## 4. 本轮整改

1. **Vitest dev 依赖漏洞（moderate）**：`vitest` / `@vitest/browser-playwright` / `@vitest/coverage-v8` / `@vitest/ui` 由 4.1.11 升级到 4.1.12，`vitest-browser-react` 升级到 2.3.0；`admin` 的 `npm audit` 归零。均为开发依赖，不进入生产包。
2. **edge 安全响应头**：接入 `hono/secure-headers` 的 `secureHeaders()`，补充 nosniff / frame / referrer / HSTS 等基线头。
3. **VPS 安全响应头**：新增 `SecurityHeadersMiddleware`，补充 nosniff / frame / referrer / permissions / COOP，认证路径加 `Cache-Control: no-store`。
4. **CORS 安全默认**：`vps/app/config.py` 与 `vps/.env.example` 的默认值由 `*` 改为 `http://localhost:5173`，生产通过 `CORS_ORIGINS` 显式配置；生产模板保持精确 origin。
5. **可复跑审计**：新增 `vps/app/security_audit.py`、`deploy/scripts/security-audit.sh`、CI `security` job 与本文档。

## 5. 隐私边界清单

| 数据 | 字段 / 位置 | 目的 | 保留期 | 备注 |
| --- | --- | --- | --- | --- |
| GitHub 账号 | `users.id/login/name/email/avatar_url`（D1） | 登录、展示、推荐归属 | 保留至账号删除（M9-06） | 仅 OAuth 获取；不采集密码 |
| 会话 | `sessions.id`（token 的 sha-256）、`user_id`、`expires_at` | 登录态 | 过期即清理（最长 30 天） | Cookie `HttpOnly; SameSite=Lax; Secure(HTTPS)` |
| 登录审计 | `login_attempts.ip_hash`、`outcome`、`reason` | 防暴力破解 | 30 天 | 只存 `sha256('login:'+IP)`，不存明文 IP |
| 安全事件 | `security_events.actor_hash/detail` | 限流 / 令牌 / 清理审计 | 90 天 | 不含令牌明文 |
| 推荐 | `recommendations.user_id`、`repo_id`、`score`、`reason` | 个性化推荐 | 未收藏 90 天 / 已收藏 365 天（M9-06） | 不含邮箱 / IP |
| 站内通知 / 更新提醒 | `notifications` / `repo_updates` | 提醒 | 已读 180 天 / 未读 365 天 | 按用户隔离 |
| 扩展令牌 | `extension_tokens.token_hash` | 扩展鉴权 | 有效期内；撤销后 30 天 | 只存 SHA-256，不存明文 |
| 隐私审计 | `privacy_events`（D1 / VPS） | 导出 / 删除 / 清理审计 | 365 天 | 只存用户 id 哈希与聚合计数 |
| 热榜快照 | `trending_snapshots` 等 | 趋势展示 | 90 天（`TRENDING_RETENTION_DAYS`） | 公开数据 |
| 运行日志 | `logs/vps-api.log`（10MB × 5） | 排障 | 滚动覆盖 | 禁止打印 token / cookie / 邮箱明文 |

第三方出网点：

| 域名 | 用途 | 数据 |
| --- | --- | --- |
| `github.com` / `api.github.com` | OAuth 登录、仓库 / Star 同步 | OAuth code、公开仓库元数据 |
| `api.deepseek.com` | 可选云端摘要降级 | README 文本（不含用户身份） |
| `localhost:11434`（Ollama） | 本地摘要 / 向量 | README 文本，不出机器 |
| Cloudflare（D1 / Workers / Pages / Vectorize） | 边缘 API、会话、向量 | 上述 D1 数据与向量 |

隐私边界结论：

- 不采集密码、支付信息、精确位置、通讯录；GitHub 邮箱仅用于账号展示；
- 限流 / 登录审计只存哈希，不存明文 IP；
- 日志未发现直接输出 token / cookie / 邮箱 / 原始 IP 的调用；
- **已闭环（M9-06）**：`GET /api/privacy/export` 支持数据主体导出，
  `DELETE /api/privacy/account` 支持账号删除，D1 与 VPS 均有每日保留清理；
  完整保留期见 `guides/privacy-retention.md`。

## 6. 遗留风险与人工事项

1. **Python 依赖未锁定**（medium）：`vps/requirements*.txt` 使用 `>=` 下限。建议生成 `requirements.lock`（`pip freeze` / `uv lock`）并在部署与 CI 使用锁定文件；本需求不强行锁定，避免牵动模型依赖。
2. **用户数据生命周期**（已闭环）：M9-06 已交付导出 / 删除接口与自动保留清理；
   备份中的历史副本仍按备份保留策略自然过期，需在隐私说明中如实告知。
3. **在线扫描时效**：`npm audit` / `pip-audit` 依赖外网与漏洞库；CI 中作为补充门禁，离线静态检查仍为主。
4. **运行配置审计**：部署机应定期执行 `security-audit.sh --runtime-env /opt/openfactory/.env --strict`；本仓库不含真实 `.env`。
5. **真实 D1 / Worker 配置**：`edge/wrangler.toml` 的 `database_id` 仍为占位符，生产渲染后应复扫 `ALLOWED_ORIGIN` 与 `RATE_LIMIT_ENABLED`。

## 7. 例外与复扫

- 确需临时关闭某项检查时，在 PR 描述中写明原因、影响面与恢复时间，不允许直接删除检查；
- 密钥误报可在 `vps/app/security_audit.py` 的占位符规则中补充标记（如 `example` / `dummy`），不要加入真实密钥白名单；
- 每次 M5 合并、依赖升级、部署配置变更后复跑：

```bash
deploy/scripts/security-audit.sh --online --strict
```
