# 实施计划 · REQ-202610-0904 秒级检索优化（索引与查询计划核对，P95 < 300ms）

> 需求：REQ-202610-0904（backlog M1-12，依赖 M1-11）｜ 分支：feat/req-202610-0904-search-perf
> 目标：仓库检索接口在 D1（SQLite）上 P95 < 300ms（spec §6），并留下可复跑的查询计划核对与基准脚本。

## 1. 现状与问题

- `GET /api/repos`（edge）只有 `(user_id)` / `(category_id)` 两个单列索引：
  - 列表默认 `ORDER BY stars DESC, updated_at DESC`，会触发临时 B-Tree 排序；
  - `WHERE user_id = ? AND category_id = ?` 只能命中单列索引之一，过滤后仍需排序；
  - 接口无 `limit`，一次返回用户全部仓库，数据量增长后响应时间不可控。
- `vps` 本地镜像 `GET /api/repos` 同样只有主键，分类 + Star 排序无索引；SQLite 既有库不会因
  `create_all` 自动补索引。
- 缺少「查询计划 + P95」的可复跑验收手段，性能目标无法证明。

## 2. 方案

### 2.1 索引（D1 迁移 0003）

| 索引 | 列 | 服务的查询 |
| --- | --- | --- |
| `idx_my_repositories_user_stars` | `(user_id, stars DESC, updated_at DESC)` | 用户仓库列表 / 关键字过滤后的排序 |
| `idx_my_repositories_user_category_stars` | `(user_id, category_id, stars DESC, updated_at DESC)` | 分类筛选 + Star 排序 |

> 迁移编号用 `0003`：`0002` 已被并行需求 REQ-202610-0899（增量同步）占用，避免合并冲突。
> `LIKE '%q%'` 无法走 B-Tree 索引；索引先把扫描范围收敛到单用户（及单分类）分区，
> 再按索引顺序过滤，避免全表扫描与临时排序。README 全文检索留给 M6-01（FTS）。

### 2.2 接口

- edge `GET /api/repos`：新增 `limit`（默认 100，上限 200）与 `offset`，参数化绑定；
  关键字长度截断 100，`%` / `_` / `\` 转义（`ESCAPE '\'`），避免通配符放大扫描。
- vps `GET /api/repos`：补充按 `id` 匹配；关键字转义；稳定排序（`stars DESC, id ASC`）。
- vps `init_db()`：启动时幂等 `CREATE INDEX IF NOT EXISTS`，兼容既有本地镜像库。

### 2.3 验证

- `edge/scripts/search-bench.mjs`：用 `node:sqlite` 加载真实迁移、灌入 20k 仓库，
  断言 `EXPLAIN QUERY PLAN` 命中新索引且无 `USE TEMP B-TREE FOR ORDER BY`，
  再对四类查询各跑 200 次，输出 P50 / P95，P95 ≥ 300ms 时退出码非 0。
- `vps/tests/test_search_perf.py`：5k 行基准 + 查询计划断言 + API 过滤行为。
- 三端常规检查：admin lint/build/test、edge typecheck、vps pytest。

## 3. 交付物

- `edge/migrations/0003_search_indexes.sql`、`docs/assets/d1-schema.sql`
- `edge/src/routes/repos.ts`、`edge/scripts/search-bench.mjs`、`edge/package.json`、CI
- `vps/app/models.py`、`vps/app/db.py`、`vps/app/api/repos.py`、`vps/tests/test_search_perf.py`
- `docs/guides/search-performance.md`、架构 / README / 计划文档同步

## 4. 风险与边界

- 本机无法连接真实 D1（Q3 凭据未就绪），P95 以同引擎本地 SQLite 基准为准，远端复测步骤写入指南；
- M1-11（组合筛选与排序）尚未合并，本需求只覆盖现有 `q` / `categoryId` 查询，索引已为分类 + Star 排序预留；
- 关键字子串检索仍为分区内扫描，数据量继续增长时由 M6-01 的 FTS 承接。

## 5. 验证记录

2026-10-22 本机：

- `cd edge && npm run perf:search`：迁移 `0001_init.sql, 0003_search_indexes.sql`；
  20k 仓库 / 50 用户 / 12 分类 / 30 标签；四类查询均命中预期索引、无临时排序；
  P95 分别约 1.1ms / 0.7ms / 1.4ms / 0.4ms（预算 300ms）。
- `cd edge && npm run typecheck`：0 error。
- `cd vps && .venv/bin/pytest -q`：23 passed（含新增 3 条检索用例）。
- 未执行：真实 D1 远端复测（Q3 凭据未就绪），步骤见 `docs/guides/search-performance.md` §4。

## 6. 交付边界

- 本需求只优化现有 `q` / `categoryId` 查询；M1-11 的组合筛选 / 多字段排序接口尚未合并，
  其排序所需的 `(user_id, stars, updated_at)` / `(user_id, category_id, stars, updated_at)` 索引已预留；
- 关键字子串检索为分区内扫描，README 全文检索由 M6-01（FTS）承接。
