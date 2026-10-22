# 部署基线（`deploy/`）

> 对应需求：REQ-202610-0893（backlog M1-01 / IT-0003）、REQ-202610-0939（backlog M5-01）、REQ-202610-0940（M5-02）、REQ-202610-0945（backlog M5-07）｜ 维护人：fntp

本目录把「本机运行」固化为可复现的基线：运行目录、Redis、systemd 进程管理与环境模板。
完整说明见 [docs/guides/deployment-baseline.md](../docs/guides/deployment-baseline.md)；
三端正式部署（Pages / Workers / 本机节点 / 域名 HTTPS）见
[docs/guides/production-deployment.md](../docs/guides/production-deployment.md)；
部署 / 升级 / 回滚 / 故障处理统一 SOP 见
[docs/guides/operations-runbook.md](../docs/guides/operations-runbook.md)。

## 1. 运行目录

```
/opt/openfactory/            700  运行根目录（仅本机，不进仓库）
├── .env                     600  真实配置（bootstrap 从模板渲染）
├── etc/redis.conf           600  Redis 配置（bootstrap 渲染）
├── data/                    700  SQLite / Celery beat schedule
│   └── redis/               700  Redis 工作目录
├── logs/                    700  应用滚动日志
├── backups/                 700  备份产物（sqlite/ + d1/）
└── run/                     700  运行态文件
```

代码与运行目录分离：systemd 单元里的 `@APP_DIR@` 在安装时指向当前检出目录。

## 2. 首次部署

```bash
# 1) 创建运行目录 / 渲染 .env 与 redis.conf（幂等，可重复执行）
deploy/scripts/bootstrap-runtime.sh

# 2) 安装 Python 依赖（vps）
cd vps && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3) 安装并启用 systemd 单元（需 root）
deploy/scripts/bootstrap-runtime.sh --install-units
systemctl enable --now openfactory-redis openfactory-api openfactory-worker openfactory-beat

# 4) 自检
deploy/scripts/doctor.sh --services
```

> `bootstrap-runtime.sh --with-redis` 可在缺少 `redis-server` 时用 apt 安装，
> 并停用发行版默认的 `redis.service`（由 `openfactory-redis.service` 接管 6379）。

## 3. 进程与资源上限

| 单元 | 进程 | 监听 / 产物 | MemoryMax |
| --- | --- | --- | --- |
| `openfactory-redis.service` | redis-server | `127.0.0.1:6379` | 320M |
| `openfactory-api.service` | uvicorn（单 worker） | `127.0.0.1:8000` | 384M |
| `openfactory-worker.service` | celery worker（并发 2） | — | 768M |
| `openfactory-beat.service` | celery beat | `data/celerybeat-schedule` | 192M |

合计上限约 1.66G，落在应用侧 2G 预算内（见 [resource-plan.md](../docs/planning/resource-plan.md) §2）。
部署后用 `deploy/scripts/resource-budget.sh` 实测；2026-10-22 基线见
[resource-budget-verification.md](../docs/guides/resource-budget-verification.md)。

## 4. 环境模板对齐

| 文件 | 用途 | 是否入库 |
| --- | --- | --- |
| `vps/.env.example` | 开发 / 本地模板（相对路径） | ✅ |
| `deploy/env/openfactory.env.example` | 生产 / 本机模板（绝对路径、回环地址） | ✅ |
| `/opt/openfactory/.env` | 真实配置（bootstrap 渲染，`INTERNAL_TOKEN` 自动生成） | ❌ |

两份模板的键集合必须与 `vps/app/config.py` 的 `Settings` 字段一致，
由 `vps/tests/test_deploy_assets.py` 自动校验，新增配置项时同步三处。

监控（M5-03）相关键已同步到两份模板：`MONITOR_*` 共 17 项，其中
`MONITOR_HOME=@RUNTIME_DIR@` 指向运行目录，内存 / 磁盘红线默认 4G / 15G。
生产环境可只改 `MONITOR_ALERT_WEBHOOK_URL` 与阈值，无需改代码。

## 5. 常用命令

```bash
deploy/scripts/bootstrap-runtime.sh --help
deploy/scripts/doctor.sh                 # 目录 / 权限 / 环境文件自检
deploy/scripts/doctor.sh --services      # 额外探测 Redis
deploy/scripts/resource-budget.sh        # 4G / 15G 资源预算实测（M5-06）
deploy/scripts/resource-budget.sh --json # JSON 输出，供监控 / 验收脚本消费
deploy/scripts/ops-diagnose.sh           # 现场诊断包（版本 / 单元 / 日志 / 健康检查，只读）
python3 -m app.runtime layout --home /opt/openfactory   # 在 vps/ 下执行
journalctl -u openfactory-api -f         # 查看进程日志
```

