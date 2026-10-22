-- 0003_repo_filter_indexes.sql — 仓库列表组合筛选 / 排序索引（REQ-202610-0903）
-- D1 / SQLite：以 user_id 为前缀，覆盖按 Star / 更新时间 / 语言 / 分类的常用组合。

CREATE INDEX IF NOT EXISTS idx_my_repositories_user_stars
  ON my_repositories (user_id, stars DESC);

CREATE INDEX IF NOT EXISTS idx_my_repositories_user_updated
  ON my_repositories (user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_my_repositories_user_language
  ON my_repositories (user_id, language);

CREATE INDEX IF NOT EXISTS idx_my_repositories_user_category
  ON my_repositories (user_id, category_id);
