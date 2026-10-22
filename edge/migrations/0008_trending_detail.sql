-- 0008_trending_detail.sql — 热榜详情页（REQ-202610-0915 / M2-07）
-- 摘要列 readme_summary 已由 0007_trending_summary.sql 添加，这里不再重复 ALTER。

-- 列表 / 详情按平台 + 今日 Star 查询
CREATE INDEX IF NOT EXISTS idx_trending_repositories_platform_stars_today
  ON trending_repositories (platform, stars_today DESC);