## 6. 正式部署（M5-01）

| 脚本 | 说明 |
| --- | --- |
| `preflight.sh` | 部署前检查工具链 / 配置键 / 占位符 / HTTPS / 内部令牌 |
| `render-config.sh` | 渲染 `edge/wrangler.production.toml` 与 Caddyfile（600） |
| `deploy-edge.sh` | D1 远端迁移 + Worker 机密 + `wrangler deploy` + 冒烟 |
| `deploy-admin.sh` | 生产构建（演示模式关闭）+ Cloudflare Pages 发布 |
| `deploy-vps.sh` | 运行目录 / systemd 单元 / 依赖 / 重启 / 健康检查 |
| `deploy-all.sh` | 三端顺序编排（edge → admin → vps → 冒烟） |
| `smoke-test.sh` | 三端 HTTP 冒烟（支持 `--json` / `--dry-run`） |
| `setup-https.sh` | 渲染并安装 Caddy HTTPS 反代 |
| `backup-d1.sh` | `wrangler d1 export` + 校验 + gzip + 清单归档（M5-04） |
| `backup-all.sh` | SQLite 快照 + D1 导出 + 恢复演练汇总入口（cron） |
| `backup-drill.sh` | 最新 SQLite 快照 / D1 导出恢复演练 |
| `restore-sqlite.sh` | 受保护的 SQLite 恢复（默认拒绝覆盖，可停 / 起 systemd） |
| `security-audit.sh` | 只读安全审计（密钥 / 依赖 / 配置 / 响应头 / 隐私），`--online` / `--strict` 可选（M5-08） |

部署控制配置模板：`deploy/env/deploy.env.example`（复制到 `/opt/openfactory/deploy.env`，600）。
首次使用前务必阅读 [正式部署手册](../docs/guides/production-deployment.md) 的 Q3 资源清单。

```bash
deploy/scripts/preflight.sh --env-file /opt/openfactory/deploy.env --target all
deploy/scripts/deploy-all.sh --env-file /opt/openfactory/deploy.env
deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json
```

## 7. 备份与恢复（M5-04）

```bash
deploy/scripts/backup-all.sh --env-file /opt/openfactory/deploy.env   # SQLite + D1 + 演练
deploy/scripts/backup-drill.sh --env-file /opt/openfactory/deploy.env # 只演练
deploy/scripts/restore-sqlite.sh --name <snapshot> --target <db> --force --stop-services
```

产物在 `$OPENFACTORY_HOME/backups/{sqlite,d1}/`，每份带 `.json` 清单；默认保留 7 份、
总量 3 GB。完整 SOP（含 D1 恢复）见 [backup-restore.md](../docs/guides/backup-restore.md)。

## 8. 安全红线

- `.env`、`redis.conf` 权限 600，运行目录 700；真实密钥不入库、不回显；
- Redis 仅监听回环地址，禁止暴露公网；
- `CORS_ORIGINS` 生产环境禁止使用 `*`；
- 单元默认以专用系统用户 `openfactory` 运行，启用 `NoNewPrivileges` / `ProtectSystem=full`。

## 9. 本机一体化模式（可选）

`local-allinone.sh` 提供离线自托管开关：开启后 `openfactory-api` 同进程托管 admin 构建产物
与 `/local/api/*` 只读接口，不依赖 Cloudflare；默认关闭，混合架构不受影响。

```bash
deploy/scripts/local-allinone.sh build    # 构建 admin（VITE_API_BASE_URL=/local）并复制到运行目录
sudo deploy/scripts/local-allinone.sh enable
deploy/scripts/local-allinone.sh status
deploy/scripts/local-allinone.sh verify   # 离线冒烟
sudo deploy/scripts/local-allinone.sh disable  # 回滚到混合架构
```

配置项：`LOCAL_MODE` / `LOCAL_USER_ID` / `LOCAL_USER_LOGIN` / `LOCAL_USER_NAME` /
`LOCAL_ADMIN_DIR`。安全边界、资源占用与验收清单见
[docs/guides/local-allinone-deployment.md](../docs/guides/local-allinone-deployment.md)。

## 10. 运维手册（M5-07）

- 统一 SOP：[docs/guides/operations-runbook.md](../docs/guides/operations-runbook.md)
  （日常巡检 / 部署 / 升级 / 回滚 / 故障处理 / 备份恢复 / 密钥轮换）；
- 现场诊断：`deploy/scripts/ops-diagnose.sh --env-file /opt/openfactory/deploy.env`
  生成只读诊断包（版本、systemd、日志尾部、健康检查、资源预算），输出目录 700、文件 600；
- 发布前检查单与回滚决策矩阵见手册 §4–§7；故障分级与复盘模板见 §7.1 / §7.6。
