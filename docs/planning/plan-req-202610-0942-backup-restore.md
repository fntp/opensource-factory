# 实施计划 · REQ-202610-0942 备份与恢复（D1 导出 / SQLite 快照 / 恢复演练）

> 对应需求：REQ-202610-0942（backlog M5-04，P0）｜ 分支：`feat/req-202610-0942-backup-restore`｜ 日期：2026-10-22｜ 状态：已完成
> 依赖：M5-01 正式部署（REQ-202610-0939 工具链）；磁盘预算见 [resource-plan.md](./resource-plan.md) §4（备份 3.0 GB，保留最近 7 份）。

## 1. 目标与范围

把「备份与恢复」做成可执行、可验证、可审计的闭环，而不是一次性手工命令：

1. **SQLite 快照**：对 VPS 本地镜像库做一致性快照（SQLite backup API），压缩、校验、记录清单；
2. **D1 导出**：通过 wrangler 导出远端 D1（schema + data），压缩、校验、记录清单；
3. **保留策略**：默认保留最近 7 份，备份总量不超过 3 GB（可配置），自动清理最旧产物；
4. **恢复演练**：把快照 / D1 导出恢复到临时库，执行完整性检查、表清单与行数核对，输出可审计报告；
5. **恢复路径**：提供受保护的 SQLite 恢复命令（默认拒绝覆盖，覆盖前自动生成 pre-restore 安全快照）；
6. **运维接口**：内部令牌保护的备份状态 / 手动快照 / 校验 / 演练接口，Celery 每日自动快照 + 每周演练；
7. **文档与 SOP**：备份布局、调度、恢复步骤、D1 恢复注意事项、演练节奏与证据留存。

不在本需求范围：异地 / 对象存储备份、备份加密与密钥托管、Cloudflare D1 时间点恢复（PITR）、跨账号容灾。上述能力记入后续增强项。

## 2. 现状与缺口

- VPS 使用 SQLite（`DATABASE_URL=sqlite:///...`），但没有快照、校验、恢复脚本；
- 边缘 D1 的 schema / 数据只存在于 Cloudflare，部署脚本没有导出能力；
- `deploy/` 已建立运行目录 `/opt/openfactory/backups` 与生产部署工具链，但目录一直为空；
- 资源规划已给出「备份 3.0 GB / 保留 7 份」预算，缺少强制执行；
- 没有恢复演练，无法证明备份「可用」而不只是「存在」。

## 3. 方案总览

```
                         ┌──────────────────────────────┐
                         │  /opt/openfactory/backups/    │
                         │   ├── sqlite/                 │
                         │   │   ├── sqlite-*.sqlite3.gz │
                         │   │   └── sqlite-*.json       │
                         │   └── d1/                     │
                         │       ├── d1-*.sql.gz         │
                         │       └── d1-*.json           │
                         └──────────────┬───────────────┘
                                        │
   Celery beat 03:50（每日）             │      cron 04:10（每日）
   backup_sqlite ───────────────────────┤      backup-d1.sh（wrangler export）
                                        │
   Celery beat 周日 04:20（每周）        │      手工 / 上线前
   backup_drill ────────────────────────┴────── backup-drill.sh
        │
        ├─ SQLite：解压 → 临时库 → PRAGMA integrity_check / foreign_key_check
        │            → 表清单与行数对比 manifest
        └─ D1：解压 → 导入临时 SQLite → integrity_check → 表清单核对
```

设计要点：

- **备份不依赖业务库可写**：SQLite 使用 backup API 读取，状态扫描基于文件与 manifest，不写业务表；
- **清单与产物同目录**：每份备份一个 `.json` 清单（时间、大小、SHA-256、表行数、校验结果），
  文件被移动 / 截断时可快速识别；
- **D1 凭据只在部署控制面**：VPS 不持有 Cloudflare 凭据，D1 导出由 `deploy/scripts/backup-d1.sh`
  在部署机 / cron 上执行；VPS 只负责校验与演练导入；
- **恢复默认安全**：`restore` 默认拒绝覆盖现有库；`--force` 覆盖前自动生成 pre-restore 快照；
  生产恢复要求先停 `openfactory-api / worker / beat`；
- **预算硬约束**：按「份数 + 总字节」双阈值清理，至少保留每类最新 1 份。

## 4. 数据与文件布局

