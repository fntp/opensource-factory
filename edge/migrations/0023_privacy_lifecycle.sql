-- 0023_privacy_lifecycle.sql — 数据保留与隐私策略落地（REQ-202610-0983 / M9-06）
-- 仅新增审计表：记录数据主体导出 / 删除与自动保留清理事件。
-- 为降低二次识别风险，actor_hash 存 users.id 的 sha-256，不存明文用户 id；
-- detail 只存计数与策略版本，不存任何个人数据。

CREATE TABLE IF NOT EXISTS privacy_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type IN ('export', 'delete', 'retention_cleanup')),
    actor_hash TEXT,
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_privacy_events_type_created
    ON privacy_events (event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_privacy_events_actor_created
    ON privacy_events (actor_hash, created_at DESC);
