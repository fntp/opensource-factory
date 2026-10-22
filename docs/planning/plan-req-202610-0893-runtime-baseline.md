# 实施计划 · REQ-202610-0893 本机运行环境与部署基线

> 对应需求：REQ-202610-0893（backlog M1-01 / IT-0003）｜ 分支：`feat/req-202610-0893-runtime-baseline`｜ 日期：2026-10-22｜ 状态：已完成

## 1. 目标

把「本机运行」从口头约定变成可复现、可自检的基线：

1. **运行目录**：`/opt/openfactory` 固定布局（配置 / 数据 / 日志 / 备份 / 运行态），私有权限；
2. **Redis**：本机 broker / 缓存基线配置（仅回环监听、256MB 上限、不落盘）；
3. **进程管理**：systemd 单元（api / worker / beat / redis），统一环境文件与资源上限；
4. **环境模板对齐**：`vps/.env.example`、生产模板、`app.config.Settings` 三者字段一致，并有自动化测试兜底；
5. **自检**：`python -m app.runtime check` + `deploy/scripts/doctor.sh`，一条命令验证基线。

## 2. 现状与约束

- 仓库三端骨架已就绪，但没有任何部署资产；`vps/.env.example` 与 `config.py` 字段大体一致，缺少运行目录 / 日志目录约定；
- 资源预算：应用侧 ≤ 2G（api + worker + beat + redis），见 `docs/planning/resource-plan.md` §2；
- 本机为 Ubuntu + systemd，Redis 未安装（脚本给出安装入口，不强制在线安装）；
- 私有配置只放 `/opt/openfactory/.env`（600），仓库只提交模板（占位符）。

## 3. 方案

### 3.1 运行目录布局

```
/opt/openfactory/            700  root:openfactory（或 openfactory:openfactory）
├── .env                     600  真实配置（模板渲染，不进仓库）
├── etc/redis.conf           600  Redis 配置（模板渲染）
├── data/                    700  SQLite / Celery beat schedule
│   └── redis/               700  Redis 工作目录
├── logs/                    700  应用日志（滚动保留）
├── backups/                 700  备份产物
└── run/                     700  运行态文件
```

代码目录与运行目录分离：代码留在检出目录（如 `/opt/workspace/opensource-factory`），
systemd 单元通过 `@APP_DIR@` 占位符在安装时渲染。

### 3.2 Redis 基线

- 仅监听 `127.0.0.1` / `::1`，`protected-mode yes`；
- `maxmemory 256mb` + `maxmemory-policy noeviction`（Celery broker 不丢任务）；
- 关闭 RDB / AOF（队列数据可重建，避免磁盘占用与 fork 抖动）；
- systemd 托管，`MemoryMax=320M`。

### 3.3 进程管理

| 单元 | 进程 | 资源上限 |
| --- | --- | --- |
| `openfactory-api.service` | uvicorn 单 worker，127.0.0.1:8000 | 384M |
| `openfactory-worker.service` | celery worker，并发 2 | 768M |
| `openfactory-beat.service` | celery beat（schedule 落 data/） | 192M |
| `openfactory-redis.service` | redis-server | 320M |

统一：`EnvironmentFile=/opt/openfactory/.env`、`Restart=on-failure`、`NoNewPrivileges`、
`ProtectSystem=full`、`ReadWritePaths=/opt/openfactory`。

### 3.4 环境模板对齐

- `vps/.env.example` 补齐 `APP_NAME` / `VERSION` / `LOG_DIR`；
- 新增 `deploy/env/openfactory.env.example`：绝对路径、回环地址、生产占位值；
- 新增 `LOG_DIR` 配置项：非空时 API 写滚动日志到运行目录（默认空 = 仅 stdout）；
- `tests/test_deploy_assets.py` 校验「Settings 字段 = 两份模板键集合」，防止后续漂移。

### 3.5 自检

`vps/app/runtime.py`（仅标准库）提供 `layout` / `check` 子命令：
目录存在、运行目录 700、`.env` 600、必填键齐全、无占位符、data 可写，`--services` 时探测 Redis。

## 4. 文件清单

| 文件 | 说明 |
| --- | --- |
| `deploy/README.md` | 部署基线说明与命令 |
| `deploy/env/openfactory.env.example` | 生产环境模板 |
| `deploy/redis/redis.conf` | Redis 基线配置（占位符） |
| `deploy/systemd/openfactory-*.service` | 四个 systemd 单元模板 |
| `deploy/scripts/bootstrap-runtime.sh` | 创建运行目录、渲染配置、可选安装单元 |
| `deploy/scripts/doctor.sh` | 基线自检入口 |
| `vps/app/runtime.py` | 运行目录自检模块（stdlib） |
| `vps/tests/test_runtime.py` | 自检模块单测 |
| `vps/tests/test_deploy_assets.py` | 模板 / 单元 / 脚本一致性测试 |
| `docs/guides/deployment-baseline.md` | 部署基线 SOP |
| 文档同步 | `docs/README.md`、`AGENTS.md`、`vps/README.md`、`resource-plan.md`、`task-planning.md`、`dev-cycle.md` |

## 5. 验收标准

1. 全新机器执行 `deploy/scripts/bootstrap-runtime.sh` 后，`/opt/openfactory` 布局与权限符合 §3.1；
2. `deploy/scripts/doctor.sh` 全绿（服务未启动时 Redis 检查为可选）；
3. `vps/.venv/bin/pytest -q` 全绿，新增测试覆盖模板漂移与自检逻辑；
4. `bash -n` 校验全部 shell 脚本；systemd 单元可被 `systemd-analyze verify` 解析（无 Redis 二进制时允许警告）；
5. 文档同步完成，无密钥入库。

## 6. 风险与人工事项

- 本机尚未安装 `redis-server`：`bootstrap-runtime.sh --with-redis` 提供 apt 安装入口，执行需联网与 root；
- Ollama 与模型下载不在本需求范围（M3-01 选型），单元只预留服务依赖；
- 真实 `INTERNAL_TOKEN` 由脚本随机生成并只写入本机 `.env`，不入库；
- 生产域名 / Cloudflare 配置属于 M1-02 / M5 范围。
