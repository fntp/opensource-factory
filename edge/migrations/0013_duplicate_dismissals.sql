-- REQ-202610-0950 重复 / 相似项目检测：按用户记录「已忽略」的重复簇
-- cluster_key 由簇成员（source:repoId）稳定哈希得到；成员变化后会重新出现供复核。

CREATE TABLE IF NOT EXISTS duplicate_dismissals (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    cluster_key TEXT NOT NULL,
    repo_ids TEXT,                    -- JSON 数组，便于排查 / 恢复
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_duplicate_dismissals_unique
    ON duplicate_dismissals (user_id, cluster_key);
CREATE INDEX IF NOT EXISTS idx_duplicate_dismissals_user_time
    ON duplicate_dismissals (user_id, created_at DESC);
