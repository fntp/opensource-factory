# 数据一致性巡检 · Data Consistency Audit

> 文档编号：GD-04 ｜ 对应需求：REQ-202610-0908（backlog M1-16）｜ 维护人：fntp
> 适用场景：同步后核对、发布前检查、每日定时巡检、故障排查

本文档说明 **D1（主数据）↔ 本机 SQLite 镜像（算力缓存）** 的对账工具：如何拉取 D1 快照、如何运行巡检、如何解读差异以及如何接入定时任务。

## 1. 目标与边界

- **目标**：以只读方式回答三个问题——哪些记录本机缺失、哪些记录 D1 缺失、双方都有的记录中哪些字段不一致；
- **不修改数据**：工具只执行 `SELECT` / `PRAGMA`，修复动作由同步任务或后续数据治理需求（M9-05）执行；
- **不依赖 Cloudflare 密钥**：D1 数据由 edge 的内部快照接口提供（在线），或使用 `wrangler d1 export` 的离线产物；
- **列交集原则**：D1 与本机表结构可能处于不同迭代，只有双方都存在的列参与比较；缺失列会在报告中标注 `skippedFields`，避免误报。

## 2. 总体链路

```text
D1（Cloudflare）
  │  edge GET /api/internal/consistency/snapshot
  │  X-Internal-Token · 表/列白名单 · 主键排序 · 分页
  ▼
vps/scripts/consistency_audit.py
  ├── --edge-url   在线拉取（推荐）
  ├── --d1-db      wrangler d1 export → sqlite3 还原
  └── --snapshot   JSON 快照（离线 / 归档）
  ▼
vps/app/services/consistency.py
  ├── 归一化（文本 / 整数 / 浮点 / 时间）
  ├── 按主键对齐 → 缺失 / 多余 / 字段差异 / 重复主键
  └── 文本摘要 + Markdown + JSON 报告
```

## 3. 前置条件

1. edge Worker 已配置 `INTERNAL_TOKEN`（`wrangler secret put INTERNAL_TOKEN`）；
2. VPS 能访问 Worker 地址（内网或公网 HTTPS 均可）；
3. 本机镜像库已初始化（`vps/data/opensource_factory.db`，或由 `DATABASE_URL` 指定）；
4. 巡检只读，不需要 GitHub / Cloudflare 凭据。

> 未配置 `INTERNAL_TOKEN` 时，快照接口返回 **503** 并保持关闭——这是默认的安全姿态，避免把 D1 数据暴露在公网。

## 4. 快速开始

### 4.1 在线巡检（推荐）

```bash
cd /opt/workspace/opensource-factory/vps

# INTERNAL_TOKEN 从运行环境读取，不要写进命令行历史
export INTERNAL_TOKEN="$(grep '^INTERNAL_TOKEN=' /opt/openfactory/.env | cut -d= -f2-)"

.venv/bin/python scripts/consistency_audit.py \
  --edge-url https://<worker-domain> \
  --token "$INTERNAL_TOKEN" \
  --report /opt/openfactory/logs/consistency-report.md \
  --json-out /opt/openfactory/logs/consistency-report.json
```

### 4.2 离线巡检（D1 导出）

```bash
# 1) 导出 D1 为 SQL，再还原成 SQLite（本机执行）
npx wrangler d1 export opensource-factory --remote --output /tmp/d1-export.sql
sqlite3 /tmp/d1-export.db < /tmp/d1-export.sql

# 2) 对账
cd /opt/workspace/opensource-factory/vps
.venv/bin/python scripts/consistency_audit.py \
  --d1-db /tmp/d1-export.db \
  --report /tmp/consistency-report.md
```

### 4.3 JSON 快照

支持三种格式：

```jsonc
// A. 汇总格式（推荐用于归档）
{ "tables": { "my_repositories": [ ... ] }, "columns": { "my_repositories": ["id", "stars"] } }

// B. 单表格式
{ "table": "my_repositories", "columns": ["id", "stars"], "rows": [ ... ] }

// C. wrangler d1 execute --json 输出
[ { "results": [ ... ], "success": true } ]
```

```bash
.venv/bin/python scripts/consistency_audit.py \
  --snapshot /tmp/d1-snapshot.json --tables my_repositories
```

## 5. CLI 参数

| 参数 | 说明 |
| --- | --- |
| `--edge-url` | edge Worker 地址；与 `--d1-db` / `--snapshot` 三选一 |
| `--token` | 内部令牌；默认读 `INTERNAL_TOKEN` 环境变量 |
| `--d1-db` | D1 导出后还原的 SQLite 文件 |
| `--snapshot` | JSON 快照文件 |
| `--local-db` | 本机镜像 SQLite；默认读 `DATABASE_URL`，否则 `vps/data/opensource_factory.db` |
| `--tables` | 对账表，逗号分隔；默认五张核心表（见下） |
| `--ignore-fields` | 忽略字段，格式 `table.field`，可重复 |
| `--sample-limit` | 每类差异保留的样例条数（默认 10） |
| `--page-size` | 在线拉取分页大小（默认 500，上限 1000） |
| `--timeout` | 在线拉取单次请求超时秒数（默认 30） |
| `--report` | 输出 Markdown 报告 |
| `--json-out` | 输出 JSON 报告 |
| `--allow-diff` | 发现差异仍返回 0（仅告警场景） |
| `--quiet` | 不打印摘要，仅写报告 |

默认对账表：