| 产物 | 路径 | 说明 |
| --- | --- | --- |
| SQLite 快照 | `backups/sqlite/sqlite-YYYYmmddTHHMMSSZ[-label].sqlite3.gz` | gzip 压缩的 SQLite 单文件快照 |
| SQLite 清单 | `backups/sqlite/sqlite-....json` | 源库、大小、SHA-256、表行数、完整性结果 |
| D1 导出 | `backups/d1/d1-YYYYmmddTHHMMSSZ[-label].sql.gz` | `wrangler d1 export` 的 SQL 文本，gzip |
| D1 清单 | `backups/d1/d1-....json` | 库名、大小、SHA-256、表行数、校验结果 |
| 演练临时库 | 系统临时目录（默认自动清理） | `--keep-work` 时保留，便于排查 |
| pre-restore 快照 | `backups/sqlite/sqlite-...-pre-restore.sqlite3.gz` | 覆盖恢复前的自动安全快照 |

清单示例：

```json
{
  "kind": "sqlite",
  "name": "sqlite-20261022T035000Z.sqlite3.gz",
  "createdAt": "2026-10-22T03:50:00Z",
  "source": "/opt/openfactory/data/opensource_factory.db",
  "sizeBytes": 1048576,
  "sha256": "…",
  "sqliteVersion": "3.45.1",
  "tableCounts": {"my_repositories": 120, "recommendations": 340},
  "integrity": "ok"
}
```

## 5. 核心模块

### 5.1 `vps/app/backup.py`（标准库，CLI 可独立运行）

- `create_sqlite_snapshot()`：`sqlite3.Connection.backup()` 生成一致性快照 → 完整性检查 → gzip →
  SHA-256 → manifest → 保留清理；
- `verify_sqlite_snapshot()`：解压到临时文件，只读打开，`integrity_check` / `foreign_key_check`，
  对比 manifest 的表行数与 SHA-256；
- `restore_sqlite_snapshot()`：先校验，目标存在时要求 `force`，覆盖前生成 pre-restore 快照，
  再用 backup API 写回目标并复核；
- `run_restore_drill()`：恢复到临时库，逐项比对表清单 / 行数 / 完整性，返回演练报告；
- `verify_d1_dump()`：把 SQL dump 导入临时 SQLite，检查完整性、表清单与行数；
- `finalize_d1_export()`：校验 wrangler 原始导出 → gzip → manifest → 清理；
- `list_backups()` / `backup_status()` / `prune_backups()`：扫描、汇总、按份数与总量清理；
- CLI 子命令：`create` / `list` / `status` / `verify` / `drill` / `restore` / `verify-d1` / `finalize-d1`。

### 5.2 VPS API（`/api/backup/*`，X-Internal-Token）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/backup/status` | GET | 备份目录、份数、总量、最新产物、预算使用率 |
| `/api/backup/files` | GET | 产物列表（可按 kind 过滤） |
| `/api/backup/sqlite` | POST | 立即创建 SQLite 快照 |
| `/api/backup/sqlite/verify` | POST | 校验指定 / 最新 SQLite 快照 |
| `/api/backup/sqlite/drill` | POST | 执行恢复演练 |
| `/api/backup/d1/verify` | POST | 校验指定 D1 导出（只允许备份目录内文件） |

恢复（覆盖生产库）只提供 CLI，不暴露 HTTP 接口，避免误操作。

### 5.3 Celery 调度

| 任务 | 时间 | 说明 |
| --- | --- | --- |
| `backup_sqlite` | 每日 03:50（可配置） | 生成 SQLite 快照并清理过期产物 |
| `backup_drill` | 每周日 04:20（可配置） | 对最新 SQLite 快照与 D1 导出做恢复演练 |

### 5.4 部署脚本

| 脚本 | 说明 |
| --- | --- |
| `deploy/scripts/backup-d1.sh` | 调用 `wrangler d1 export`，交给 Python CLI 完成压缩 / 校验 / 清单 / 清理 |
| `deploy/scripts/backup-all.sh` | 一次完成 SQLite 快照 + D1 导出 + 恢复演练（cron 入口） |
| `deploy/scripts/backup-drill.sh` | 只做演练：最新 SQLite 快照 + 最新 D1 导出 |
| `deploy/scripts/restore-sqlite.sh` | 受保护的 SQLite 恢复（可选停 / 起 systemd 服务） |

