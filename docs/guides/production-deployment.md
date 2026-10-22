# 正式部署手册 · Production Deployment

> 文档编号：GD-04 ｜ 对应需求：REQ-202610-0939（backlog M5-01）｜ 维护人：fntp
> 适用版本：v0.1.x ｜ 更新方式：域名 / 部署形态 / 凭据口径变化时更新

本文档把 OpenFactory 从「本机可跑」推进到「可重复、可自检、可回滚的生产部署」。
部署资产在 [`deploy/`](../../deploy/README.md)，本机运行基线见
[deployment-baseline.md](./deployment-baseline.md)；升级、回滚与故障处理的完整 SOP 见
[operations-runbook.md](./operations-runbook.md)。

## 1. 部署形态

```
Cloudflare（无状态控制面）                    本机 VPS（私有数据 / AI）
├── Pages    admin 静态站点  admin.<domain>    ├── FastAPI  127.0.0.1:8000
├── Workers  edge API       api.<domain>      ├── Celery worker / beat
├── D1       元数据                           ├── Redis    127.0.0.1:6379
└── Vectorize 向量索引                        └── Caddy    node.<domain> → 8000
```

| 组件 | 部署目标 | 域名 / 入口 | HTTPS |
| --- | --- | --- | --- |
| `admin/` | Cloudflare Pages | `ADMIN_ORIGIN` | Pages 自动证书 |
| `edge/` | Cloudflare Workers | `API_ORIGIN` | Workers 自定义域自动证书 |
| `vps/` | 本机 systemd | `VPS_NODE_URL` | Caddy + Let's Encrypt |

> 三个域名都必须先托管在同一个 Cloudflare 账号下；`node.<domain>` 的 DNS 记录指向本机公网 IP
> （建议仅开放 80/443，Cloudflare 代理可开可关；Caddy 需要 80 端口做 HTTP-01 验证）。

## 2. 前置条件（Q3 清单）

| 资源 | 获取方式 | 写入位置 |
| --- | --- | --- |
| Cloudflare Account ID | 控制台右侧 / `wrangler whoami` | `deploy.env` |
| API Token | My Profile → API Tokens，权限：Workers Scripts:Edit、D1:Edit、Pages:Edit、Vectorize:Edit | `deploy.env` |
| D1 数据库 | `npx wrangler d1 create opensource-factory` | `D1_DATABASE_ID` |
| Vectorize 索引 | `npx wrangler vectorize create opensource-factory-vectors --dimensions=1024 --metric=cosine` | `VECTORIZE_INDEX_NAME` |
| Pages 项目 | 首次部署脚本自动创建，或 `wrangler pages project create` | `PAGES_PROJECT_NAME` |
| GitHub OAuth App | GitHub → Settings → Developer settings → OAuth Apps | `GITHUB_CLIENT_ID` / Secret |
| 域名 | Cloudflare → DNS | `ADMIN_ORIGIN` / `API_ORIGIN` / `VPS_NODE_URL` |
| VPS SSH | 本机 root / 部署用户 + SSH key | GitHub Secrets（CI 用） |

GitHub OAuth App 的 **Authorization callback URL** 填：

```
https://api.<domain>/api/auth/github/callback
```

## 3. 配置准备

### 3.1 部署控制配置

```bash
install -m 600 deploy/env/deploy.env.example /opt/openfactory/deploy.env
$EDITOR /opt/openfactory/deploy.env
```

必须替换全部 `REPLACE_WITH_*` 占位符。`deploy/scripts/preflight.sh` 会逐项检查。

### 3.2 应用运行配置

首次部署前先初始化运行目录（幂等）：

```bash
deploy/scripts/bootstrap-runtime.sh
```

它会生成 `/opt/openfactory/.env`（600）与随机 `INTERNAL_TOKEN`。
按实际环境修改以下键：

