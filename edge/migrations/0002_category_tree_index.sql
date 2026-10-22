-- 0002_category_tree_index.sql — 分类树查询与同级排序索引（REQ-202610-0901）
CREATE INDEX IF NOT EXISTS idx_categories_parent_sort
    ON categories (parent_id, sort_order, name);
