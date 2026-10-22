-- ============================================================
-- 开源项目工厂 · Cloudflare D1 数据库 Schema（数据资产副本）
-- 来源与同步：edge/migrations/0001_init.sql —— 以迁移文件为准，两处必须同步修改
-- 内容说明：前三节为需求原文核心表（表名/列名保持不变，仅追加扩展列），
--           其余为边缘 API 所需的扩展表；索引见文末。
-- ============================================================

-- ── 我的仓库（用户同步的个人仓库资产）───────────────────────────
CREATE TABLE my_repositories (
    id TEXT PRIMARY KEY,             -- "owner/repo"
    platform TEXT NOT NULL,          -- 'github' 或 'gitee'
    name TEXT NOT NULL,
    description TEXT,
    html_url TEXT NOT NULL,
    stars INTEGER DEFAULT 0,
    language TEXT,
    readme_summary TEXT,
    category_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- 追加列（API 需要）
    user_id TEXT,
    owner TEXT,
    forks INTEGER DEFAULT 0,
    updated_at TEXT,
    synced_at TEXT,
    -- 项目健康度（REQ-202610-0952 / M6-05）
    pushed_at DATETIME,                  -- GitHub pushed_at：最后提交时间
    open_issues_count INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    disabled INTEGER NOT NULL DEFAULT 0,
    health_status TEXT,                  -- active | attention | stale | archived | unknown
    health_score INTEGER,                -- 0-100
    health_checked_at DATETIME
);

-- ── 今日趋势仓库（爬虫写入）─────────────────────────────────────
CREATE TABLE trending_repositories (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    name TEXT NOT NULL,
    html_url TEXT NOT NULL,
    stars_today INTEGER,
    description TEXT,
    tech_stack TEXT,
    crawled_at DATE DEFAULT (CURRENT_DATE),
    -- 追加列（API 需要）
    owner TEXT,
    language TEXT,
    stars INTEGER DEFAULT 0,
    readme_summary TEXT
);

-- ── 分类 ────────────────────────────────────────────────────────
CREATE TABLE categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id TEXT,
    -- 追加列（API 需要）
    description TEXT,
    sort_order INTEGER
);

-- ── 用户（GitHub OAuth）─────────────────────────────────────────
CREATE TABLE users (
    id TEXT PRIMARY KEY,             -- GitHub 数字 id 的字符串形式
    login TEXT NOT NULL,
    name TEXT,
    email TEXT,
    avatar_url TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ── 会话（id 为随机 token 的 sha-256 十六进制摘要）──────────────
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,             -- token hash
    user_id TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL
);

-- ── 标签 ────────────────────────────────────────────────────────
CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    count INTEGER DEFAULT 0
);

-- ── 仓库 ↔ 标签 关联 ────────────────────────────────────────────
CREATE TABLE repo_tags (
    repo_id TEXT NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (repo_id, tag_id)
);

-- ── 智能推荐 ────────────────────────────────────────────────────
CREATE TABLE recommendations (
    id TEXT PRIMARY KEY,
    user_id TEXT,                    -- NULL 表示全局推荐
    repo_id TEXT,                    -- owner/name（REQ-202610-0925）
    owner TEXT,
    name TEXT,
    description TEXT,
    language TEXT,
    stars INTEGER DEFAULT 0,
    score REAL,
    reason TEXT,
    based_on TEXT,                   -- JSON 数组字符串，如 '["tag:ai","lang:ts"]'
    url TEXT,
    status TEXT DEFAULT 'new',       -- new / saved / dismissed / pushed
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);

-- 推荐反馈明细（收藏 / 忽略 / 点击），(user_id, recommendation_id, action) 唯一
CREATE TABLE recommendation_feedback (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    recommendation_id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('saved', 'dismissed', 'clicked')),
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ── 热榜按日快照（REQ-202610-0913 / M2-05）──────────────────────
-- 同一仓库同一天只有一行；趋势字段对比上一有效快照计算。
CREATE TABLE IF NOT EXISTS trending_snapshots (
    snapshot_date DATE NOT NULL,
    repo_id TEXT NOT NULL,               -- owner/repo
    platform TEXT NOT NULL DEFAULT 'github',
    owner TEXT,
    name TEXT NOT NULL,
    html_url TEXT NOT NULL,
    description TEXT,
    language TEXT,
    tech_stack TEXT,
    stars INTEGER DEFAULT 0,
    stars_today INTEGER DEFAULT 0,
    rank INTEGER DEFAULT 0,              -- 全平台综合排名（1 起）
    language_rank INTEGER DEFAULT 0,     -- 同语言内排名
    star_delta INTEGER DEFAULT 0,        -- 对比上一快照的总 Star 增量
    rank_delta INTEGER DEFAULT 0,        -- 正数=排名上升
    appearances INTEGER DEFAULT 1,       -- 连续上榜天数
    is_new INTEGER DEFAULT 0,
    trend TEXT DEFAULT 'steady',         -- new / up / down / steady
    trending_pages TEXT,                 -- JSON 数组，来源语言页
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (snapshot_date, repo_id)
);

-- ── 索引 ────────────────────────────────────────────────────────
CREATE INDEX idx_my_repositories_user_id ON my_repositories (user_id);
CREATE INDEX idx_my_repositories_category_id ON my_repositories (category_id);
CREATE INDEX idx_my_repositories_health ON my_repositories (user_id, health_status);
CREATE INDEX idx_trending_repositories_stars_today ON trending_repositories (stars_today DESC);
CREATE INDEX idx_trending_snapshots_date_rank ON trending_snapshots (snapshot_date, rank);
CREATE INDEX idx_trending_snapshots_repo_date ON trending_snapshots (repo_id, snapshot_date);
CREATE INDEX idx_trending_snapshots_date_language ON trending_snapshots (snapshot_date, language);
CREATE INDEX idx_trending_repositories_platform_stars_today ON trending_repositories (platform, stars_today DESC);
CREATE INDEX idx_sessions_user_id ON sessions (user_id);
CREATE INDEX idx_sessions_expires_at ON sessions (expires_at);
CREATE INDEX idx_recommendations_user_id ON recommendations (user_id);
CREATE INDEX idx_recommendations_score ON recommendations (score DESC);
CREATE INDEX idx_repo_tags_tag_id ON repo_tags (tag_id);
CREATE UNIQUE INDEX idx_recommendation_feedback_unique
    ON recommendation_feedback (user_id, recommendation_id, action);
CREATE INDEX idx_recommendation_feedback_user_time
    ON recommendation_feedback (user_id, created_at DESC);
CREATE INDEX idx_recommendation_feedback_user_repo
    ON recommendation_feedback (user_id, repo_id);
