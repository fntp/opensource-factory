# 运维手册（部署 / 升级 / 回滚 / 故障处理 SOP） · Operations Runbook

> 文档编号：GD-06 ｜ 对应需求：REQ-202610-0945（backlog M5-07）｜ 依赖：M5-01 正式部署
> 维护人：fntp ｜ 适用版本：v0.1.x ｜ 更新方式：部署形态 / 脚本 / 阈值 / 凭据口径变化时更新

本文档是 OpenFactory 生产环境的**统一运维入口**。它把 [部署基线](./deployment-baseline.md)、
[正式部署手册](./production-deployment.md)、[资源预算实测](./resource-budget-verification.md)
中的操作收敛为可执行的 SOP：日常巡检、部署、升级、回滚、故障处理、备份恢复、密钥轮换。

> 原则：**先止血、后定位；不可逆操作先备份；所有生产变更留痕；一人操作、一人复核（破坏性操作）。**
> 文档与脚本冲突时，以仓库实际脚本和 `--help` 输出为准，并回改本文档。

## 0. 适用范围与文档矩阵

| 场景 | 本文档章节 | 配套文档 / 脚本 |
| --- | --- | --- |
| 首次部署 / 日常发布 | §4 部署 SOP | [production-deployment.md](./production-deployment.md)、`deploy/scripts/deploy-all.sh` |
| 版本升级 | §5 升级 SOP | `deploy/scripts/preflight.sh`、`deploy/scripts/deploy-all.sh` |
| 发布失败 / 线上故障回退 | §6 回滚 SOP | `deploy/scripts/smoke-test.sh`、`wrangler rollback` |
| 线上告警 / 故障定位 | §7 故障处理 SOP | `deploy/scripts/ops-diagnose.sh`、`journalctl` |
| 数据备份 / 恢复演练 | §8 备份与恢复 SOP | `sqlite3 .backup`、`wrangler d1 export` |
| 密钥轮换 / 泄漏处置 | §9 安全与密钥 SOP | `deploy/scripts/deploy-edge.sh`、`wrangler secret put` |
| 资源红线 / 容量评估 | §10 监控与告警 | `deploy/scripts/resource-budget.sh` |
| 日常巡检 | §3 日常巡检 | `deploy/scripts/doctor.sh`、`smoke-test.sh` |

**适用边界**：当前为「Cloudflare 无状态控制面 + 单台本机 VPS」的混合架构，不覆盖多节点、
多区域、Kubernetes 或托管数据库；扩容 / 多实例化后必须补充对应章节并重新评审本文档。

## 1. 系统全景

### 1.1 组件与入口

```
Cloudflare（无状态控制面）                     本机 VPS（私有数据 / AI）
├── Pages    admin 静态站点  admin.<domain>     ├── Caddy    node.<domain> → 127.0.0.1:8000
├── Workers  edge API       api.<domain>        ├── FastAPI  127.0.0.1:8000
├── D1       元数据                             ├── Celery worker / beat
└── Vectorize 向量索引                          └── Redis    127.0.0.1:6379
```

| 组件 | 运行位置 | 入口 / 监听 | 健康检查 | 数据 |
| --- | --- | --- | --- | --- |
| admin | Cloudflare Pages | `https://admin.<domain>` | 首页返回 HTML | 无状态（构建产物） |
| edge | Cloudflare Workers | `https://api.<domain>` | `GET /healthz` → `{"status":"ok"}` | D1、Vectorize |
| vps-api | 本机 systemd | `127.0.0.1:8000`（Caddy 暴露 `node.<domain>`） | `GET /healthz` → `{"status":"ok"}` | SQLite、日志 |
| vps-worker | 本机 systemd | 无端口 | `systemctl is-active` | 队列消费、SQLite 写入 |
| vps-beat | 本机 systemd | 无端口 | `systemctl is-active` | `celerybeat-schedule` |
| redis | 本机 systemd | `127.0.0.1:6379` | `redis-cli ping` → `PONG` | 队列（可重建） |
| Caddy | 本机 systemd | `:80` / `:443` | `curl https://node.<domain>/healthz` | 证书 |

### 1.2 目录与数据

| 路径 | 内容 | 权限 | 备份 |
| --- | --- | --- | --- |
| `/opt/openfactory/.env` | 真实运行配置（含 `INTERNAL_TOKEN`） | 600 | 单独加密备份，不入普通备份包 |
| `/opt/openfactory/data/opensource_factory.db` | VPS SQLite 主库 | 600 | 每日快照 |
| `/opt/openfactory/data/celerybeat-schedule` | beat 调度状态 | 600 | 可选 |
| `/opt/openfactory/logs/` | API 滚动日志（10MB × 5） | 700 | 不需要 |
| `/opt/openfactory/backups/` | 备份产物（受 3GB 预算约束） | 700 | 异地转存 |
| `/opt/openfactory/etc/redis.conf` | Redis 配置 | 600 | 随配置备份 |
| 代码检出目录 | git 工作区（示例 `/opt/workspace/opensource-factory`） | — | git 远端 |

> **代码目录与运行目录分离**。生产发布使用独立检出目录，不要与开发 worktree、其他任务共用；
> 共享检出会被切分支 / 未提交修改污染，是发布事故的常见根因。

### 1.3 版本标识

每次发布必须记录以下四项，写入变更单：

| 项 | 获取方式 |
| --- | --- |
| 代码版本 | `git -C <部署检出目录> rev-parse --short HEAD` |
| Worker 版本 | `cd edge && npx wrangler deployments list --config wrangler.production.toml` |
| Pages 版本 | Cloudflare Pages → 项目 → Deployments（记录 deployment id / commit） |
| VPS 单元状态 | `systemctl is-active openfactory-redis openfactory-api openfactory-worker openfactory-beat` |

## 2. 角色、值班与变更纪律

### 2.1 角色

| 角色 | 职责 | 当前承担人 |
| --- | --- | --- |
| 变更发起人 | 提交变更单、准备回滚点、执行发布 | 维护者 |
| 复核人 | 核对变更单 / 备份 / 回滚命令，破坏性操作时在场 | 维护者（单人时采用「先写后执行」自检） |
| 值班 | 接收告警、按 §7 分级处理、升级上报 | 维护者 |
| 决策人 | 批准紧急变更 / 回滚 / 数据恢复 | 维护者 |

