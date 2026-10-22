# 实施计划 · REQ-202610-0941 监控与告警（健康检查 / 资源监控 / 日志 / Workers Analytics）

> 需求：REQ-202610-0941（backlog M5-03）｜ 分支：`feat/req-202610-0941-monitoring-alerting`
> 依赖：M5-01 正式部署（部署基线已具备 `/opt/openfactory` 运行目录与 systemd 单元）
> 目标：为「本机 VPS + Cloudflare 边缘」建立可观测闭环：健康检查、4G/15G 资源红线、
> 日志治理与 Workers 请求分析，并提供告警落库 / 去重 / 确认与运维查询入口。

## 1. 现状与缺口

- 已有 `GET /healthz` 仅返回进程存活，不检查数据库 / Redis / 磁盘等依赖；
- `deploy/scripts/doctor.sh` 只校验运行目录与配置，不是持续监控；
- 资源规划要求内存 > 3.5G、磁盘 > 13G 预警，但没有采集、阈值判定与告警记录；
- API 已有滚动日志，但缺少日志占用统计、保留策略与清理入口；
- Workers 侧只有 Cloudflare 控制台，没有项目内可查询的请求量 / 错误率 / 延迟视图。

## 2. 方案总览

```
                    ┌─────────────────────────────┐
  admin 系统监控页 ──▶│ edge /api/monitoring/overview│
                    └───────┬───────────────┬─────┘
                            │               │
                  D1 worker_metrics     VPS /api/monitoring/status
                  （请求量 / 错误 / 延迟）   （健康检查 + 资源 + 告警 + 日志）
                            ▲               │
          edge 中间件按请求聚合写入            ├─ /proc、cgroup、磁盘、日志目录
                                            └─ Celery beat 每 5 分钟 monitor_system_health
                                                 ├─ 阈值判定（3.5G / 4G、13G / 15G）
                                                 ├─ monitoring_alerts 去重 / 冷却 / 恢复
                                                 ├─ 可选 webhook 通知
                                                 └─ monitoring_check_runs 历史
```

设计要点：

- **边缘与节点各自采集、统一视图**：Workers 指标落在 D1（无需 Cloudflare API Token），
  VPS 指标由本机采集；admin 只调用 edge 的 `/api/monitoring/overview`。
- **健康检查分层**：`/healthz` 存活探针保持轻量；`/healthz/ready` 校验数据库与运行目录，
  依赖服务（Redis / edge）状态在监控详情中体现。
- **资源红线按项目预算**：内存优先读 systemd cgroup（`openfactory-*.service`），
  回退到进程 cmdline 匹配；磁盘统计运行目录实际占用；阈值可配置。
- **告警可闭环**：按 `kind + scope` 去重，冷却窗口内累加次数；条件恢复自动置 `resolved`；
  支持 `acknowledged` 人工确认与 webhook。
- **日志可治理**：统计日志目录文件与占用，按保留天数清理；API 已有 RotatingFileHandler。

## 3. 数据模型（VPS SQLite）

### 3.1 `monitoring_alerts`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | uuid hex |
| `kind` | TEXT | memory / disk / service / logs / edge / model |
| `severity` | TEXT | warning / critical |
| `message` | TEXT | 中文告警文案 |
| `details` | TEXT | JSON 详情（阈值 / 实测值） |
| `dedupe_key` | TEXT | `monitoring:<kind>:<scope>` |
| `status` | TEXT | open / acknowledged / resolved |
| `occurrences` | INTEGER | 冷却窗口内出现次数 |
| `first_seen_at` / `last_seen_at` | DATETIME | 首次 / 最近 |
| `acknowledged_at` / `resolved_at` | DATETIME | 确认 / 恢复时间 |

### 3.2 `monitoring_check_runs`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | uuid hex |
| `status` | TEXT | ok / warning / critical |
| `checks` | TEXT | 健康检查 JSON |
| `resources` | TEXT | 资源快照 JSON |
| `findings` | TEXT | 本轮告警判定 JSON |
| `created_at` | DATETIME | 执行时间 |

## 4. 接口

