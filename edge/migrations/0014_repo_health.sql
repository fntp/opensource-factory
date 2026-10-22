-- REQ-202610-0952 项目健康度追踪（M6-05）：最后提交 / issue 活跃 / 归档标记
-- 元数据由 VPS 每日任务通过 GitHub API 刷新并回写；health_* 为最近一次计算结果。

ALTER TABLE my_repositories ADD COLUMN pushed_at DATETIME;
ALTER TABLE my_repositories ADD COLUMN open_issues_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE my_repositories ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
ALTER TABLE my_repositories ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE my_repositories ADD COLUMN health_status TEXT;
ALTER TABLE my_repositories ADD COLUMN health_score INTEGER;
ALTER TABLE my_repositories ADD COLUMN health_checked_at DATETIME;

CREATE INDEX IF NOT EXISTS idx_my_repositories_health
    ON my_repositories (user_id, health_status);