> 单人维护时，用「变更单 + 命令预演（`--dry-run`）+ 回滚点确认」替代双人复核；
> 涉及数据恢复、D1 导入、删除备份等不可逆操作，必须先在临时库演练并保留原始备份。

### 2.2 变更分级

| 级别 | 示例 | 审批 | 窗口 | 回滚要求 |
| --- | --- | --- | --- | --- |
| 标准变更 | 文档、前端文案、无 schema 变更的小版本 | 维护者 | 任意 | 记录上一版本 |
| 常规变更 | 代码发布、配置调整、依赖升级 | 维护者 | 低峰期（建议 22:00–次日 02:00） | 备份 + 上一版本 |
| 紧急变更 | P0/P1 故障止血、安全漏洞修复 | 维护者 | 立即 | 先止血，事后补单 |
| 重大变更 | D1 迁移、数据模型调整、域名 / 证书切换 | 维护者 + 演练 | 维护窗口 | 完整备份 + 恢复演练 |

**变更冻结期**：重大节假日、无值班时段、已知上游故障期间不进行非紧急发布。

### 2.3 变更单模板

```text
变更编号：CHG-YYYYMMDD-NN
需求 / 工单：REQ-xxxx / issue 链接
变更级别：标准 / 常规 / 紧急 / 重大
变更内容：一句话说明改什么
影响范围：edge / admin / vps / 数据 / 用户可见性
变更窗口：开始时间 - 结束时间
操作人 / 复核人：
回滚点：代码 commit / Worker deployment id / Pages deployment id / 备份文件
验证步骤：smoke-test + 关键业务链路
结果：成功 / 回滚 / 失败（附原因）
遗留事项：
```

## 3. 日常巡检 SOP

### 3.1 每日巡检（5–10 分钟）

| # | 检查 | 命令 | 期望 |
| --- | --- | --- | --- |
| 1 | 三端冒烟 | `deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json` | `ok:true`，三项 PASS |
| 2 | 运行目录 / 配置自检 | `deploy/scripts/doctor.sh --services` | 全部 `ok` |
| 3 | systemd 单元 | `systemctl is-active openfactory-redis openfactory-api openfactory-worker openfactory-beat` | 4 个 `active` |
| 4 | API 健康 | `curl -fsS http://127.0.0.1:8000/healthz` | `{"status":"ok"}` |
| 5 | 错误日志 | `journalctl -u openfactory-api -u openfactory-worker --since "24 hours ago" -p err --no-pager` | 无持续重复错误 |
| 6 | 资源 | `free -m`、`df -h /opt/openfactory` | 可用内存 ≥ 2G，磁盘使用 < 13G |
| 7 | 资源预算 | `deploy/scripts/resource-budget.sh --json` | `PASS` 或已知 `WARN` |

### 3.2 每周巡检

| # | 检查 | 命令 / 动作 | 期望 |
| --- | --- | --- | --- |
| 1 | 资源趋势 | `deploy/scripts/resource-budget.sh` 并记录内存 / 磁盘分项 | 无持续上涨 |
| 2 | 备份完整性 | `ls -lh /opt/openfactory/backups/`，抽检最新 SQLite / D1 备份 | 文件存在、大小合理、可读 |
| 3 | D1 迁移状态 | `cd edge && npx wrangler d1 migrations list <db> --remote --config wrangler.production.toml` | 无 pending 迁移 |
| 4 | Worker 部署 | `cd edge && npx wrangler deployments list --config wrangler.production.toml` | 当前版本符合变更单 |
| 5 | 证书 | `curl -vI https://node.<domain> 2>&1 \| grep -i expire` 或 Caddy 日志 | 证书 > 30 天到期 |
| 6 | 日志磁盘 | `journalctl --disk-usage`、`du -sh /opt/openfactory/logs` | 未逼近配额 |
| 7 | 依赖安全 | `cd admin && npm audit --omit=dev`；`cd edge && npm audit --omit=dev` | 无 high / critical（有则登记） |

### 3.3 每月巡检

| # | 检查 | 动作 |
| --- | --- | --- |
| 1 | 恢复演练 | 按 §8.6 在临时目录恢复最新 SQLite / D1 备份并校验 |
| 2 | 密钥盘点 | 按 §9.1 核对密钥清单、最后轮换时间 |
| 3 | 容量评估 | 对照 [resource-plan.md](../planning/resource-plan.md) 复核内存 / 磁盘分项 |
| 4 | 依赖升级评估 | 汇总 `npm outdated` / `pip list --outdated`，按项目规范单独提交 |
| 5 | 文档复核 | 检查本文档命令、链接、阈值是否与脚本一致 |
| 6 | 备份清理 | 按保留策略清理过期备份，确认剩余空间 ≥ 3G |

### 3.4 巡检记录模板

```text
日期：YYYY-MM-DD HH:MM
巡检人：
smoke-test：PASS / FAIL（附输出）
doctor：PASS / FAIL
单元：redis=active api=active worker=active beat=active
内存可用：____ MB；磁盘使用：____ GB / 15 GB
异常日志：
处理动作：
遗留：
```

## 4. 部署 SOP

### 4.1 首次部署

前置条件见 [production-deployment.md](./production-deployment.md) §2（Q3 清单）：
Cloudflare Account ID / API Token、D1 database_id、Vectorize 索引、Pages 项目、域名、
GitHub OAuth App、VPS SSH。

```bash
# 1) 准备部署控制配置（600）
install -m 600 deploy/env/deploy.env.example /opt/openfactory/deploy.env
$EDITOR /opt/openfactory/deploy.env

# 2) 初始化运行目录（幂等；生成 INTERNAL_TOKEN）
deploy/scripts/bootstrap-runtime.sh

# 3) 预检（占位符 / 工具链 / 配置键 / HTTPS / 令牌）
deploy/scripts/preflight.sh --env-file /opt/openfactory/deploy.env --target all

# 4) 三端部署（edge → admin → vps → 冒烟）
deploy/scripts/deploy-all.sh --env-file /opt/openfactory/deploy.env

# 5) 验收
deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json
deploy/scripts/doctor.sh --services
```

