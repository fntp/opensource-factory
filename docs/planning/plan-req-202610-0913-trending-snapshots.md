# 实施计划 · REQ-202610-0913 热榜快照入库与去重（按日快照 + 趋势字段）

> 需求：REQ-202610-0913（backlog M2-05，依赖 M2-01）｜ 分支：`feat/req-202610-0913-trending-snapshots`
> 目标：在每日抓取之后写入「按日、按仓库唯一」的热榜快照，计算 Star / 排名趋势字段，并同步到 D1 供热榜页按日期、语言筛选（M2-06）。

## 1. 现状与问题

- `trending_repositories` 以 `owner/repo` 为主键，只保留「最新状态」，同一仓库每天抓取会覆盖上一日数据；
- 无法回答「某天的热榜是什么」「排名上升/下降多少」「连续上榜几天」；
- 同一仓库会出现在全局页与多个语言页，抓取层已做单轮去重，但重复执行同一日任务仍可能产生重复快照；
- D1 侧没有快照表，边缘接口只能读最新状态，无法支持 M2-06 的日期 / 语言筛选。

## 2. 方案

### 2.1 数据模型

新增 `trending_snapshots`（VPS SQLite 与 D1 同构）：

- 主键 `(snapshot_date, repo_id)`：按日快照 + 同日去重（同一仓库一天只有一行）；
- 元信息：`platform` / `owner` / `name` / `html_url` / `description` / `language` / `tech_stack`；
- 指标：`stars` / `stars_today` / `rank` / `language_rank`；
- 趋势：`star_delta`（对比上一有效快照的总 Star 增量）、`rank_delta`（正数=上升）、`appearances`（连续上榜天数）、`is_new`、`trend`（`new` / `up` / `down` / `steady`）；
- `trending_pages`：来源语言页 JSON，便于追溯重复来源。

### 2.2 快照服务（vps/app/services/trending_snapshot.py）

- `build_snapshot_rows(items, snapshot_date, previous)`：纯函数；按 `repo_id` 去重合并（数值取大、空字段互补、来源页并集），按 `stars_today` / `stars` 排序生成 `rank`，按语言分组生成 `language_rank`；
- `compute_trend`：对比同一仓库「上一有效快照」（默认回看 7 天）计算 `star_delta` / `rank_delta` / `appearances` / `is_new` / `trend`；
- `save_trending_snapshots`：预取上一快照与当日已有行，逐条 upsert；重复执行同一日期幂等，不产生重复行；
- `push_trending_snapshots`：配置 `EDGE_BASE_URL` + `INTERNAL_TOKEN` 时，分批（默认 200 条）写回 D1；失败只记日志，不影响本地入库与任务状态。

### 2.3 任务接入（vps/app/tasks/jobs.py）

- `crawl_trending` 在 upsert 最新状态后调用快照服务，返回 `snapshots` 统计（date / total / created / updated / pushed / pushFailed / skipped）；
- 快照写入异常不得影响抓取主流程，按降级返回错误信息。

### 2.4 API

VPS：

- `GET /api/trending/snapshots?date=&language=&platform=&limit=`：按日期（默认最近一天）、语言筛选快照；
- `GET /api/trending/dates?limit=`：可用快照日期与条数；
- `GET /api/trending/history?repoId=&days=`：单仓库 Star / 排名历史。

Edge：

- `GET /api/trending?date=&language=&limit=`：优先读快照（无快照时回退最新状态表，保持兼容）；
- `GET /api/trending/dates`：可用日期；
- `POST /api/internal/trending/snapshots`：VPS 批量 upsert（`X-Internal-Token`，单批 ≤ 500）。

### 2.5 迁移与文档

- `edge/migrations/0002_trending_snapshots.sql` + `docs/assets/d1-schema.sql`；
- 同步 `docs/architecture/data-model.md`、`docs/architecture/overview.md`、`vps/README.md`、`edge/README.md`、`docs/requirements/backlog.md`。

## 3. 去重与趋势口径

1. **同日去重**：`(snapshot_date, repo_id)` 唯一；重复抓取执行 upsert；
2. **同轮去重**：同一 `repo_id` 多语言页出现时合并为一条，`stars` / `stars_today` 取最大，来源页取并集；
3. **趋势基线**：取该仓库在 `snapshot_date` 之前最近一条快照（最多回看 7 天）；
4. **趋势标签**：无基线 → `new`；`rank_delta >= 3` → `up`；`rank_delta <= -3` → `down`；其余 → `steady`；
5. **连续上榜**：基线日期与当前日期相差 1 天时 `appearances + 1`，否则重置为 1。

## 4. 测试与验证

| 检查 | 内容 |
| --- | --- |
| `vps/.venv/bin/pytest -q` | 快照构建 / 去重 / 趋势计算 / 幂等 upsert / 任务接入 / API 筛选 |
| `edge npm run typecheck` | 快照路由与类型 |
| `git diff --check` | 空白与格式检查 |

## 5. 交付边界

- 本需求负责「快照存储 + 趋势字段 + 查询接口」，热榜页的日期 / 语言筛选 UI 与趋势标注属 M2-06；
- 快照保留窗口 / 归档 / 清理属 M2-08；
- 测试不访问网络，Edge 推送通过 MockTransport 覆盖。