| 表 | 主键 | 说明 |
| --- | --- | --- |
| `my_repositories` | `id`（`owner/repo`） | 我的仓库（核心资产） |
| `categories` | `id` | 分类树 |
| `trending_repositories` | `id` | 热榜快照 |
| `users` | `id` | 用户（D1 `login` ↔ 本地 `username`） |
| `recommendations` | `id` | 推荐结果 |

## 6. 报告与退出码

命令行摘要示例：

```text
数据一致性巡检 · D1 ↔ 本机镜像
数据源: edge https://api.example.com
本地库: /opt/openfactory/data/opensource_factory.db
生成时间: 2026-10-22T04:00:00+00:00

表                            D1     本地   本机缺失   D1缺失  字段差异    状态
my_repositories              120      118          2        0         3      差异
categories                    12       12          0        0         0      一致

结论: 发现差异（本机缺失 2 · D1 缺失 0 · 字段差异 3）
```

| 退出码 | 含义 | 建议 |
| --- | --- | --- |
| `0` | 全部一致 | 无需处理 |
| `1` | 发现差异 | 查看报告，按差异类型处理（见 §7） |
| `2` | 输入 / 连接错误 | 检查路径、令牌、Worker 可达性与表结构 |

报告字段：

| 字段 | 含义 |
| --- | --- |
| `missingInLocal` | D1 有、本机没有 → 通常需要重新同步 |
| `missingInD1` | 本机有、D1 没有 → 确认是否本地临时数据 / D1 删除未同步 |
| `mismatches` | 双方都有但字段值不同（附主键、字段、两侧值） |
| `mismatchFields` | 按字段统计的差异数量，用于判断系统性问题 |
| `duplicateKeys` | 主键重复（数据质量告警；正常情况下不应出现） |
| `skippedFields` | 未参与比较的字段及原因（`ignored` / `d1_column_missing` / `local_column_missing`） |
| `comparedFields` | 实际参与比较的列，便于复核 |

## 7. 差异处理建议

1. **先确认主数据方向**：D1 为主数据，本机镜像允许重建；
2. `missingInLocal`：对本机执行同步任务（`POST /api/tasks/sync`）或按主键补拉；
3. `missingInD1`：确认是否为本地临时数据；若是 D1 侧误删，按备份恢复，不要直接反向覆盖；
4. **字段差异**：先看 `mismatchFields` 是否集中在某个字段——例如 `stars` / `updated_at` 通常是同步时间差，`readme_summary` 可能是摘要版本差异；
5. **重复主键**：属于数据质量问题，记录后由 M9-05 数据治理处理；
6. 巡检报告建议保留至少 30 天，便于对比差异是否收敛。

## 8. 定时巡检

推荐用 systemd timer（读取运行目录 `.env`，避免把令牌写进 crontab）：

```ini
# /etc/systemd/system/openfactory-consistency.service
[Unit]
Description=OpenFactory D1 ↔ local mirror consistency audit
After=network-online.target openfactory-api.service

[Service]
Type=oneshot
User=openfactory
WorkingDirectory=/opt/workspace/opensource-factory/vps
EnvironmentFile=/opt/openfactory/.env
ExecStart=/opt/workspace/opensource-factory/vps/.venv/bin/python scripts/consistency_audit.py \
  --edge-url https://<worker-domain> \
  --report /opt/openfactory/logs/consistency-report.md \
  --json-out /opt/openfactory/logs/consistency-report.json
```

```ini
# /etc/systemd/system/openfactory-consistency.timer
[Unit]
Description=Daily OpenFactory consistency audit

[Timer]
OnCalendar=*-*-* 04:17:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload
systemctl enable --now openfactory-consistency.timer
journalctl -u openfactory-consistency.service -n 50
```

> 退出码 `1` 会让 service 进入 failed，便于 `systemd` / 监控告警；若只做记录，可在 `ExecStart` 末尾加 `--allow-diff`。

## 9. 接口契约（edge 内部）

`GET /api/internal/consistency/snapshot?table=<name>&limit=<1..1000>&offset=<n>`

请求头：`X-Internal-Token: <INTERNAL_TOKEN>`

响应：

```json
{
  "table": "my_repositories",
  "key": "id",
  "columns": ["id", "platform", "name", "..."],
  "rows": [{ "id": "owner/repo", "stars": 10 }],
  "offset": 0,
  "limit": 500,
  "total": 120,
  "hasMore": true,
  "generatedAt": "2026-10-22T04:00:00.000Z"
}
```

| 状态码 | 含义 |
| --- | --- |
| `200` | 正常返回 |
| `400` | 表名不在白名单 / `limit` / `offset` 非法 |
| `401` | 令牌缺失或不匹配 |
| `503` | 服务端未配置 `INTERNAL_TOKEN`（接口关闭） |

安全约束：只允许五张白名单表与固定列；不接受任意 SQL；主键排序保证分页稳定；令牌只存 Worker secret，不下发浏览器。

## 10. 已知限制

- **全量拉取**：按 `offset/limit` 分页，适合万级数据；数据量继续增长后可改为按主键游标；
- **列交集**：本地尚未镜像的 D1 新列不会比较，需先完成 schema 对齐；
- **不自动修复**：差异只报告，修复由同步 / 数据治理流程执行；
- **时间精度**：统一到秒，忽略小数秒与时区表示差异；如需毫秒级核对，可在 `normalize_datetime` 中调整。