首次部署后的人工动作：

1. Cloudflare 控制台确认 Worker Custom Domain 为 `api.<domain>`；
2. Pages 项目绑定 `admin.<domain>`，等待证书 Active；
3. `ALLOWED_ORIGIN` 指向 `https://admin.<domain>`；
4. 用真实 GitHub 账号走一遍：登录 → 同步收藏 → 热榜 → 推荐 → 通知中心。

### 4.2 常规发布（标准流程）

```bash
# 0) 记录当前版本与回滚点
git -C /opt/workspace/opensource-factory rev-parse --short HEAD
cd edge && npx wrangler deployments list --config wrangler.production.toml | head

# 1) 代码更新（独立部署检出，不与其他 worktree 混用）
git -C /opt/workspace/opensource-factory fetch --all --tags
git -C /opt/workspace/opensource-factory checkout <目标 tag / commit>

# 2) 备份（见 §8.2 / §8.3）
# 3) 预检
deploy/scripts/preflight.sh --env-file /opt/openfactory/deploy.env --target all

# 4) 发布
deploy/scripts/deploy-all.sh --env-file /opt/openfactory/deploy.env

# 5) 冒烟 + 观察
deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json
```

发布后 15 分钟内观察：

- `smoke-test` 全绿；
- `journalctl -u openfactory-api -u openfactory-worker --since "15 min ago" -p err` 无新增错误；
- admin 登录、仓库列表、热榜、推荐、通知中心可打开；
- `resource-budget.sh` 无新增 FAIL；
- 若接入外部监控，错误率 / 延迟回到基线。

### 4.3 分组件部署

| 组件 | 命令 | 适用场景 | 注意 |
| --- | --- | --- | --- |
| edge | `deploy/scripts/deploy-edge.sh --env-file ...` | 仅 Worker / D1 变更 | 会执行远端迁移与 `wrangler deploy` |
| admin | `deploy/scripts/deploy-admin.sh --env-file ...` | 仅前端变更 | 强制 `VITE_DEMO_MODE=false` |
| vps | `deploy/scripts/deploy-vps.sh --env-file ...` | 仅后端变更 | 需 root；重启 4 个单元 |
| 全部 | `deploy/scripts/deploy-all.sh --env-file ...` | 常规发布 | 任一步失败即停止 |

### 4.4 部署失败处理

1. **立即停止**：不要连续重试，避免把半成品状态扩大；
2. **保留现场**：执行 `deploy/scripts/ops-diagnose.sh --env-file /opt/openfactory/deploy.env`；
3. **判断阶段**：
   - 预检失败：修配置 / 凭据，不涉及线上；
   - edge 部署失败：Worker 可能仍是旧版本，检查 `wrangler deployments list`；
   - admin 构建失败：Pages 仍是旧版本，线上不受影响；
   - vps 重启失败：按 §7.5.2 处理，必要时回滚到上一提交；
4. **回滚或修复**：按 §6 执行；不要在故障现场直接改生产代码；
5. **记录**：变更单标记失败原因、回滚版本、恢复时间。

## 5. 升级 SOP

### 5.1 升级前评估

| 检查 | 动作 | 阻断条件 |
| --- | --- | --- |
| 变更范围 | 阅读需求 / PR / commit，列出 edge、admin、vps、deploy、docs 变更 | 范围不清 |
| 数据库迁移 | 检查 `edge/migrations/*.sql` 新增文件；检查 `vps/app/db.py` 是否补列 | 未备份 |
| 配置变更 | diff `Settings.model_fields` 与两份 env 模板；新增键先补 `.env` | 缺配置键 |
| 依赖变更 | 检查 `package-lock.json` / `requirements.txt` 变化 | 未评估体积 / 兼容性 |
| 资源影响 | 新模型 / 新任务是否突破 4G / 15G | 超预算未优化 |
| 回滚点 | 记录当前 commit、Worker deployment、Pages deployment、备份文件 | 缺一不可 |

### 5.2 升级前检查单

- [ ] 变更单已填写，窗口已确认；
- [ ] 当前版本与目标版本已记录；
- [ ] SQLite 快照完成，`PRAGMA integrity_check` 返回 `ok`；
- [ ] D1 导出完成，文件包含 `BEGIN` / `COMMIT` 且可读；
- [ ] `/opt/openfactory/backups` 剩余空间 ≥ 3G；
- [ ] `uptime` 1 分钟 load < `nproc`，可用内存 ≥ 2G；
- [ ] `preflight.sh` 全绿；
- [ ] 回滚命令已在预发 / 临时环境演练（重大变更必须）。

### 5.3 标准升级步骤

```bash
# 1) 冻结写入（可选：暂停 beat，避免升级中触发任务）
sudo systemctl stop openfactory-beat

# 2) 备份（§8.2 / §8.3）
# 3) 更新代码
git -C /opt/workspace/opensource-factory fetch --all --tags
git -C /opt/workspace/opensource-factory checkout <目标版本>

# 4) 预检
deploy/scripts/preflight.sh --env-file /opt/openfactory/deploy.env --target all

# 5) 发布（含 D1 迁移、Worker、Pages、VPS 重启）
deploy/scripts/deploy-all.sh --env-file /opt/openfactory/deploy.env

# 6) 恢复 beat
sudo systemctl start openfactory-beat

# 7) 验收
deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json
deploy/scripts/doctor.sh --services
```

> 若升级包含 D1 迁移，`deploy-edge.sh` 会先执行 `wrangler d1 migrations apply --remote`；
> 迁移是**前向、不可自动回滚**的。升级前备份是唯一可靠的回退手段。

### 5.4 配置变更

1. 先在 `deploy/env/openfactory.env.example` / `vps/.env.example` 补键（模板入库）；
2. 再改 `/opt/openfactory/.env`（600，不入库）；
3. `deploy/scripts/doctor.sh` 校验键集合；
4. 重启受影响单元：`systemctl restart openfactory-api openfactory-worker openfactory-beat`；
5. 变更 `INTERNAL_TOKEN` 时，必须同步 Worker secret，见 §9.2。