| 键 | 生产值 |
| --- | --- |
| `CORS_ORIGINS` | `https://admin.<domain>`（禁止 `*`） |
| `EDGE_BASE_URL` | `https://api.<domain>` |
| `VECTORIZE_INDEX_NAME` | 与 Worker 绑定一致 |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | 本机 Ollama 地址与 ≤2B 量化模型 |
| `GITHUB_TOKEN` | 可选，仅同步公开数据时使用 |

`INTERNAL_TOKEN` 由 bootstrap 生成，部署脚本会自动同步到 Worker 机密，**不要手工复制到聊天 / 日志**。

### 3.3 部署前预检

```bash
deploy/scripts/preflight.sh --env-file /opt/openfactory/deploy.env --target all
```

预检失败会列出缺失项；`--dry-run` 可在没有真实凭据时查看检查计划。

## 4. 部署步骤

### 4.1 edge（Workers + D1）

```bash
# 首次：创建 D1 与 Vectorize（只需一次）
cd edge
npx wrangler d1 create opensource-factory
npx wrangler vectorize create opensource-factory-vectors --dimensions=1024 --metric=cosine
cd ..

# 部署（渲染配置 → 写机密 → D1 迁移 → Worker 发布 → /healthz）
deploy/scripts/deploy-edge.sh --env-file /opt/openfactory/deploy.env
```

脚本行为：

1. `render-config.sh` 生成 `edge/wrangler.production.toml`（600，gitignore）；
2. `wrangler secret put` 写入 `GITHUB_CLIENT_SECRET` / `SESSION_SECRET` / `INTERNAL_TOKEN`；
3. `wrangler d1 migrations apply opensource-factory --remote` 应用 `edge/migrations/*.sql`；
4. `wrangler deploy` 发布 Worker；
5. `curl https://api.<domain>/healthz` 冒烟。

首次部署后在 Cloudflare 控制台确认 Worker 的 Custom Domain 为 `api.<domain>`，
并把 `ALLOWED_ORIGIN` 指向 `https://admin.<domain>`。

### 4.2 admin（Pages）

```bash
deploy/scripts/deploy-admin.sh --env-file /opt/openfactory/deploy.env --create-project
```

脚本会：

1. 以 `VITE_API_BASE_URL=$API_ORIGIN`、`VITE_DEMO_MODE=false` 执行 `npm ci && npm run build`；
2. `wrangler pages deploy dist --project-name ... --branch main`；
3. 冒烟 `https://admin.<domain>`。

首次部署后在 Pages 项目 → Custom domains 绑定 `admin.<domain>`，等待证书状态为 Active。

> 本地验证构建可用 `cd admin && VITE_API_BASE_URL=https://api.example.com VITE_DEMO_MODE=false npm run build`，
> 产物在 `admin/dist/`。

### 4.3 vps（本机节点 + HTTPS）

```bash
# 1) 运行目录 + systemd 单元（root）
deploy/scripts/deploy-vps.sh --env-file /opt/openfactory/deploy.env

# 2) 安装 Caddy（若未安装）
apt-get install -y caddy

# 3) 渲染并安装 HTTPS 反代
deploy/scripts/setup-https.sh --env-file /opt/openfactory/deploy.env
```

`deploy-vps.sh` 会安装 4 个单元并重启：

```bash
systemctl status openfactory-redis openfactory-api openfactory-worker openfactory-beat
journalctl -u openfactory-api -n 100 --no-pager
```

Caddy 首次启动会自动申请证书；确认：

```bash
curl -fsS https://node.<domain>/healthz
```

> 本机若已运行 Apache / Nginx 占用 80/443，先停用或改端口，否则 Caddy 无法绑定。
> 仅本机联调时可直接访问 `http://127.0.0.1:8000/healthz`，不需要 Caddy。

### 4.4 一键部署

```bash
deploy/scripts/deploy-all.sh --env-file /opt/openfactory/deploy.env
```

顺序为 edge → admin → vps → 三端冒烟；任一步失败即停止。重活（`npm ci` / `pip install` / build）
通过 `bacs-heavy` 排队，符合同机资源自律。

## 5. 验收清单

```bash
deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json
```

