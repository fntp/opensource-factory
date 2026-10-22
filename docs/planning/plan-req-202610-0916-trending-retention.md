# 实施计划 · REQ-202610-0916 热榜数据保留策略（保留窗口 / 归档 / 清理）

> 需求：REQ-202610-0916（backlog M2-08，依赖 M2-05）｜ 分支：`feat/req-202610-0916-trending-retention`
> 目标：给 `trending_snapshots` 建立可配置的保留窗口、先归档后清理的安全删除流程，并让 VPS 本地镜像与 D1 同步收敛，满足 15G 磁盘预算。

## 1. 现状与问题

- M2-05 已把每日热榜写入 `trending_snapshots`（VPS SQLite + D1 同构），每天约数百行，长期运行会持续增长；
- 目前没有任何清理入口：`trending_snapshots` 只增不减，SQLite 与 D1 都会逼近磁盘 / 存储配额；
- 直接 `DELETE` 会丢失历史数据，无法回溯「某天热榜是什么」，因此清理前必须先归档；
- D1 是热榜展示镜像，VPS 是归档与任务编排方；两侧保留窗口需要一致，否则会出现「本地已删、D1 还在」或反之；
- 资源规划（`docs/planning/resource-plan.md`）要求数据目录 2GB 内、定期 VACUUM / 归档，但缺少落地任务。

## 2. 方案

### 2.1 保留口径

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `TRENDING_RETENTION_DAYS` | `90` | 快照保留天数（含当天）；`0` 表示暂停自动清理 |
| `TRENDING_ARCHIVE_ENABLED` | `true` | 清理前是否归档；关闭时直接删除（不推荐） |
| `TRENDING_ARCHIVE_DIR` | `./data/archives` | 归档目录（相对路径按 `vps/` 解析） |
| `TRENDING_ARCHIVE_KEEP_DAYS` | `365` | 归档文件保留天数；`0` 表示永久保留 |
| `TRENDING_RETENTION_HOUR` / `MINUTE` | `4` / `17` | 每日清理时间（Asia/Shanghai，抓取任务 03:27 之后） |

清理边界：`cutoff = today - retention_days`，删除 `snapshot_date < cutoff` 的行；窗口内的快照（含 cutoff 当天）保留。

### 2.2 VPS 归档与清理服务

新增 `vps/app/services/trending_retention.py`：

- `archive_snapshots(db, before_date, archive_dir)`：把 `snapshot_date < before_date` 的快照流式写成 gzip JSONL（首行是格式头，随后一行一条快照），临时文件写完再原子 `os.replace`；无数据时不创建空文件；
- `cleanup_trending_snapshots(...)`：统计过期行 → 归档（失败则**中止删除**并返回 error）→ 单事务删除 → 清理超过保留期的归档文件；
- `retention_status(...)`：返回保留配置、cutoff、总数 / 过期数、最早 / 最新日期、SQLite 文件大小、归档文件数与字节数，供运维与 API 查询；
- `cleanup_edge_trending_snapshots(...)`：调用 edge 内部清理接口，删除 D1 同日期范围；未配置 `EDGE_BASE_URL` / `INTERNAL_TOKEN` 时跳过，失败只记录不抛异常。

归档文件命名 `trending-snapshots-<最早日期>_<最新日期>.jsonl.gz`，格式头：

```json
{"format":"openfactory.trending_snapshots","version":1,"exportedAt":"...","beforeDate":"...","rowCount":123}
```

### 2.3 定时任务与接口

- Celery 任务 `app.tasks.jobs.cleanup_trending_data`：本地归档 + 删除 → 边缘 D1 清理；返回 `status / cutoff / totalBefore / expired / archived / deleted / archiveFile / edge` 等统计；本地成功、边缘失败时返回 `partial`；
- beat 计划 `cleanup-trending-daily`：每日 `TRENDING_RETENTION_HOUR:MINUTE` 触发；
- VPS API：
  - `GET /api/trending/retention`：保留策略状态；
  - `POST /api/trending/retention/cleanup?dryRun=&retentionDays=&archive=`：入队清理任务（202 `taskId`），`dryRun` 只统计不删除。

### 2.4 Edge D1 清理接口

`edge/src/routes/internal-trending.ts` 新增（均校验 `X-Internal-Token`，未配置时 503）：

- `GET /api/internal/trending/retention`：D1 快照总数、最早 / 最新日期；
- `POST /api/internal/trending/retention/cleanup`：body `{beforeDate, dryRun?}`，`DELETE FROM trending_snapshots WHERE snapshot_date < ?`，返回删除行数；`dryRun` 只计数。

### 2.5 安全与边界

- **先归档后删除**：归档异常时不删除任何行；归档文件原子落盘，避免半截文件；
- 删除按日期范围，不触碰 `trending_repositories` 最新状态表（体积小，且热榜页 / 详情页仍依赖）；
- 清理任务幂等：重复执行同一天只会归档 / 删除剩余过期行；
- 不做 `VACUUM`（避免长事务锁库）；SQLite 空间由后续运维窗口回收，状态接口暴露 `databaseBytes` 供监控；
- 所有路径与阈值可配置，默认值按 15G 预算估算（90 天约 15~30MB，归档一年约 60MB 内）。

## 3. 文件清单

- `vps/app/services/trending_retention.py`（新增）
- `vps/app/tasks/jobs.py`、`vps/app/tasks/celery_app.py`
- `vps/app/api/trending.py`、`vps/app/schemas.py`
- `vps/app/config.py`、`vps/.env.example`
- `vps/tests/test_trending_retention.py`（新增）
- `edge/src/routes/internal-trending.ts`
- `docs/architecture/data-model.md`、`docs/architecture/overview.md`
- `docs/guides/trending-retention.md`（新增运维手册）
- `vps/README.md`、`edge/README.md`
- `docs/requirements/backlog.md`、`docs/planning/roadmap.md`

## 4. 验证计划

- `cd vps && .venv/bin/pytest -q`：新增保留策略用例（归档内容 / 窗口边界 / dry-run / 归档失败不删除 / 归档过期清理 / 状态统计 / edge 清理请求 / API）；
- `cd edge && npm run typecheck`：0 error；
- `cd admin && npm run lint && npm run build && npm run test`：无前端行为变更，回归通过；
- `git diff --check`：无空白错误。

## 5. 风险与后续

- D1 清理依赖 VPS 任务成功执行；VPS 长期离线时 D1 仍会增长，后续可在 edge Cron 增加兜底（本需求不引入第二套策略）；
- 归档文件为冷数据，恢复时按 JSONL 逐行回灌即可（运维手册给出步骤）；
- 保留窗口默认 90 天，若热榜页需要更长历史（如年度榜单），调大 `TRENDING_RETENTION_DAYS` 并关注 `databaseBytes`。