### 5.5 升级后观察期

- 0–15 分钟：冒烟、错误日志、关键页面；
- 15–60 分钟：任务队列是否积压、beat 是否按计划触发、资源是否异常；
- 24 小时：对比错误率、推荐 / 推送任务成功率、备份是否正常；
- 观察期内禁止连续发布无关变更。

### 5.6 升级失败判定

满足任一条件即触发回滚评估：

- `smoke-test` 连续 2 次失败；
- API 5xx 比例 > 5% 持续 10 分钟；
- 核心链路（登录 / 收藏 / 推荐 / 通知）不可用；
- 数据写入错误或数据损坏；
- 内存 / 磁盘突破红线且无法在 15 分钟内缓解。

## 6. 回滚 SOP

### 6.1 回滚触发条件

| 条件 | 级别 | 动作 |
| --- | --- | --- |
| 三端不可用 / 登录全挂 | P0 | 立即回滚，先恢复服务 |
| 核心链路不可用（收藏 / 推荐 / 通知） | P1 | 15 分钟内决策回滚或修复 |
| 数据错误 / 丢失 | P1 | 停止写入，按 §8 恢复 |
| 性能明显劣化（P95 翻倍） | P2 | 评估回滚 |
| 单页面 / 非核心功能异常 | P2/P3 | 可前滚修复 |

### 6.2 回滚决策矩阵

| 变更类型 | 首选 | 备选 | 说明 |
| --- | --- | --- | --- |
| 纯前端（admin） | Pages 回滚上一 deployment | 重新构建上一 commit | 不影响 API / 数据 |
| 纯 Worker（edge，无 D1 迁移） | `wrangler rollback` | 重新部署上一 commit | 秒级生效 |
| Worker + D1 迁移 | 代码回滚 + 数据恢复 | 前滚修复 | 迁移不回滚，先评估兼容性 |
| 纯 VPS 代码（无 schema 变更） | `git checkout` 上一 commit + `deploy-vps.sh --skip-deps` | 重装依赖后部署 | 运行目录数据不变 |
| VPS + SQLite schema 变更 | 代码回滚 + SQLite 快照恢复 | 前滚修复 | 恢复需停服 |
| 配置错误 | 恢复上一版 `.env` + 重启 | 热修配置 | 先备份当前 `.env` |
| 数据损坏 | 停服 + 最近备份恢复 | 人工修复 | 记录数据丢失窗口 |

### 6.3 edge 回滚

```bash
cd edge
npx wrangler deployments list --config wrangler.production.toml
# 找到上一个稳定版本的 deployment id
npx wrangler rollback <deployment-id> --config wrangler.production.toml

# 验证
curl -fsS https://api.<domain>/healthz
deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json
```

> `wrangler rollback` 只回滚 Worker 代码，**不会回滚 D1 迁移**。如果新版本依赖新表 / 新列，
> 回滚旧代码前必须确认旧代码能容忍这些新增结构（通常可以，删除列 / 改类型则不行）。

### 6.4 admin 回滚

**方式 A（推荐，最快）**：Cloudflare Dashboard → Pages → 项目 → Deployments → 选择上一个稳定
deployment → **Rollback**。

**方式 B（命令行）**：切回上一 commit 后重新发布：

```bash
git -C /opt/workspace/opensource-factory checkout <上一稳定 commit>
deploy/scripts/deploy-admin.sh --env-file /opt/openfactory/deploy.env
```

验证：打开 `https://admin.<domain>`，确认页面标题 / 版本号 / 登录入口正常，浏览器无白屏。

### 6.5 vps 回滚

```bash
# 1) 记录当前版本与现场
git -C /opt/workspace/opensource-factory rev-parse --short HEAD
deploy/scripts/ops-diagnose.sh --env-file /opt/openfactory/deploy.env

# 2) 切回上一稳定 commit（独立部署检出，避免影响开发 worktree）
git -C /opt/workspace/opensource-factory checkout <上一稳定 commit>

# 3) 依赖未变时跳过安装；有依赖变化则去掉 --skip-deps
deploy/scripts/deploy-vps.sh --env-file /opt/openfactory/deploy.env --skip-deps

# 4) 验证
systemctl is-active openfactory-redis openfactory-api openfactory-worker openfactory-beat
curl -fsS http://127.0.0.1:8000/healthz
deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json
```

> 若回滚跨过 SQLite schema 变更，旧代码可能不认识新列。SQLite 补列是幂等的，通常向前兼容；
> 若旧代码启动报 `no such column`，按 §8.4 恢复升级前快照，并记录数据丢失窗口。

### 6.6 数据库回滚 / 恢复

**D1**：

```bash
cd edge
# 1) 先导出现场（即使已损坏，也保留证据）
npx wrangler d1 export "$D1_DATABASE_NAME" --remote \
  --output "/opt/openfactory/backups/d1-before-restore-$(date +%Y%m%d-%H%M%S).sql" \
  --config wrangler.production.toml

# 2) 用升级前备份恢复（先在 staging / 本地库演练）
npx wrangler d1 execute "$D1_DATABASE_NAME" --remote \
  --file /opt/openfactory/backups/d1-<timestamp>.sql \
  --config wrangler.production.toml

# 3) 验证表数量 / 关键行数 / 登录链路
```

**SQLite**：

```bash
# 1) 停写
sudo systemctl stop openfactory-worker openfactory-beat openfactory-api

# 2) 保留现场
cp -a /opt/openfactory/data/opensource_factory.db \
  /opt/openfactory/backups/opensource_factory.before-restore-$(date +%Y%m%d-%H%M%S).db

# 3) 恢复（使用 sqlite3 .restore，避免半截文件）
sqlite3 /opt/openfactory/data/opensource_factory.db \
  ".restore '/opt/openfactory/backups/sqlite-<timestamp>.db'"
sqlite3 /opt/openfactory/data/opensource_factory.db "PRAGMA integrity_check;"

# 4) 启动并验证
sudo systemctl start openfactory-api openfactory-worker openfactory-beat
deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json
```

