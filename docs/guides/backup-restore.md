# 备份与恢复手册（M5-04 / REQ-202610-0942）

> 适用对象：本机维护者 / 值班同学｜实现：`vps/app/backup.py`、`deploy/scripts/backup-*.sh`、`deploy/scripts/restore-sqlite.sh`

本手册把备份从「偶尔手工执行」变成可审计的日常流程：

- **SQLite 快照**：VPS 本地镜像库的一致性快照（SQLite backup API），gzip 压缩并记录 SHA-256 / 表行数；
- **D1 导出**：通过 `wrangler d1 export` 导出远端 D1（schema + data），校验后归档；
- **恢复演练**：把快照 / D1 导出导入临时库，检查完整性、表清单与行数，证明备份真的可用；
- **保留策略**：默认每类保留最近 7 份、总量不超过 3 GB（`resource-plan.md` §4）；
- **受保护恢复**：默认拒绝覆盖生产库，`--force` 覆盖前自动生成 pre-restore 安全快照。

## 1. 备份产物布局

```
/opt/openfactory/backups/            700
├── sqlite/
│   ├── sqlite-20261022T035000Z.sqlite3.gz     600
│   ├── sqlite-20261022T035000Z.sqlite3.gz.json
│   └── sqlite-20261022T041500Z-pre-restore.sqlite3.gz
└── d1/
    ├── d1-20261022T041000Z.sql.gz
    └── d1-20261022T041000Z.sql.gz.json
```

每份产物旁边都有同名 `.json` 清单，至少包含：

| 字段 | 说明 |
| --- | --- |
| `kind` | `sqlite` / `d1` |
| `createdAt` | UTC 创建时间 |
| `sizeBytes` | 压缩后大小 |
| `sha256` | 压缩文件 SHA-256 |
| `tableCounts` | 各业务表行数（不含 `sqlite_*`） |
| `integrity` | 生成时完整性检查结果 |
| `source` / `database` | 源库路径 / D1 数据库名 |

> 备份含用户与仓库数据，属于敏感资产：目录 700、文件 600；不得提交仓库、不得直接外发。
> 当前版本不包含异地 / 对象存储与加密，后续增强项见第 9 节。

## 2. 配置项

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BACKUP_ENABLED` | `true` | 关闭后每日快照任务跳过 |
| `BACKUP_DIR` | `./data/backups`（生产 `@RUNTIME_DIR@/backups`） | 备份根目录 |
| `BACKUP_RETENTION_COUNT` | `7` | 每类保留份数（SQLite / D1 各自计算） |
| `BACKUP_MAX_TOTAL_MB` | `3072` | 全部备份总量上限（MB，0 = 不限制） |
| `BACKUP_DRILL_ENABLED` | `true` | 关闭后每周演练任务跳过 |
| `BACKUP_HOUR` / `BACKUP_MINUTE` | `3` / `50` | 每日 SQLite 快照时刻（Asia/Shanghai） |
| `BACKUP_DRILL_HOUR` / `BACKUP_DRILL_MINUTE` | `4` / `20` | 每周日演练时刻（Asia/Shanghai） |

两份环境模板（`vps/.env.example`、`deploy/env/openfactory.env.example`）与 `Settings` 字段由
`vps/tests/test_deploy_assets.py` 强制对齐，新增配置项时三处同步。

## 3. 自动调度

| 任务 | 默认时间 | 内容 |
| --- | --- | --- |
| Celery `backup_sqlite` | 每日 03:50 | SQLite 快照 + 清单 + 保留清理 |
| Celery `backup_drill` | 每周日 04:20 | 最新 SQLite 快照演练；若存在 D1 归档则一并校验 |
| `deploy/scripts/backup-d1.sh` | 建议 cron 每日 04:10 | 远端 D1 导出 + 校验 + 归档 |
| `deploy/scripts/backup-all.sh` | 可选 cron 汇总入口 | SQLite + D1 + 演练，任一步失败以非零退出 |

D1 导出需要 Cloudflare 凭据（只放在部署控制面，VPS 不持有）。示例 cron（按实际路径调整）：

```cron
10 4 * * *  cd /opt/openfactory/app && deploy/scripts/backup-d1.sh --env-file /opt/openfactory/deploy.env >> /opt/openfactory/logs/backup-d1.log 2>&1
```

`backup-all.sh` 中的 D1 失败不会影响 SQLite 快照，但最终退出码为 1，便于 cron 告警。

## 4. 手工命令

以下命令在 `vps/` 目录执行（生产可用 `.venv/bin/python`）：

```bash
# 状态 / 列表
python3 -m app.backup status --backup-dir /opt/openfactory/backups
python3 -m app.backup list   --backup-dir /opt/openfactory/backups --kind sqlite

# 立即快照（默认读 DATABASE_URL；也可显式 --database）
python3 -m app.backup create --backup-dir /opt/openfactory/backups --label manual

# 校验 / 演练（缺省最新一份；--name 指定）
python3 -m app.backup verify --backup-dir /opt/openfactory/backups
python3 -m app.backup drill  --backup-dir /opt/openfactory/backups