## 6. 配置项

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `BACKUP_ENABLED` | `true` | 总开关（关闭后定时任务跳过） |
| `BACKUP_DIR` | `./data/backups`（生产 `@RUNTIME_DIR@/backups`） | 备份根目录 |
| `BACKUP_RETENTION_COUNT` | `7` | 每类保留份数 |
| `BACKUP_MAX_TOTAL_MB` | `3072` | 备份总量上限（3 GB，0 = 不限制） |
| `BACKUP_DRILL_ENABLED` | `true` | 每周自动演练开关 |
| `BACKUP_HOUR` / `BACKUP_MINUTE` | `3` / `50` | 每日快照时间 |
| `BACKUP_DRILL_HOUR` / `BACKUP_DRILL_MINUTE` | `4` / `20` | 每周演练时间 |

## 7. 测试与验收

| 层 | 用例 |
| --- | --- |
| 单元 | 快照 / 校验 / 损坏检测 / 保留清理 / 恢复 / 演练 / D1 dump 校验 / 状态汇总 / CLI |
| API | 状态、列表、手动快照、校验、演练、D1 校验、内部令牌鉴权、路径越界拒绝 |
| 部署资产 | 新增配置键与两份 env 模板一致；新脚本 `bash -n` / `--help`；systemd 目录布局不变 |
| 调度 | Celery beat 含每日快照与每周演练条目 |

验收标准：

1. 创建快照后 `verify` 通过，manifest 中的 SHA-256 与表行数可复核；
2. 故意截断 / 篡改快照时 `verify` 失败并给出原因；
3. 保留策略只保留最近 N 份且总量不超预算，最新一份永不删除；
4. `drill` 能把快照恢复到临时库并通过完整性 / 表行数核对；
5. `restore --force` 覆盖前生成 pre-restore 快照，恢复后目标库可读；
6. D1 导出可通过 `verify-d1` 导入临时 SQLite 并核对表清单；
7. 全部 VPS 测试、edge typecheck、admin lint/build/test 通过。

## 8. 风险与人工事项

- **D1 导出依赖 Cloudflare 凭据与 wrangler**：无凭据时脚本失败并提示，不影响 SQLite 快照；
- **备份包含个人数据**：目录权限 700、文件 600；不得提交仓库、不得外发；异地加密备份列为后续增强；
- **恢复窗口**：SQLite 恢复需停 API / worker / beat，恢复后需重启并跑冒烟测试；
- **D1 恢复**：`wrangler d1 execute --remote --file` 适合中小库；超大库建议新建 D1 导入后切换绑定；
- **磁盘预算**：3 GB 为硬上限，超限时清理最旧产物并记录告警；真实占用由 M5-06 实测复核。

## 9. 实施与验证记录（2026-10-22）

| 项 | 结果 |
| --- | --- |
| VPS pytest | 253 passed（含新增 `tests/test_backup.py` 13 用例；`tests/test_deploy_assets.py` 全部通过） |
| edge typecheck | `npm run typecheck` 通过 |
| edge tests | `npm test` 27 passed |
| admin lint / build / test | ESLint 通过；Vite 生产构建通过；Vitest 14 个文件 / 92 用例通过 |
| 脚本语法 / 帮助 | 4 个新脚本 `bash -n` 通过，`--help` 均输出「用法」 |
| 配置一致性 | `Settings` / `REQUIRED_ENV_KEYS` / 两份 env 模板键集合一致（自动测试） |
| 手工冒烟 | `backup-all.sh --env-file deploy/env/deploy.env.example --dry-run` 通过；D1 dump 含 `BEGIN/COMMIT` 的事务导入校验通过 |

实现文件：

- `vps/app/backup.py`、`vps/app/api/backup.py`、`vps/app/schemas.py`（Backup* 模型）
- `vps/app/config.py` / `runtime.py` / `main.py` / `tasks/celery_app.py` / `tasks/jobs.py`
- `deploy/scripts/backup-d1.sh` / `backup-all.sh` / `backup-drill.sh` / `restore-sqlite.sh`
- `vps/tests/test_backup.py`、`vps/tests/test_deploy_assets.py`
- `docs/guides/backup-restore.md` 及索引 / 架构 / 数据模型 / 部署 / VPS / 规划文档同步

遗留人工事项：真实 D1 导出需在部署控制面配置 Cloudflare 凭据后执行；异地 / 加密备份与 D1 PITR
按 `open-questions.md` Q14 作为后续增强。
