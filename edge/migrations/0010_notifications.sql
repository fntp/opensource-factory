-- 0010_notifications.sql — 站内通知中心（M4-02）
-- 通知由 D1 recommendations 中 status='pushed' 的记录惰性物化；
-- 也支持 VPS / 运维通过内部接口写入系统通知。

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'recommendation',   -- recommendation / system
    title TEXT NOT NULL,
    body TEXT,
    url TEXT,
    repo_id TEXT,
    recommendation_id TEXT,                        -- 关联 recommendations.id
    dedupe_key TEXT,                               -- 内部推送幂等键
    score REAL,
    reason TEXT,
    language TEXT,
    stars INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'unread',         -- unread / read / dismissed
    payload TEXT,                                  -- 扩展 JSON（如 basedOn）
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    read_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_notifications_user_status_created
    ON notifications (user_id, status, created_at DESC);

-- 同一用户 + 同一推荐只物化一次（recommendation_id 为 NULL 时 SQLite 允许多行）
CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_user_recommendation
    ON notifications (user_id, recommendation_id);

-- 内部推送按 (user_id, dedupe_key) 幂等
CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_user_dedupe
    ON notifications (user_id, dedupe_key);
