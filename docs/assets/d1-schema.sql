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
    synced_at TEXT
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
    owner TEXT,
    name TEXT,
    description TEXT,
    language TEXT,
    stars INTEGER DEFAULT 0,
    score REAL,
    reason TEXT,
    based_on TEXT,                   -- JSON 数组字符串，如 '["tag:ai","lang:ts"]'
    url TEXT,
    status TEXT DEFAULT 'new',       -- new / saved / dismissed ...
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ── 索引 ────────────────────────────────────────────────────────
CREATE INDEX idx_my_repositories_user_id ON my_repositories (user_id);
CREATE INDEX idx_my_repositories_category_id ON my_repositories (category_id);
CREATE INDEX idx_trending_repositories_stars_today ON trending_repositories (stars_today DESC);
CREATE INDEX idx_sessions_user_id ON sessions (user_id);
CREATE INDEX idx_sessions_expires_at ON sessions (expires_at);
CREATE INDEX idx_recommendations_user_id ON recommendations (user_id);
CREATE INDEX idx_recommendations_score ON recommendations (score DESC);
CREATE INDEX idx_repo_tags_tag_id ON repo_tags (tag_id);
