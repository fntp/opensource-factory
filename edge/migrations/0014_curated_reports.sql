-- REQ-202610-0962 每周 / 月度精选报告（M7-03）
-- 报告由 Worker Cron / 页面首次访问生成，按用户 + 周期唯一，重复生成幂等 upsert。
CREATE TABLE IF NOT EXISTS curated_reports (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('weekly', 'monthly')),
    period_start TEXT NOT NULL,                 -- YYYY-MM-DD（UTC，含）
    period_end TEXT NOT NULL,                   -- YYYY-MM-DD（UTC，含）
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    stats TEXT NOT NULL DEFAULT '{}',           -- ReportStats JSON
    sections TEXT NOT NULL DEFAULT '[]',        -- ReportSection[] JSON
    markdown TEXT NOT NULL DEFAULT '',          -- 预渲染 Markdown（下载 / 归档）
    status TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('ready', 'empty')),
    generated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_curated_reports_user_period
    ON curated_reports (user_id, kind, period_start);
CREATE INDEX IF NOT EXISTS idx_curated_reports_user_generated
    ON curated_reports (user_id, generated_at DESC);
