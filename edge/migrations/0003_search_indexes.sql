-- 0003_search_indexes.sql — 仓库检索索引（REQ-202610-0904）
-- 编号说明：0002 已被并行需求 REQ-202610-0899（增量同步）占用，本迁移使用 0003 避免合并冲突。
--
-- 查询形态（edge GET /api/repos）：
--   WHERE user_id = ? [AND category_id = ?] [AND (name/id/description LIKE ?)]
--   ORDER BY stars DESC, updated_at DESC
--   LIMIT ? OFFSET ?
-- 复合索引让「用户（+分类）」过滤与 Star 排序在同一条索引上完成，
-- 避免全表扫描与 USE TEMP B-TREE FOR ORDER BY。
-- 注意：`LIKE '%q%'` 本身无法走 B-Tree 索引，索引的作用是先收敛到单用户分区。

-- 单列 (user_id) 索引被下面的复合索引最左前缀完全覆盖，删除以降低写放大。
DROP INDEX IF EXISTS idx_my_repositories_user_id;

CREATE INDEX IF NOT EXISTS idx_my_repositories_user_stars
    ON my_repositories (user_id, stars DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_my_repositories_user_category_stars
    ON my_repositories (user_id, category_id, stars DESC, updated_at DESC);
