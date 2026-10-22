# 检索性能基线 · Search Performance

> 对应需求：REQ-202610-0904（M1-12）｜ 目标：`GET /api/repos` 检索 P95 < 300ms（spec §6）
> 适用：edge（Cloudflare D1）与 vps（本地 SQLite 镜像）

## 1. 索引设计

| 索引 | 列 | 服务的查询 |
| --- | --- | --- |
| `idx_my_repositories_user_stars` | `(user_id, stars DESC, updated_at DESC)` | 用户仓库列表；关键字过滤后按 Star / 更新时间排序 |
| `idx_my_repositories_user_category_stars` | `(user_id, category_id, stars DESC, updated_at DESC)` | 分类筛选 + Star / 更新时间排序 |

要点：

- 列表查询是 `WHERE user_id = ? [AND category_id = ?] ORDER BY stars DESC, updated_at DESC`；
  复合索引把过滤与排序合并，避免 `USE TEMP B-TREE FOR ORDER BY`；
- `LIKE '%q%'` 前导通配符无法走 B-Tree，索引的作用是先把扫描收敛到**单用户（单分类）分区**，
  再在分区内过滤；个人仓库量级（千级）下 P95 仍远低于预算；
- 数据量继续增长或需要 README 全文检索时，由 M6-01 的 FTS5 承接，不在本需求内。

## 2. 本地验证（提交前必跑）

```bash
# edge：20k 行灌入 + 查询计划断言 + 200 次/类 P95
cd edge && npm run perf:search

# vps：5k 行基准 + 索引计划 + API 过滤 / 通配符转义
cd vps && .venv/bin/pytest -q tests/test_search_perf.py
```

脚本失败条件（退出码非 0）：

1. 查询计划未命中预期复合索引；
2. 计划出现 `USE TEMP B-TREE FOR ORDER BY`；
3. 出现无索引的全表扫描；
4. 任一查询 P95 ≥ 300ms。

## 3. 基准记录（2026-10-22，本机）

`edge`（20,000 仓库 / 50 用户 / 12 分类 / 30 标签，Node 22 `node:sqlite`）：

| 查询 | P50 | P95 | 命中索引 |
| --- | --- | --- | --- |
| 用户列表 | 0.81ms | 1.09ms | `idx_my_repositories_user_stars` |
| 分类筛选 | 0.09ms | 0.69ms | `idx_my_repositories_user_category_stars` |
| 关键字检索 | 1.15ms | 1.38ms | `idx_my_repositories_user_stars` |
| 关键字 + 分类 | 0.12ms | 0.43ms | `idx_my_repositories_user_category_stars` |

`vps`（5,000 仓库，pytest 断言 P95 < 300ms）：全量用例 23 passed。

> 本地 SQLite 与 D1 同为 SQLite 引擎，用于验证 SQL / 索引设计；D1 还会叠加网络与调度开销，
> 上线前需按下节在真实 D1 复测。

## 4. 真实 D1 复测（Q3 凭据就绪后）

```bash
cd edge
# 1) 确认迁移已应用
npx wrangler d1 migrations list opensource-factory --remote

# 2) 查看查询计划（把 <user_id> 换成真实用户）
npx wrangler d1 execute opensource-factory --remote --command \
  "EXPLAIN QUERY PLAN SELECT id FROM my_repositories WHERE user_id = '<user_id>' ORDER BY stars DESC, updated_at DESC LIMIT 100"

# 3) 需要时更新统计信息（大表写入后）
npx wrangler d1 execute opensource-factory --remote --command "ANALYZE"
```

验收口径：在真实数据量下，对 `q` / `categoryId` 的典型组合各采样 ≥ 100 次，
接口端到端 P95 < 300ms；若超出，先看计划是否退化为全表扫描或临时排序，再补索引 / 收窄查询。

## 5. 排障

| 现象 | 处理 |
| --- | --- |
| 计划显示 `SCAN my_repositories` | 确认 `0003_search_indexes.sql` 已应用；`PRAGMA index_list('my_repositories')` 核对 |
| 出现 `USE TEMP B-TREE FOR ORDER BY` | 检查 WHERE 是否未带 `user_id`；排序字段是否与索引列顺序一致 |
| 关键字查询慢 | 关键字已截断 100 字符并转义通配符；确认传入的 `q` 不是超长 / 纯 `%` |
| 写入变慢 | 复合索引会增加写放大；当前仅两条，若后续继续加索引需重新评估 |