> 数据恢复是**最后手段**：会丢失备份时间点之后的数据。执行前必须确认备份时间点、
> 影响范围、是否可接受；执行后必须在变更单记录数据丢失窗口。

### 6.7 回滚后验证清单

- [ ] `smoke-test.sh --json` 三项 PASS；
- [ ] `doctor.sh --services` 全绿；
- [ ] 4 个 systemd 单元 `active`；
- [ ] 登录 → 收藏 → 热榜 → 推荐 → 通知中心 主链路可用；
- [ ] 错误日志无新增持续错误；
- [ ] 资源预算 `PASS`；
- [ ] 变更单记录回滚版本、原因、验证结果、遗留问题。

## 7. 故障处理 SOP

### 7.1 故障分级

| 级别 | 定义 | 示例 | 响应 | 恢复目标 |
| --- | --- | --- | --- | --- |
| P0 | 全站不可用 / 数据安全事件 | 三端全挂、D1 不可用、密钥泄漏 | 立即 | 30 分钟内止血 |
| P1 | 核心功能不可用 | 登录失败、收藏 / 推荐 / 通知全挂 | 15 分钟内响应 | 2 小时内恢复 |
| P2 | 非核心功能异常 / 性能劣化 | 单页面报错、任务延迟、P95 翻倍 | 1 小时内响应 | 24 小时内恢复 |
| P3 | 体验问题 / 个别用户 | 文案错误、个别数据不一致 | 下一工作日 | 按排期 |

### 7.2 通用五步法

1. **确认影响面**：哪些端、哪些用户、何时开始、是否仍在扩大；
2. **保留现场**：`deploy/scripts/ops-diagnose.sh --env-file /opt/openfactory/deploy.env`；
3. **止血**：重启 / 回滚 / 摘除故障组件 / 限流；优先恢复服务，不追求当场根因；
4. **定位根因**：按 §7.3 快速诊断，结合日志、版本、变更记录；
5. **恢复验证与复盘**：`smoke-test` + 主链路，P0/P1 24 小时内出复盘。

### 7.3 快速诊断命令

```bash
# 版本与变更
git -C /opt/workspace/opensource-factory rev-parse --short HEAD
cd edge && npx wrangler deployments list --config wrangler.production.toml

# 进程 / 端口
systemctl status openfactory-redis openfactory-api openfactory-worker openfactory-beat --no-pager
ss -lntp | grep -E ':(8000|6379|80|443)\b'

# 健康检查
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS https://api.<domain>/healthz
curl -fsS https://node.<domain>/healthz
curl -fsS -o /dev/null -w '%{http_code}\n' https://admin.<domain>/

# 日志
journalctl -u openfactory-api -n 100 --no-pager
journalctl -u openfactory-worker -n 100 --no-pager
journalctl -u openfactory-beat -n 100 --no-pager
journalctl -u openfactory-redis -n 50 --no-pager

# 资源
free -m; df -h /opt/openfactory; uptime; ps aux --sort=-%cpu | head
deploy/scripts/resource-budget.sh --json

# Redis / 队列
redis-cli -h 127.0.0.1 -p 6379 ping
cd vps && .venv/bin/celery -A app.tasks.celery_app inspect ping
```

### 7.4 常见故障场景

| 现象 | 可能原因 | 检查 | 处理 |
| --- | --- | --- | --- |
| `api.<domain>` 502 / 1101 | Worker 崩溃 / 脚本异常 | `wrangler deployments list`；Cloudflare Workers 日志 | 回滚上一 Worker 版本；修复后重发 |
| Worker 报 D1 `no such table` | 迁移未执行 | `wrangler d1 migrations list <db> --remote` | 执行 `wrangler d1 migrations apply`；先备份 |
| admin 白屏 / 资源 404 | Pages 部署不完整 / 缓存 | 浏览器 Network；Pages deployment | 回滚上一 Pages deployment；清缓存重试 |
| admin 显示演示数据 | 构建时 `VITE_API_BASE_URL` 为空或 `VITE_DEMO_MODE=true` | 构建日志 / 页面横幅 | 用 `deploy-admin.sh` 重新构建发布 |
| 登录 501 | GitHub OAuth 未配置 | Worker secret `GITHUB_CLIENT_ID/SECRET` | 补 secret 并重发 Worker |
| CORS 报错 | `ALLOWED_ORIGIN` 与 admin 域名不一致 | Worker 配置 / 浏览器报错 | 修正为精确域名（含协议） |
| VPS API 502 / 健康检查失败 | 进程崩溃 / 端口占用 / 配置错误 | `systemctl status openfactory-api`；日志 | 修配置 → 重启；反复失败回滚上一版本 |
| worker 不消费任务 | Redis 不通 / worker 崩溃 / 队列积压 | `systemctl status openfactory-worker`；`redis-cli ping` | 重启 Redis / worker；检查 `REDIS_URL` |
| beat 不触发任务 | beat 未启动 / schedule 文件损坏 | `systemctl status openfactory-beat`；日志 | 重启 beat；必要时删除 `celerybeat-schedule` 重建 |
| Redis OOM / 写入失败 | `maxmemory 256mb` 打满 | `redis-cli info memory` | 清理积压任务；扩容需评估预算 |
| Ollama 不可用 / 摘要超时 | 模型未加载 / 端口不通 | `curl http://127.0.0.1:11434/api/tags`；`ollama ps` | 启动 Ollama / `ollama pull`；确认降级链生效 |
| 内存持续上涨 / OOM | worker 并发过高 / 模型峰值 | `resource-budget.sh`；`systemctl show -p MemoryCurrent` | 降并发、缩短 `OLLAMA_KEEP_ALIVE`、切小模型 |
| 磁盘满 | 日志 / 备份 / 模型缓存 | `du -sh /opt/openfactory/*`；`df -h` | 清日志 / 旧备份 / 未用模型；按 §10 处理 |
| SQLite `database is locked` | 长事务 / 并发写 | `journalctl`；`lsof` 数据库文件 | 停写、重试；检查 worker 并发与任务时长 |
| Caddy 证书失败 | DNS 未指向本机 / 80 被占用 / 代理 | `dig`；`ss -lntp`；Caddy 日志 | 修 DNS / 释放 80；重启 Caddy |
| 内部接口 401 | `INTERNAL_TOKEN` 不一致 | VPS `.env` 与 Worker secret 对比（不回显） | 按 §9.2 同步轮换 |
| 429 限流 | 触发接口配额 | 访问日志 / 监控 | 确认是否攻击；调整限流需评估 |
| 推送未送达 | 通道凭据 / 静默 / 阈值 | 任务日志、推送状态接口 | 检查通道配置、静默窗口、阈值；重试任务 |

