# 实施计划 · REQ-202610-0939 正式部署（Pages / Workers + 本机节点 + 域名 HTTPS）

> 需求：REQ-202610-0939（backlog M5-01）｜ 分支：`feat/req-202610-0939-production-deploy`
> 依赖：Q3（Cloudflare 资源信息）；M1~M4（功能与部署基线）
> 目标：把三端从「本地可跑」推进到「可重复、可自检、可回滚的生产部署」，并固化域名 / HTTPS / 密钥配置口径。

## 1. 现状与缺口

- `deploy/` 已有本机运行基线（运行目录 / Redis / systemd / env 模板，REQ-202610-0893），但只覆盖 VPS 节点；
- `edge/wrangler.toml` 的 D1 `database_id` 仍是 `REPLACE_WITH_D1_DATABASE_ID`，没有生产环境段、自定义域名与部署流程；
- admin 没有生产构建 / Pages 发布脚本，`VITE_API_BASE_URL` / `VITE_DEMO_MODE` 只写在模板里；
- 没有统一的三端部署编排、部署前预检、部署后冒烟测试与 HTTPS 反代模板；
- Q3 所需的 Cloudflare 账号 / D1 / Vectorize / 域名仍未提供，真实上线需人工凭据。

## 2. 方案总览

```
┌──────────── 部署控制机（本机） ────────────┐
│ deploy/scripts/deploy-all.sh               │
│   ├─ preflight.sh      配置 / 工具 / 占位符  │
│   ├─ deploy-edge.sh    D1 迁移 + Worker     │
│   ├─ deploy-admin.sh   构建 + Pages         │
│   ├─ deploy-vps.sh     依赖 + systemd + 健康 │
│   └─ smoke-test.sh     三端 HTTP 冒烟        │
└───────────────┬────────────────────────────┘
                │
   ┌────────────┼──────────────────────────┐
   ▼            ▼                          ▼
Cloudflare    Cloudflare Pages        本机 VPS 节点
Workers       admin 静态站点           FastAPI + Celery
api.example   admin.example            node.example
   │                                      ▲
   └────────── X-Internal-Token ──────────┘
```

域名口径（示例，实际以 Q3 为准）：

| 组件 | 域名 | HTTPS 来源 |
| --- | --- | --- |
| admin | `admin.<domain>` | Cloudflare Pages 自定义域（自动证书） |
| edge | `api.<domain>` | Workers 自定义域（自动证书） |
| vps | `node.<domain>` | Caddy 自动申请 Let's Encrypt 证书 |

## 3. 交付物

### 3.1 配置模板

- `deploy/env/deploy.env.example`：部署控制配置（Cloudflare 账号 / D1 / Pages / 域名 / VPS 地址），全部占位符；
- `deploy/templates/wrangler.production.toml.tmpl`：生产 Worker 配置（D1 / Vectorize / vars / 自定义域），由脚本渲染到 `edge/wrangler.production.toml`（gitignore）；
- `deploy/templates/Caddyfile.tmpl`：VPS 节点 HTTPS 反代模板（自动证书、安全响应头、访问日志）。

### 3.2 部署脚本

| 脚本 | 职责 | 关键约束 |
| --- | --- | --- |
| `preflight.sh` | 工具链 / 配置文件 / 占位符 / 目标可达性检查 | 只读；失败即退出，不打印密钥 |
| `render-config.sh` | 渲染 wrangler / Caddy 模板 | 输出文件权限 600；拒绝空值 |
| `deploy-edge.sh` | D1 远端迁移 + `wrangler deploy` | 先迁移后发布；发布后 `/healthz` 冒烟 |
| `deploy-admin.sh` | `npm ci` + 生产构建 + `wrangler pages deploy` | 强制 `VITE_DEMO_MODE=false` 且 `VITE_API_BASE_URL` 非空 |
| `deploy-vps.sh` | 依赖安装 + bootstrap + systemd 重启 + 健康检查 | 幂等；`--skip-deps` 支持快速重启 |
| `deploy-all.sh` | 顺序编排三端 | 任一步失败即停止，不并发起重活 |
| `smoke-test.sh` | 三端 HTTP / JSON 冒烟 | 支持 `--dry-run` / `--json`，离线可测 |

### 3.3 CI/CD

`.github/workflows/deploy.yml`：

- 触发：`workflow_dispatch` + `push` 到 `main`；
- `concurrency` 带 `github.ref` + `cancel-in-progress: true`；
- `production` environment（人工审批）；
- edge / admin 使用 `cloudflare/wrangler-action`，VPS 使用 SSH 密钥执行 `deploy-vps.sh`；
- 所有凭据来自 GitHub Secrets，不入库。

### 3.4 文档

- `docs/guides/production-deployment.md`：完整上线手册（资源准备 → 部署 → 域名 HTTPS → 冒烟 → 回滚 → 安全清单）；
- `deploy/README.md` 增加生产部署入口；
- `docs/planning/task-planning.md` / `docs/planning/roadmap.md` / `docs/requirements/open-questions.md` 同步状态与 Q3 说明。

## 4. 测试与验收

| 层 | 用例 |
| --- | --- |
| 部署资产 | `vps/tests/test_deploy_assets.py` 扩展：模板键集合、wrangler 生产配置安全、Caddy TLS、脚本 `bash -n` / `--help`、smoke `--dry-run` |
| 本机基线 | `deploy/scripts/doctor.sh --services` 全绿；`GET /healthz` 200 |
| 脚本自检 | `preflight.sh --dry-run`、`smoke-test.sh --dry-run` 在无凭据环境下可运行 |
| 三端构建 | admin `lint / build / test`；edge `typecheck`；vps `pytest` |

验收标准：

1. 一条命令完成三端部署（有凭据时），无凭据时 preflight 明确列出缺失项；
2. 部署后 smoke-test 覆盖 admin / edge / vps 健康检查；
3. 域名 / HTTPS / 密钥 / 回滚步骤在文档中可照做；
4. 所有脚本 `bash -n` 通过，模板不含真实密钥。

## 5. 风险与边界

- **Q3 未提供**：无法执行真实 Cloudflare 部署，本次交付「部署工具链 + 手册」，实际上线需填真实账号 / D1 / 域名后执行；
- **Cloudflare Pages 项目**需先创建（脚本支持 `--create-project`，首次部署时自动创建）；
- **Caddy / 证书**依赖域名解析到本机且 80/443 可达；本机已有 Apache 时需先停用或改端口，文档给出检查项；
- **VPS 重活**：`npm ci` / `pip install` 走 `bacs-heavy`（同机资源自律），脚本只负责调用，不并发。
