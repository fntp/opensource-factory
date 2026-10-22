-- REQ-202610-0961 自动分类建议（按业务线）
-- 建议按「用户 + 仓库 + 分类名」唯一：重复生成只刷新分数与理由，不覆盖已采纳 / 已忽略状态。

CREATE TABLE IF NOT EXISTS category_suggestions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    category_name TEXT NOT NULL,
    business_line TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    reason TEXT,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending / accepted / dismissed
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_category_suggestions_unique
    ON category_suggestions (user_id, repo_id, category_name);
CREATE INDEX IF NOT EXISTS idx_category_suggestions_user_status
    ON category_suggestions (user_id, status, score DESC);
CREATE INDEX IF NOT EXISTS idx_category_suggestions_repo
    ON category_suggestions (user_id, repo_id);