### 7.5 重点场景详细 SOP

#### 7.5.1 三端不可用（P0）

1. 确认是否单端还是全端：分别 `curl` 三个入口；
2. 若仅 Cloudflare 端不可用：检查 Cloudflare 状态页、Worker deployment、DNS；
3. 若仅 VPS 不可用：按 §7.5.2；
4. 若全部不可用：优先排查 DNS / 域名 / 证书 / 本机网络；
5. 止血：回滚最近一次变更；无法回滚则切静态维护页（如已配置）；
6. 恢复后补做 §6.7 验证。

#### 7.5.2 VPS API 健康检查失败（P1）

```bash
systemctl status openfactory-api --no-pager
journalctl -u openfactory-api -n 200 --no-pager
ss -lntp | grep ':8000'
curl -v http://127.0.0.1:8000/healthz
```

- 配置错误：修 `/opt/openfactory/.env` → `systemctl restart openfactory-api`；
- 依赖缺失：`cd vps && .venv/bin/pip install -r requirements.txt` → 重启；
- 数据库损坏：按 §8.4 恢复；
- 代码缺陷：回滚上一 commit（§6.5）。

#### 7.5.3 Celery 任务积压 / 不执行（P1/P2）

```bash
systemctl status openfactory-worker openfactory-beat --no-pager
redis-cli -h 127.0.0.1 -p 6379 llen celery
cd vps && .venv/bin/celery -A app.tasks.celery_app inspect active
cd vps && .venv/bin/celery -A app.tasks.celery_app inspect reserved
```

- worker 崩溃：重启；反复崩溃看日志中的任务异常；
- 队列积压：确认是否单个长任务阻塞；必要时扩容 worker 并发（受 768M 上限约束）；
- beat 不触发：重启 beat；确认 `celerybeat-schedule` 可写；检查时区 / 调度配置。

#### 7.5.4 D1 / 数据库异常（P0/P1）

- `no such table`：迁移未执行，先备份再 `wrangler d1 migrations apply`；
- D1 写入失败 / 配额：Cloudflare 控制台查看 D1 指标；必要时清理历史数据；
- 数据错误：停止写入 → 导出当前 → 恢复备份 → 校验；
- 任何恢复操作都必须记录时间点与影响范围。

#### 7.5.5 资源红线（P1/P2）

```bash
deploy/scripts/resource-budget.sh --json
free -m; df -h /opt/openfactory
ps aux --sort=-%mem | head
```

按 [resource-budget-verification.md](./resource-budget-verification.md) §6 处理：
降 worker 并发、缩短模型驻留、清理日志 / 归档 / 旧备份、切小模型。处理后在变更单记录。

#### 7.5.6 证书 / 域名（P2）

- `curl -vI https://node.<domain>` 看证书有效期；
- `dig +short node.<domain>` 确认解析到本机公网 IP；
- `ss -lntp | grep ':80'` 确认 80 未被占用；
- Caddy 日志：`journalctl -u caddy -n 100 --no-pager`；
- 修复后 `systemctl reload caddy` 或重启。

#### 7.5.7 安全事件 / 密钥泄漏（P0）

1. 立即轮换泄漏的密钥（§9.2 / §9.3）；
2. 检查访问日志、异常登录、异常任务；
3. 若涉及用户数据，评估影响范围并按隐私策略通知；
4. 保留证据，24 小时内出复盘；
5. 在 `docs/requirements/open-questions.md` 记录处置与后续改进。

#### 7.5.8 数据损坏 / 误删（P0/P1）

1. **立即停止写入**：停 worker / beat / api；
2. 保留现场（当前库 + 日志）；
3. 选择最近可用备份，评估丢失窗口；
4. 按 §8.4 / §6.6 恢复；
5. 校验完整性 + 主链路；
6. 复盘根因（误操作 / 代码缺陷 / 磁盘故障）。

### 7.6 事故复盘模板

```text
事故编号：INC-YYYYMMDD-NN
级别：P0 / P1 / P2 / P3
影响：影响的端 / 用户 / 时长 / 数据范围
时间线：
  HH:MM 发现（告警 / 用户反馈）
  HH:MM 响应（谁、做了什么）
  HH:MM 止血（回滚 / 重启 / 限流）
  HH:MM 恢复
  HH:MM 复盘完成
根因：
为什么没有更早发现：
做对了什么：
需要改进：
行动项（负责人 / 截止日期）：
  - [ ] ...
文档 / 监控更新：
```

## 8. 备份与恢复 SOP

### 8.1 备份对象与频率

| 对象 | 频率 | 保留 | 存放 | 说明 |
| --- | --- | --- | --- | --- |
| SQLite 主库 | 每日（升级 / 回滚前必做） | 最近 7 份 | `/opt/openfactory/backups/` | 一致性快照 |
| D1 元数据 | 每日（升级 / 回滚前必做） | 最近 7 份 | `/opt/openfactory/backups/` | `wrangler d1 export` |
| `.env` / `redis.conf` | 配置变更前 | 最近 3 份 | 加密存放 | 含密钥，禁止明文外传 |
| 代码 | 每次发布 | git 历史 | GitHub | tag / commit |
| 日志 | 不需要备份 | journald / 滚动 | 本机 | 故障时保留现场 |

> 备份总量受 3GB 预算约束（见 [resource-plan.md](../planning/resource-plan.md)）。
> 超过保留份数时按「最旧优先」清理，清理前确认最新备份可用。

### 8.2 SQLite 快照

