-- 0002_trending_snapshots.sql — 热榜按日快照（REQ-202610-0913 / M2-05）
-- 主键 (snapshot_date, repo_id)：同一仓库同一天只有一行，重复抓取按主键 upsert。
CREATE TABLE IF NOT EXISTS trending_snapshots (
    snapshot_date DATE NOT NULL,
    repo_id TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'github',
    owner TEXT,
    name TEXT NOT NULL,
    html_url TEXT NOT NULL,
    description TEXT,
    language TEXT,
    tech_stack TEXT,
    stars INTEGER DEFAULT 0,
    stars_today INTEGER DEFAULT 0,
    rank INTEGER DEFAULT 0,
    language_rank INTEGER DEFAULT 0,
    star_delta INTEGER DEFAULT 0,
    rank_delta INTEGER DEFAULT 0,
    appearances INTEGER DEFAULT 1,
    is_new INTEGER DEFAULT 0,
    trend TEXT DEFAULT 'steady',
    trending_pages TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (snapshot_date, repo_id)
);

CREATE INDEX IF NOT EXISTS idx_trending_snapshots_date_rank
    ON trending_snapshots (snapshot_date, rank);
CREATE INDEX IF NOT EXISTS idx_trending_snapshots_repo_date
    ON trending_snapshots (repo_id, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_trending_snapshots_date_language
    ON trending_snapshots (snapshot_date, language);
