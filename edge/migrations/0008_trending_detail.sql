-- 0008_trending_detail.sql — 热榜详情页（REQ-202610-0915 / M2-07）
-- 摘要列由 M2-04 中文摘要任务写入；为空时详情页回退项目描述。
ALTER TABLE trending_repositories ADD COLUMN readme_summary TEXT;

-- 列表 / 详情按平台 + 今日 Star 查询
CREATE INDEX IF NOT EXISTS idx_trending_repositories_platform_stars_today
  ON trending_repositories (platform, stars_today DESC);