```bash
STAMP="$(date +%Y%m%d-%H%M%S)"
DB="/opt/openfactory/data/opensource_factory.db"
OUT="/opt/openfactory/backups/sqlite-${STAMP}.db"

sqlite3 "$DB" ".backup '$OUT'"
sqlite3 "$OUT" "PRAGMA integrity_check;"
ls -lh "$OUT"
```

要求：`integrity_check` 返回 `ok`；文件大小与主库接近；记录到变更单。

### 8.3 D1 导出

```bash
cd edge
STAMP="$(date +%Y%m%d-%H%M%S)"
npx wrangler d1 export "$D1_DATABASE_NAME" --remote \
  --output "/opt/openfactory/backups/d1-${STAMP}.sql" \
  --config wrangler.production.toml
head -5 "/opt/openfactory/backups/d1-${STAMP}.sql"
grep -c '^INSERT' "/opt/openfactory/backups/d1-${STAMP}.sql" || true
```

要求：文件非空、包含 `BEGIN` / `COMMIT`（或等价事务边界）、关键表有 `INSERT`。
D1 导出需要 Cloudflare 凭据；VPS 不持有凭据时，在部署控制机执行后转存。

### 8.4 SQLite 恢复

```bash
# 1) 停写
sudo systemctl stop openfactory-worker openfactory-beat openfactory-api

# 2) 保留现场
cp -a /opt/openfactory/data/opensource_factory.db \
  /opt/openfactory/backups/opensource_factory.before-restore-$(date +%Y%m%d-%H%M%S).db

# 3) 恢复
sqlite3 /opt/openfactory/data/opensource_factory.db \
  ".restore '/opt/openfactory/backups/sqlite-<timestamp>.db'"
sqlite3 /opt/openfactory/data/opensource_factory.db "PRAGMA integrity_check;"

# 4) 启动
sudo systemctl start openfactory-api openfactory-worker openfactory-beat
deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json
```

### 8.5 D1 恢复

```bash
cd edge
# 1) 先导出现场
npx wrangler d1 export "$D1_DATABASE_NAME" --remote \
  --output "/opt/openfactory/backups/d1-before-restore-$(date +%Y%m%d-%H%M%S).sql" \
  --config wrangler.production.toml

# 2) 恢复（先在本地 / staging 演练）
npx wrangler d1 execute "$D1_DATABASE_NAME" --remote \
  --file /opt/openfactory/backups/d1-<timestamp>.sql \
  --config wrangler.production.toml

# 3) 校验
npx wrangler d1 execute "$D1_DATABASE_NAME" --remote \
  --command "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;" \
  --config wrangler.production.toml
```

### 8.6 恢复演练（每月）

1. 在临时目录创建演练库：`mkdir -p /tmp/openfactory-drill && cp <备份> /tmp/openfactory-drill/`；
2. `sqlite3 /tmp/openfactory-drill/<备份> "PRAGMA integrity_check;"`；
3. 用临时端口启动 API 指向演练库（不要影响生产）：
   `cd vps && DATABASE_URL=sqlite:////tmp/openfactory-drill/<备份> .venv/bin/uvicorn app.main:app --port 18000`；
4. `curl http://127.0.0.1:18000/healthz`；
5. 记录演练结果（备份时间、恢复耗时、校验结果、问题）；
6. 演练结束后删除临时目录。

## 9. 安全与密钥 SOP

### 9.1 密钥清单

| 密钥 | 存放位置 | 用途 | 轮换周期 | 影响 |
| --- | --- | --- | --- | --- |
| `INTERNAL_TOKEN` | VPS `/opt/openfactory/.env` + Worker secret | edge ↔ VPS 内部鉴权 | 90 天 / 泄漏时 | 轮换期间内部接口短暂 401 |
| `SESSION_SECRET` | Worker secret | 会话签名 | 90 天 / 泄漏时 | 用户需重新登录 |
| `GITHUB_CLIENT_SECRET` | Worker secret | GitHub OAuth | 180 天 / 泄漏时 | 登录失败 |
| `CLOUDFLARE_API_TOKEN` | 部署控制机 `deploy.env`（600） | 部署 / D1 / Pages | 90 天 | 部署失败 |
| `DEEPSEEK_API_KEY` | VPS `.env`（可选） | 云端摘要降级 | 180 天 | 摘要降级到截断 |
| `BARK_DEVICE_KEY` / Telegram / SMTP | VPS `.env`（按需） | 推送通道 | 180 天 | 对应通道不可用 |
| SSH key | 部署机 / GitHub Secrets | 发布登录 | 按需 | 部署中断 |

> 任何密钥不得出现在仓库、聊天、日志、截图、诊断包中。诊断包可能包含日志，外发前必须人工审查。

### 9.2 `INTERNAL_TOKEN` 轮换

```bash
# 1) 生成新令牌（不回显）
NEW_TOKEN="$(openssl rand -hex 32)"

# 2) 更新 VPS .env（600）
python3 - "$NEW_TOKEN" <<'PY'
import sys, pathlib
token = sys.argv[1]
path = pathlib.Path('/opt/openfactory/.env')
lines = path.read_text().splitlines()
out = [f'INTERNAL_TOKEN={token}' if line.startswith('INTERNAL_TOKEN=') else line for line in lines]
path.write_text('\n'.join(out) + '\n')
path.chmod(0o600)
PY

# 3) 更新 Worker secret（在 edge/ 下，令牌从 stdin 传入，不落盘、不回显）
cd /opt/workspace/opensource-factory/edge
printf '%s' "$NEW_TOKEN" | npx wrangler secret put INTERNAL_TOKEN --config wrangler.production.toml

# 4) 重启 VPS 侧
sudo systemctl restart openfactory-api openfactory-worker openfactory-beat

# 5) 验证内部接口 / 任务
deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json
```

> 轮换顺序：先更新 Worker secret，再更新 VPS 并重启，最后验证；期间内部调用可能短暂 401。
> 若需要零中断，采用双令牌（`INTERNAL_TOKEN` + `INTERNAL_TOKEN_PREVIOUS`）方案；当前基线为停机轮换。

### 9.3 其他密钥轮换

