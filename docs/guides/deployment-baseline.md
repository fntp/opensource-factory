# 本机运行环境与部署基线 · Deployment Baseline

> 文档编号：GD-03 ｜ 对应需求：REQ-202610-0893（backlog M1-01 / IT-0003）｜ 维护人：fntp ｜ 更新方式：运行目录 / 进程 / 端口变化时更新

本文档定义 OpenFactory 在本机（VPS）运行的最小基线：**运行目录、Redis、进程管理、环境模板**。
部署资产全部位于仓库 [`deploy/`](../../deploy/README.md)，文档与脚本以「可重复执行、可自检」为准。

> 三端正式上线（Cloudflare Pages / Workers + 本机节点 + 域名 HTTPS）见
> [production-deployment.md](./production-deployment.md)；本文档只覆盖本机运行基线。

## 1. 目标与边界

- **目标**：任意一台干净的 Ubuntu 机器，按本文档执行后得到一致的运行环境；
- **不在本需求范围**：Ollama 模型选型与下载（M3-01）、D1 / Cloudflare 配置（M1-02）、
  GitHub OAuth App（M1-03）、域名与 HTTPS（M5）；
- **部署形态**：按 [Q9](../requirements/open-questions.md) 默认选项 A（混合架构），
  本机承载全部 AI / 数据 / 私有配置，Cloudflare 仅做无状态控制面。

## 2. 运行目录

运行目录与代码目录**分离**：代码可以放在任意检出目录（如 `/opt/workspace/opensource-factory`），
运行目录固定为 `/opt/openfactory`（可用 `OPENFACTORY_HOME` 覆盖）。

```
/opt/openfactory/            700   root:openfactory
├── .env                     600   真实配置（bootstrap 渲染）
├── etc/redis.conf           600   Redis 配置（bootstrap 渲染）
├── data/                    700   SQLite / Celery beat schedule
│   └── redis/               700   Redis 工作目录
├── logs/                    700   API 滚动日志（10MB × 5）
├── backups/                 700   备份产物
└── run/                     700   运行态文件（redis.pid 等）
```

约定：

- 运行目录及子目录 700，`.env` / `redis.conf` 600；
- 真实密钥只存在于 `/opt/openfactory/.env`，仓库只提交模板；
- 日志默认进 journald；设置 `LOG_DIR` 后 API 额外写 `logs/vps-api.log`。

## 3. Redis 基线

配置文件：[`deploy/redis/redis.conf`](../../deploy/redis/redis.conf)（bootstrap 渲染到 `etc/redis.conf`）。

| 配置项 | 值 | 理由 |
| --- | --- | --- |
| `bind` | `127.0.0.1 ::1` | 仅本机访问，不暴露公网 |
| `protected-mode` | `yes` | 兜底防护 |
| `maxmemory` | `256mb` | 资源规划 §2 的 Redis 预算 |
| `maxmemory-policy` | `noeviction` | Celery broker 不静默丢任务 |
| `save` / `appendonly` | 关闭 | 队列数据可重建，节省磁盘与 fork 抖动 |
| 托管方式 | systemd `Type=notify` | 与 `supervised systemd` 配合 |

> 若本机尚未安装 Redis，执行 `deploy/scripts/bootstrap-runtime.sh --with-redis`
> （apt 安装并停用发行版默认 `redis.service`，避免 6379 端口冲突）。

## 4. 进程管理（systemd）

单元模板位于 [`deploy/systemd/`](../../deploy/systemd/)，由 bootstrap 渲染
`@APP_DIR@` / `@RUNTIME_DIR@` / `@SERVICE_USER@` 后安装到 `/etc/systemd/system/`。

| 单元 | ExecStart 摘要 | 资源上限 | 说明 |
| --- | --- | --- | --- |
| `openfactory-redis.service` | `redis-server etc/redis.conf` | 320M | broker / 结果后端 |
| `openfactory-api.service` | `uvicorn app.main:app`（1 worker） | 384M | 仅监听 127.0.0.1:8000 |
| `openfactory-worker.service` | `celery worker --concurrency=2` | 768M | AI 任务队列内串行 |
| `openfactory-beat.service` | `celery beat` | 192M | 定时抓取 / 每日推送 |

统一约束：`Restart=on-failure`、`NoNewPrivileges=true`、`PrivateTmp=true`、
`ProtectSystem=full`、`ProtectHome=true`、`ReadWritePaths=/opt/openfactory`，
以专用系统用户 `openfactory` 运行。

启用：

```bash
systemctl enable --now openfactory-redis openfactory-api openfactory-worker openfactory-beat
systemctl status openfactory-api
journalctl -u openfactory-worker -f
```