### 4.1 VPS

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/healthz` | GET | 无 | 存活探针（保持兼容） |
| `/healthz/ready` | GET | 无 | 就绪探针：数据库 / 运行目录，返回检查摘要 |
| `/api/monitoring/status` | GET | 内部令牌 | 实时健康检查 + 资源 + 阈值 + 告警 + 最近运行 |
| `/api/monitoring/check` | POST | 内部令牌 | 立即执行一轮检查并落库 |
| `/api/monitoring/history` | GET | 内部令牌 | 检查历史（`limit`） |
| `/api/monitoring/alerts` | GET | 内部令牌 | 告警列表（`status` / `limit`） |
| `/api/monitoring/alerts/{id}/ack` | POST | 内部令牌 | 确认告警（幂等） |
| `/api/monitoring/logs` | GET | 内部令牌 | 日志文件统计与保留策略 |
| `/api/monitoring/logs/cleanup` | POST | 内部令牌 | 按保留天数清理日志 |

### 4.2 Edge

| 端点 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/api/monitoring/health` | GET | 无 | 边缘存活 + 指标能力 |
| `/api/monitoring/overview` | GET | 登录态 | 边缘 + VPS + Workers 指标统一视图 |
| `/api/monitoring/check` | POST | 登录态 | 代理 VPS 立即检查 |
| `/api/monitoring/alerts/{id}/ack` | POST | 登录态 | 代理 VPS 确认告警 |
| `/api/internal/analytics` | GET | 内部令牌 | Workers 请求指标（VPS / 运维可读） |

## 5. 配置

新增 `MONITOR_*` 配置（VPS / deploy 两套模板同步）：

- 开关与调度：`MONITOR_ENABLED`、`MONITOR_INTERVAL_MINUTES`、`MONITOR_HOME`；
- 内存红线：`MONITOR_MEMORY_BUDGET_MB=4096`、`MONITOR_MEMORY_WARN_MB=3584`、
  `MONITOR_MEMORY_CRITICAL_MB=4096`；
- 磁盘红线：`MONITOR_DISK_BUDGET_MB=15360`、`MONITOR_DISK_WARN_MB=13312`、
  `MONITOR_DISK_CRITICAL_MB=15360`；
- 日志：`MONITOR_LOG_BUDGET_MB=1024`、`MONITOR_LOG_RETENTION_DAYS=14`；
- 告警：`MONITOR_ALERT_COOLDOWN_MINUTES=60`、`MONITOR_ALERT_WEBHOOK_URL`；
- 依赖探测：`MONITOR_EDGE_TIMEOUT_SECONDS`、`MONITOR_REDIS_TIMEOUT_SECONDS`；
- 进程匹配：`MONITOR_PROCESS_PATTERNS`（逗号分隔，`+` 连接多个关键字）；
- 历史：`MONITOR_HISTORY_RETENTION_DAYS=30`。

## 6. 前端

- 新增 `/monitoring` 页面与侧边栏「系统监控」入口；
- 总览卡片：整体状态、内存 / 4G、磁盘 / 15G、请求量 / 错误率；
- 健康检查表、告警列表（确认操作）、Workers 每日指标、日志文件与保留策略；
- 演示模式提供内置 mock，接口不可用时页面仍可预览。

## 7. 测试与验收

| 层 | 用例 |
| --- | --- |
| vps | `tests/test_monitoring.py`：meminfo / loadavg / 目录占用解析、阈值判定、告警去重与恢复、日志清理、服务与 API、就绪探针、鉴权 |
| edge | `scripts/monitoring-route.test.mjs`：天数 / 路由归一化、指标汇总、错误率与均值计算 |
| admin | `features/monitoring/monitoring.test.ts`：字节 / 百分比格式化、状态映射、mock 汇总 |

验收标准：

1. `/healthz/ready` 在数据库可用时返回 200，数据库不可用时 503；
2. 资源超过 3.5G / 13G 产生 warning，超过 4G / 15G 产生 critical；
3. 同一告警在冷却窗口内只累加不新增，条件恢复自动 resolved；
4. 日志清理只删除超过保留天数的文件；
5. Workers 指标可按天 / 路由查询请求量、错误率与平均延迟；
6. 三端 lint / typecheck / build / test 全绿。

## 8. 风险与后续

- 本机与其它项目共用时，cgroup 只统计 `openfactory-*.service`；进程匹配为回退口径；
- Workers 指标为 D1 自建聚合，非 Cloudflare GraphQL Analytics，量大时可迁移到 Analytics Engine；
- 日志清理默认只处理运行目录 `logs/`，journald 日志由 systemd 自身轮转；
- webhook 为 best-effort，失败只记日志，不影响检查任务。