| 检查 | 期望 |
| --- | --- |
| `GET https://api.<domain>/healthz` | 200 `{"status":"ok"}` |
| `GET https://node.<domain>/healthz` | 200 `{"status":"ok"}` |
| `GET https://admin.<domain>/` | 200，返回 admin HTML |
| admin 登录 | GitHub OAuth 回调成功，进入控制台 |
| `deploy/scripts/doctor.sh --services` | 运行目录 / 权限 / env / Redis 全绿 |
| `systemctl is-active openfactory-*` | 4 个单元均 active |

上线后建议再用真实账号走一遍：登录 → 同步收藏 → 热榜 → 推荐 → 通知中心。

## 6. 回滚

| 组件 | 回滚方式 |
| --- | --- |
| edge | `cd edge && npx wrangler deployments list` 找到上一版本 → `npx wrangler rollback <deployment-id>` |
| admin | Cloudflare Pages → Deployments → 选择上一版本 → Rollback |
| vps | 切回上一提交 → `deploy/scripts/deploy-vps.sh --skip-deps`（运行目录数据不变） |
| 数据库 | D1 迁移不自动回滚；先在 staging 验证，必要时用 D1 导出恢复（M5-04） |

回滚后必须重跑 `smoke-test.sh`。完整回滚决策矩阵、数据库恢复步骤与回滚后验证清单见
[operations-runbook.md](./operations-runbook.md) §6。

## 7. 密钥与安全清单

- [ ] `deploy.env`、`/opt/openfactory/.env` 权限 600，运行目录 700；
- [ ] 仓库内无真实 token（`git grep -nE 'sk-|ghp_|CLOUDFLARE_API_TOKEN='` 应无命中）；
- [ ] Worker 机密只通过 `wrangler secret put` 写入，不写入 `wrangler.production.toml`；
- [ ] `CORS_ORIGINS` / `ALLOWED_ORIGIN` 为精确域名，禁止 `*`；
- [ ] Redis 只监听 `127.0.0.1`，不暴露公网；
- [ ] VPS 防火墙仅开放 22 / 80 / 443（`ufw status`）；
- [ ] GitHub OAuth App 仅授权必要 scope；
- [ ] 定期轮换 `INTERNAL_TOKEN`（同步更新 Worker 与 VPS 后重启）。

## 8. 常见问题

| 现象 | 排查 |
| --- | --- |
| `wrangler deploy` 报 D1 database_id 无效 | `deploy.env` 的 `D1_DATABASE_ID` 是否为真实 id；是否执行过 `wrangler d1 create` |
| Worker `/healthz` 502 | 自定义域是否绑定；`wrangler deployments list` 是否成功 |
| admin 打开是演示模式 | 构建时 `VITE_API_BASE_URL` 为空或 `VITE_DEMO_MODE=true`；重新执行 deploy-admin |
| 登录 501 | Worker `GITHUB_CLIENT_ID` / Secret 未配置 |
| CORS 报错 | `ALLOWED_ORIGIN` 与 admin 实际域名不一致（含协议 / 端口） |
| Caddy 证书失败 | 域名未解析到本机、80 端口被占用、Cloudflare 代理开启但源站 80 不可达 |
| VPS 任务不执行 | `systemctl status openfactory-worker`；Redis 是否 active；`.env` 的 `REDIS_URL` |

完整的故障分级、排查步骤与复盘模板见 [operations-runbook.md](./operations-runbook.md) §7；
现场信息采集使用 `deploy/scripts/ops-diagnose.sh --env-file /opt/openfactory/deploy.env`。

## 9. 当前执行状态（2026-10-22）

- ✅ 部署工具链、模板、CI 工作流与本文档已就绪；
- ✅ 本机运行基线已验证（`doctor.sh --services`、`GET /healthz` 200）；
- ⏳ **真实 Cloudflare 部署待 Q3 凭据**：账号 ID、API Token、D1 `database_id`、
  Vectorize 索引、域名与 GitHub OAuth App 信息；
- ⏳ 本机 `worker` / `beat` 已纳入 `deploy-vps.sh` 启停流程，首次生产部署时一并启用。