## 5. 环境模板对齐

三处必须保持一致（`vps/tests/test_deploy_assets.py` 自动校验）：

1. `vps/app/config.py` 的 `Settings` 字段；
2. `vps/.env.example`（开发 / 本地）；
3. `deploy/env/openfactory.env.example`（生产 / 本机，绝对路径）。

生产模板关键差异：

| 变量 | 开发模板 | 生产模板 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./data/...` | `sqlite:////opt/openfactory/data/...` |
| `LOG_DIR` | 空（仅 stdout） | `/opt/openfactory/logs` |
| `REDIS_URL` / `OLLAMA_BASE_URL` | `localhost` | `127.0.0.1`（避免 IPv6 解析歧义） |
| `CORS_ORIGINS` | `*` | 实际管理后台域名（禁止 `*`） |
| `INTERNAL_TOKEN` | 空（本地不鉴权） | bootstrap 自动生成 64 位十六进制 |

## 6. 首次部署步骤

```bash
# 0) 代码检出（示例）
git clone <repo> /opt/workspace/opensource-factory && cd /opt/workspace/opensource-factory

# 1) 运行目录 + 配置（幂等）
deploy/scripts/bootstrap-runtime.sh

# 2) Python 依赖
cd vps && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3) 单元安装（需 root）
deploy/scripts/bootstrap-runtime.sh --install-units
systemctl enable --now openfactory-redis openfactory-api openfactory-worker openfactory-beat

# 4) 自检
deploy/scripts/doctor.sh --services
```

## 7. 自检与验收

```bash
deploy/scripts/doctor.sh --services
```

检查项：

| 检查 | 通过条件 |
| --- | --- |
| `home` / `home_permissions` | 运行目录存在且权限 ≤ 700 |
| `layout` | `etc/data/data/redis/logs/backups/run` 齐全 |
| `env_file` / `env_permissions` | `.env` 存在且权限 ≤ 600 |
| `env_keys` | 与 `Settings` 字段一致，无缺失 |
| `env_placeholders` | 无 `CHANGE_ME` / `REPLACE_WITH` / `<your` 残留 |
| `internal_token` | 长度 ≥ 16（bootstrap 生成 64 位） |
| `model_budget` | 已登记的模型峰值驻留 ≤ `MODEL_BUDGET_MB`（未识别模型跳过） |
| `data_writable` | `data/` 可写 |
| `redis`（`--services`） | `REDIS_URL` 的 host:port 可连接 |

模型预算可单独复核（`--probe` 会读取本机 Ollama `/api/ps`）：

```bash
cd vps && .venv/bin/python -m app.model_budget check --probe
```

验收记录（2026-10-22，本机）：

- 运行目录 `/opt/openfactory` 已创建，权限 700；`.env` / `redis.conf` 600；
- `python -m app.runtime check --services` 全绿；`pytest` 新增用例通过；
- Redis 已安装并启用 `openfactory-redis`（`PONG`，`maxmemory 256MB`）；
- `openfactory-api` 已启用，`GET /healthz` 返回 200；
- `openfactory-worker` / `openfactory-beat` 已安装但未启用（等待 M1-05 同步链路与模型就绪）。

## 8. 运维要点

- **升级**：`git pull` → `pip install -r requirements.txt` → `systemctl restart openfactory-api openfactory-worker openfactory-beat`；
- **回滚**：切回上一提交 → 重装依赖 → 重启单元；运行目录数据不受影响；
- **日志**：`journalctl -u openfactory-*`；`LOG_DIR` 文件日志按 10MB × 5 滚动；
- **磁盘**：`data/`、`logs/`、`backups/` 均受 15G 总预算约束，备份保留策略见 M5；
- **密钥轮换**：修改 `/opt/openfactory/.env` 的 `INTERNAL_TOKEN` 后，同步更新边缘侧
  `wrangler secret put INTERNAL_TOKEN` 并重启 API / worker。

## 9. 已知人工事项

| 事项 | 说明 |
| --- | --- |
| 安装 Redis | ✅ 2026-10-22 已通过 `bootstrap-runtime.sh --with-redis` 安装并启用 |
| 启用服务 | `openfactory-api` / `openfactory-redis` 已启用；worker / beat 待 M1-05 后启用 |
| Ollama / 模型 | M3-01 已选型（bge-m3 int8 + `qwen2.5:1.5b-instruct-q4_K_M`）；本基线预留地址与端口，模型需另行 `ollama pull` |
| 生产域名 | 属 M1-02 / M5，`CORS_ORIGINS` 先保留 localhost 占位 |
