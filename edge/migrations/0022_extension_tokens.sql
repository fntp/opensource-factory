-- 浏览器扩展令牌（REQ-202610-0971 / M8-02）
-- 令牌仅保存 sha-256 摘要；明文只在创建时返回一次。
CREATE TABLE IF NOT EXISTS extension_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    label TEXT,
    token_hash TEXT NOT NULL UNIQUE,
    hint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TEXT,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_extension_tokens_user
    ON extension_tokens (user_id, created_at DESC);