# D1 归档校验（.sql 或 .sql.gz）
python3 -m app.backup verify-d1 --file /tmp/d1.sql
```

CLI 失败返回非零退出码；`verify` / `drill` 的 JSON 报告包含逐项 `checks`，可直接作为演练证据留存。

## 5. 生产恢复 SOP（SQLite）

> 恢复会覆盖生产数据，必须两人复核：一人执行、一人核对备份名与目标路径。

1. **确认故障与备份**：`python3 -m app.backup list --kind sqlite`，选择故障前最近一份；
2. **先校验**：`python3 -m app.backup verify --name <snapshot>`，必须 `"ok": true`；
3. **停服务**：`systemctl stop openfactory-api openfactory-worker openfactory-beat`；
4. **恢复**（脚本会再次校验；`--force` 覆盖前自动生成 pre-restore 快照）：

   ```bash
   deploy/scripts/restore-sqlite.sh \
     --name sqlite-20261022T035000Z.sqlite3.gz \
     --target /opt/openfactory/data/opensource_factory.db \
     --force --stop-services
   ```

5. **启动并冒烟**：`systemctl start openfactory-api openfactory-worker openfactory-beat`，
   执行 `deploy/scripts/smoke-test.sh --env-file /opt/openfactory/deploy.env`；
6. **核对业务**：登录管理后台抽查仓库 / 推荐 / 热榜数据；记录恢复耗时与备份名。

若目标库不存在（首次恢复 / 新建节点），可省略 `--force`；脚本仍会先校验快照。
恢复脚本默认不删除旧库的 `-wal` / `-shm` 文件，SQLite backup API 会写入一致页；
如遇异常，停服务后确认目标目录只保留主库文件再重试。

## 6. D1 恢复

D1 的权威数据在 Cloudflare。恢复前先确认：

1. 选择 `backups/d1/d1-*.sql.gz` 并用 `verify-d1` 校验通过；
2. 在 staging / 本地 D1 先演练导入；
3. 生产恢复使用 wrangler（会执行 SQL，务必确认库名与环境）：

```bash
gzip -dc /opt/openfactory/backups/d1/d1-20261022T041000Z.sql.gz > /tmp/d1-restore.sql
cd edge
npx wrangler d1 execute "$D1_DATABASE_NAME" --remote --file /tmp/d1-restore.sql --config wrangler.production.toml
rm -f /tmp/d1-restore.sql
```

4. 恢复后检查 `GET /healthz`、登录、仓库列表与推荐接口；D1 导出中的 `DROP TABLE` / `CREATE TABLE`
   会覆盖同名表，执行前确认没有并发写入（必要时暂停 Worker 定时任务）。

> 超大库（> 数 GB）建议新建 D1 数据库导入后切换 Worker 绑定，避免单次 `d1 execute` 超时；
> 该场景属于后续增强，不在本需求范围。

## 7. 恢复演练与证据

- 每周日 Celery `backup_drill` 自动执行；也可随时 `python3 -m app.backup drill`；
- 演练只写系统临时目录，默认自动清理；`--keep-work` 可保留临时库排查；
- 报告字段：`ok`、`snapshot`、`tableCounts`、`checks[]`、`durationMs`；
- 建议把每周报告写入运维日志 / 工单，保留至少 4 周；连续失败必须人工介入。

D1 演练由 `backup-drill.sh` 校验最新归档；没有 D1 归档时明确输出「暂无 D1 导出，跳过」。

## 8. 保留与容量

- 每类至少保留最新 1 份，最新一份永不因总量预算被删；
- 先按每类 `BACKUP_RETENTION_COUNT` 删除超量最旧产物，再按 `BACKUP_MAX_TOTAL_MB` 从最旧开始删；
- `status` 返回 `usagePercent` / `withinBudget` / `freeBytes`，可接入 M5-03 监控；
- 3 GB 为资源规划预算，不是磁盘配额硬限制；真实占用由 M5-06 实测复核。

## 9. 已知边界与后续增强

- 不做异地 / 对象存储备份：本机磁盘损坏会同时丢失生产库与备份；
- 不做备份加密与密钥托管：依赖运行目录 700 / 文件 600 与主机访问控制；
- 不做 Cloudflare D1 时间点恢复（PITR）；
- 不做跨账号容灾；
- 恢复窗口内 API / worker / beat 必须停止，恢复后需冒烟与业务核对。

以上增强项记入后续需求（M9-04 全量导出与归档、M5-07 运维手册等）。

## 10. 故障排查

| 现象 | 排查 |
| --- | --- |
| `verify` 报 SHA-256 不一致 | 文件被改动 / 传输损坏；改用其他备份，勿恢复 |
| `verify` 报 `integrity_check` 失败 | 快照损坏；检查磁盘 / 压缩过程，保留现场 |
| `drill` 报表行数不一致 | 生成后源库仍在写入属正常差异；若差异大，检查 manifest 与备份时间 |
| D1 导出为空 | 检查 `D1_DATABASE_NAME`、Cloudflare 凭据与 `wrangler` 登录态 |
| `restore` 报目标已存在 | 加 `--force`（会先生成 pre-restore 快照）或换目标路径 |
| 备份目录超预算 | 降低 `BACKUP_RETENTION_COUNT` / `BACKUP_MAX_TOTAL_MB`，或扩容磁盘 |
