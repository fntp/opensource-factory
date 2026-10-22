# 运维手册 · 热榜数据保留（M2-08）

> 适用：VPS 本地镜像 `trending_snapshots` 与 edge D1 同表；需求 REQ-202610-0916。
> 相关配置：`vps/.env`（模板见 `vps/.env.example`）；代码：`vps/app/services/trending_retention.py`。

## 1. 保留口径

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `TRENDING_RETENTION_DAYS` | `90` | 快照保留天数（含当天）；`0` = 暂停自动清理 |
| `TRENDING_ARCHIVE_ENABLED` | `true` | 删除前归档为 gzip JSONL；关闭后直接删除（不推荐） |
| `TRENDING_ARCHIVE_DIR` | `./data/archives` | 归档目录；相对路径按 `vps/` 解析 |
| `TRENDING_ARCHIVE_KEEP_DAYS` | `365` | 归档文件保留天数；`0` = 永久保留 |
| `TRENDING_RETENTION_HOUR` / `TRENDING_RETENTION_MINUTE` | `4` / `17` | 每日清理时刻（Asia/Shanghai） |

清理边界：`cutoff = today - TRENDING_RETENTION_DAYS`，删除 `snapshot_date < cutoff`；`cutoff` 当天保留。
默认 90 天、每天数百行，SQLite 增量约 15~30MB；归档压缩后一年约 60MB 内，符合 15G 磁盘预算。

## 2. 日常检查

```bash
# 保留策略状态（窗口、过期数、SQLite 文件大小、归档文件数 / 字节）
curl -s http://127.0.0.1:8000/api/trending/retention | python -m json.tool

# 只统计不删除（dry-run，会同时返回 D1 侧将删除数量）
curl -s -X POST 'http://127.0.0.1:8000/api/trending/retention/cleanup?dryRun=true' \
  -H 'Content-Type: application/json'
```

`GET /api/trending/retention` 关键字段：

- `expiredSnapshots`：超出保留窗口、待清理的行数；
- `databaseBytes`：SQLite 文件大小（监控数据目录 2GB 配额）；
- `archiveFiles` / `archiveBytes`：归档目录占用。

## 3. 手动执行

```bash
# 入队清理（默认 90 天、归档开启）；返回 202 taskId
curl -s -X POST 'http://127.0.0.1:8000/api/trending/retention/cleanup' \
  -H 'Content-Type: application/json'

# 自定义窗口 / 关闭归档（谨慎）
curl -s -X POST 'http://127.0.0.1:8000/api/trending/retention/cleanup?retentionDays=180&archive=false'

# 查询任务结果
curl -s http://127.0.0.1:8000/api/tasks/<taskId> -H "X-Internal-Token: $INTERNAL_TOKEN"
```

任务返回示例：

```json
{
  "status": "ok",
  "retentionDays": 90,
  "cutoff": "2026-07-24",
  "totalBefore": 31200,
  "expired": 420,
  "archived": 420,
  "archiveFile": "/opt/openfactory/data/archives/trending-snapshots-2026-04-01_2026-07-23.jsonl.gz",
  "archiveBytes": 183422,
  "deleted": 420,
  "edge": {"skipped": false, "deleted": 420, "error": null}
}
```

- `status=partial`：本地清理成功，但 D1 清理失败（`edge.error` 给出原因），可稍后重跑；
- `status=error`：归档失败，**未删除任何数据**，先排查磁盘 / 权限。

## 4. 归档格式与恢复

归档为 gzip JSONL，一行一条记录：

- 第 1 行：格式头 `{"format":"openfactory.trending_snapshots","version":1,"exportedAt":"...","beforeDate":"...","firstDate":"...","lastDate":"...","rowCount":N}`；
- 第 2 行起：与 `trending_snapshots` 字段一致的记录（`snapshot_date` 为 `YYYY-MM-DD`）。

查看：

```bash
gzip -dc data/archives/trending-snapshots-2026-04-01_2026-07-23.jsonl.gz | head -3
```

恢复（示例：把归档行回灌本地 SQLite，按主键幂等）：

```bash
python - <<'PY'
import gzip, json, sqlite3

archive = "data/archives/trending-snapshots-2026-04-01_2026-07-23.jsonl.gz"
conn = sqlite3.connect("data/opensource_factory.db")
rows = []
with gzip.open(archive, "rt", encoding="utf-8") as fh:
    next(fh)  # 跳过格式头
    for line in fh:
        item = json.loads(line)
        rows.append(tuple(item[k] for k in (
            "snapshot_date", "repo_id", "platform", "owner", "name", "html_url",
            "description", "language", "tech_stack", "stars", "stars_today",
            "rank", "language_rank", "star_delta", "rank_delta", "appearances",
            "is_new", "trend", "trending_pages", "created_at", "updated_at",
        )))
conn.executemany(
    "INSERT OR REPLACE INTO trending_snapshots VALUES (" + ",".join("?" * 21) + ")",
    rows,
)
conn.commit()
print("restored", len(rows))
PY
```

> 恢复前先备份数据库；D1 侧如需恢复，按同样 JSONL 逐行调用 `POST /api/internal/trending/snapshots`（单批 ≤ 500）。

## 5. 故障处理

| 现象 | 排查 |
| --- | --- |
| `status=error`，提示归档失败 | 检查 `TRENDING_ARCHIVE_DIR` 是否存在、磁盘剩余空间、运行用户写权限；修复后重跑任务 |
| `status=partial`，`edge.error=HTTP 503` | edge 未配置 `INTERNAL_TOKEN`，或 VPS 与 edge 令牌不一致；补齐后重跑 |
| `expiredSnapshots` 长期不降 | 确认 Celery beat 已启动（`vps-beat`）、`TRENDING_RETENTION_DAYS > 0`；查看 worker 日志 |
| SQLite 文件未变小 | 删除只释放页，不自动收缩；在维护窗口手动 `VACUUM`（避开抓取 / 摘要任务） |
| 归档目录持续增长 | 调小 `TRENDING_ARCHIVE_KEEP_DAYS` 或迁移旧归档到备份盘；`prune_archives` 只删 `trending-snapshots-*.jsonl.gz` |

## 6. 变更记录

| 日期 | 变更 |
| --- | --- |
| 2026-10-22 | 首版：REQ-202610-0916 / M2-08 保留窗口、归档与清理落地 |
