-- 0007_trending_summary.sql — 热榜仓库中文摘要列（REQ-202610-0912 / M2-04）
-- VPS 摘要任务通过 POST /api/trending/summaries 回写；M2-07 热榜详情页直接读取。
ALTER TABLE trending_repositories ADD COLUMN readme_summary TEXT;
