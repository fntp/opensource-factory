# 实施计划 · REQ-202610-0914 热榜页联动（日期 / 语言筛选、趋势标注）

> 对应需求：REQ-202610-0914（backlog M2-06）｜ 分支：`feat/req-202610-0914-trending-page`｜ 日期：2026-10-22｜ 状态：已完成（依赖 M2-05 / REQ-202610-0913 已合入本分支）

## 1. 目标

在已有「每日热榜」前端骨架上补齐三件事：

1. **按日快照可查**：热榜数据按 `snapshot_date` 保存每日快照，页面可按日期切换；
2. **语言筛选**：按快照中的主语言筛选，并与日期组合生效；
3. **趋势标注**：每条项目展示相对上一可用快照日的排名变化（新上榜 / 上升 / 下降 / 持平）。

## 2. 现状与缺口

- `admin/src/features/trending` 只有静态榜单：无日期、语言筛选，无趋势字段；
- edge `GET /api/trending` 直接读 `trending_repositories` 最新表，按 `stars_today` 排序，无法按日回溯；
- VPS `crawl_trending` 只 upsert 最新表，每日抓取会覆盖，没有历史快照；
- M2-05（REQ-202610-0913）已提供按日快照、排名与趋势字段；本分支合入该依赖，复用其 `trending_snapshots` 模型与写入服务，只补页面所需的查询契约与 UI。

## 3. 方案

### 3.1 数据模型（复用 M2-05 迁移 `0002_trending_snapshots.sql`）

复用 M2-05 已建的 `trending_snapshots`：

| 字段 | 说明 |
| --- | --- |
| snapshot_date | 快照日期（`YYYY-MM-DD`） |
| repo_id | `owner/repo` |
| platform / owner / name / html_url / description / language | 项目元信息 |
| stars / stars_today / tech_stack | 指标与技术栈 |
| rank / language_rank | 全平台综合排名 / 同语言内排名 |
| rank_delta / star_delta | 相对上一有效快照的排名变化（正数 = 上升）/ Star 增量 |
| appearances / is_new / trend | 连续上榜天数 / 是否新上榜 / `new`·`up`·`down`·`steady` |
| trending_pages | 来源语言页 JSON 数组 |

主键 `(snapshot_date, repo_id)` 实现按日去重；索引覆盖日期 + 排名、仓库 + 日期、日期 + 语言。页面将 `rank_delta` 的符号映射为 `up` / `down` / `same`，`is_new=1` 映射为 `new`。

### 3.2 VPS 写入

- 复用 M2-05 的 `TrendingSnapshot` 模型与 `trending_snapshot.save_trending_snapshots`；
- `crawl_trending` 抓取后按 `repo_id` 去重，upsert 最新表 + 当日快照，并在配置边缘地址时批量回写 D1；
- 本需求只新增 `GET /api/trending` 的日期 / 语言筛选映射，以及 `/api/trending/languages` 语言分布接口。

### 3.3 edge 读取

- `GET /api/trending?date=YYYY-MM-DD&language=Python&limit=20`：读快照表，按 `rank` 排序；
  缺省日期取最新快照日；无快照时回退最新表（兼容旧数据）；
- `GET /api/trending/dates?limit=30`：可用快照日期列表（新 → 旧，`[{date, count}]`）；
- `GET /api/trending/languages?date=YYYY-MM-DD`：当日语言及数量；
- 列表项追加 `snapshotDate`、`rank`、`rankChange`、`trend`（`up` / `down` / `new` / `same`），并保留 M2-05 的 `languageRank` / `starDelta` / `rankDelta` / `appearances` / `isNew` 扩展字段。

### 3.4 admin 页面

- 日期下拉（来自 `/api/trending/dates`）+ 语言下拉（来自 `/api/trending/languages`）；
- 查询键包含日期与语言，切换即重新请求；加载 / 空态 / 错误重试；
- 每条展示排名、趋势徽标（新上榜 / ↑N / ↓N / —）、今日 Star 与总 Star；
- 保留演示数据兜底，演示模式下按日期 / 语言本地过滤。

## 4. 文件清单

- `edge/migrations/0002_trending_snapshots.sql`（M2-05 提供）、`docs/assets/d1-schema.sql`
- `edge/src/trending/query.ts`、`edge/src/routes/trending.ts`、`edge/src/types.ts`
- `edge/scripts/trending-query.test.mjs`、`edge/package.json`
- `vps/app/api/trending.py`、`vps/app/schemas.py`（模型与写入服务由 M2-05 提供）
- `vps/tests/test_trending_page_api.py`
- `admin/src/features/trending/api.ts`、`admin/src/features/trending/trend.ts`、`admin/src/features/trending/index.tsx`、`admin/src/features/trending/trend.test.ts`
- `docs/architecture/overview.md`、`docs/architecture/data-model.md`、`docs/planning/task-planning.md`、`docs/requirements/backlog.md`
- 基线修复：`admin/src/components/layout/data/sidebar-data.ts`、`.gitignore`

## 5. 验证计划

| 检查 | 命令 |
| --- | --- |
| edge 类型 | `cd edge && npm run typecheck` |
| edge 单测 | `cd edge && npm run test:trending` |
| vps 单测 | `cd vps && .venv/bin/pytest -q` |
| admin 静态 | `cd admin && npm run lint && npm run build` |
| admin 单测 | `cd admin && npm run test` |

## 6. 风险与边界

1. 本分支已合入 M2-05（REQ-202610-0913）；若平台先合并 M2-05，注意按 0913 的 `rank_delta` / `is_new` / `trend` 字段口径验收；
2. 生产 D1 需在合并后执行迁移 `0002`；
3. 真实多语言抓取依赖 M2-01（REQ-202610-0909）合并；本分支只保证快照与查询契约；
4. 快照保留 / 清理策略由 M2-08 承接，本需求不删除历史快照；
5. 页面趋势按 `rank_delta` 符号展示（±1 也显示 ↑/↓），与 M2-05 后端 `trend` 字段的 ±3 阈值口径不同，已在 API 层做映射。