- **SESSION_SECRET**：`wrangler secret put SESSION_SECRET` → 重新发布 Worker → 用户重新登录；
- **GITHUB_CLIENT_SECRET**：GitHub OAuth App 重置 secret → 更新 Worker secret → 重发 Worker → 验证登录；
- **CLOUDFLARE_API_TOKEN**：Cloudflare 控制台创建新 token → 更新部署控制机 `deploy.env`（600）→ 撤销旧 token；
- **DEEPSEEK / 推送密钥**：服务商控制台轮换 → 更新 `/opt/openfactory/.env` → 重启对应单元。

### 9.4 泄漏处置

1. **立即撤销 / 轮换**泄漏密钥；
2. 检查 Cloudflare / GitHub / 服务商审计日志，确认是否有异常调用；
3. 检查 VPS 登录记录、异常进程、crontab、systemd 单元；
4. 评估数据影响，必要时通知用户；
5. 24 小时内复盘，更新本文档与 `open-questions`；
6. 若密钥曾进入 git 历史，按项目规范重写历史并通知协作者（需维护者批准）。

### 9.5 访问控制基线

- `/opt/openfactory` 700，`.env` / `redis.conf` 600；
- Redis 仅监听 `127.0.0.1` / `::1`，`protected-mode yes`；
- 防火墙仅开放 22 / 80 / 443：`ufw status`；
- `CORS_ORIGINS` / `ALLOWED_ORIGIN` 使用精确域名，禁止 `*`；
- 仓库密钥扫描：`git grep -nE 'sk-|ghp_|CLOUDFLARE_API_TOKEN=[A-Za-z0-9]'` 应无命中；
- 定期检查 `systemctl cat openfactory-*` 是否被篡改。

## 10. 监控与告警

### 10.1 监控分层

| 层 | 指标 | 工具 | 阈值 / 期望 |
| --- | --- | --- | --- |
| 可用性 | 三端 `/healthz` / 首页 | `smoke-test.sh`、外部 uptime 监控 | 连续 2 次失败告警 |
| 进程 | 4 个 systemd 单元 | `systemctl`、journald | 任一 `failed` 告警 |
| 资源 | 内存 / 磁盘 | `resource-budget.sh` | 3.5G / 4G、13G / 15G 预警 |
| 应用 | 5xx、任务失败、队列长度 | 日志 / 后续 M5-03 监控接口 | 5xx > 5%、队列持续增长 |
| 边缘 | 请求量 / 错误率 / 延迟 | Cloudflare Workers Analytics | 错误率 > 1% 关注 |
| 数据 | D1 容量 / 迁移状态 | Cloudflare 控制台 | 接近配额告警 |
| 证书 | 到期时间 | `curl -vI` / Caddy | < 30 天续期 |

### 10.2 告警路由（当前基线）

- 当前为单人维护：告警进入维护者邮箱 / 即时通讯；
- P0/P1 立即处理；P2 当日处理；P3 排期；
- M5-03 监控告警合入后，按 `MONITOR_ALERT_WEBHOOK_URL` 外发，并在本节补充告警去重 / 静默 / 恢复通知；
- 任何告警静默必须记录原因与截止时间，禁止长期静默。

### 10.3 日志治理

```bash
journalctl --disk-usage
journalctl --vacuum-time=14d
du -sh /opt/openfactory/logs
```

- API 文件日志按 10MB × 5 滚动；journald 保留 14 天；
- 故障现场日志先复制到诊断目录，再清理；
- 日志中不得打印 token / 密码；发现即按 §9.4 处理。

## 11. 附录

### 11.1 命令速查

| 目的 | 命令 |
| --- | --- |
| 三端冒烟 | `deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env --json` |
| 运行目录自检 | `deploy/scripts/doctor.sh --services` |
| 资源预算 | `deploy/scripts/resource-budget.sh --json` |
| 现场诊断 | `deploy/scripts/ops-diagnose.sh --env-file /opt/openfactory/deploy.env` |
| 三端部署 | `deploy/scripts/deploy-all.sh --env-file /opt/openfactory/deploy.env` |
| 预检 | `deploy/scripts/preflight.sh --env-file /opt/openfactory/deploy.env --target all` |
| Worker 版本 | `cd edge && npx wrangler deployments list --config wrangler.production.toml` |
| Worker 回滚 | `cd edge && npx wrangler rollback <deployment-id> --config wrangler.production.toml` |
| VPS 重启 | `systemctl restart openfactory-api openfactory-worker openfactory-beat` |
| VPS 日志 | `journalctl -u openfactory-api -n 100 --no-pager` |
| Redis 探活 | `redis-cli -h 127.0.0.1 -p 6379 ping` |
| 模型预算 | `cd vps && .venv/bin/python -m app.model_budget check --probe` |
| 降级自检 | `cd vps && .venv/bin/python -m app.degradation check` |

### 11.2 端口与环境变量

| 项 | 值 |
| --- | --- |
| VPS API | `127.0.0.1:8000`（Caddy `node.<domain>`） |
| Redis | `127.0.0.1:6379` |
| Caddy | `:80` / `:443` |
| 运行目录 | `/opt/openfactory`（`OPENFACTORY_HOME` 可覆盖） |
| SQLite | `/opt/openfactory/data/opensource_factory.db` |
| 日志 | `/opt/openfactory/logs/` |
| 备份 | `/opt/openfactory/backups/` |
| 部署配置 | `/opt/openfactory/deploy.env`（600） |

### 11.3 相关文档

- [部署基线](./deployment-baseline.md)
- [正式部署手册](./production-deployment.md)
- [资源预算实测](./resource-budget-verification.md)
- [Agent 维护指南](./agent-maintenance.md)
- [架构总览](../architecture/overview.md)
- [数据模型](../architecture/data-model.md)
- [资源规划](../planning/resource-plan.md)
- [需求池](../requirements/backlog.md)

### 11.4 更新记录

| 日期 | 变更 |
| --- | --- |
| 2026-10-22 | 创建（REQ-202610-0945 / M5-07）：部署、升级、回滚、故障处理、备份恢复、密钥与巡检 SOP |
