-- REQ-202610-0925 推荐页闭环：推荐快照补充 repo_id / updated_at，并新增反馈明细表

ALTER TABLE recommendations ADD COLUMN repo_id TEXT;
ALTER TABLE recommendations ADD COLUMN updated_at DATETIME;

CREATE TABLE IF NOT EXISTS recommendation_feedback (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    recommendation_id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('saved', 'dismissed', 'clicked')),
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_recommendation_feedback_unique
    ON recommendation_feedback (user_id, recommendation_id, action);
CREATE INDEX IF NOT EXISTS idx_recommendation_feedback_user_time
    ON recommendation_feedback (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_recommendation_feedback_user_repo
    ON recommendation_feedback (user_id, repo_id);
