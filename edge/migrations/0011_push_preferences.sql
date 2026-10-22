-- 0011_push_preferences.sql — 推送偏好设置（M4-06）
-- 每个用户一行；未保存时由 edge 返回默认值，不强制落库。
-- VPS 每日推送任务通过 /api/internal/push-preferences 读取。

CREATE TABLE IF NOT EXISTS push_preferences (
    user_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,              -- 0 / 1
    time_of_day TEXT NOT NULL DEFAULT '09:00',       -- HH:MM（用户本地时区）
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',  -- IANA 时区
    min_score REAL NOT NULL DEFAULT 0.35,            -- 匹配度阈值 0~1
    min_quality_score REAL NOT NULL DEFAULT 0.55,    -- 质量分阈值 0~1
    channel_inapp INTEGER NOT NULL DEFAULT 1,        -- 站内通知
    channel_bark INTEGER NOT NULL DEFAULT 0,
    channel_telegram INTEGER NOT NULL DEFAULT 0,
    channel_email INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
