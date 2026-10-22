-- 0021_telegram_bot.sql — Telegram Bot 查询入口（M8-03）
-- 与 M4-04 的 Telegram 推送共用同一个 Bot：推送是 VPS → Bot API，
-- 查询入口是 Telegram → edge webhook。本迁移只保存「会话 ↔ 用户」绑定关系。
--
-- 安全约定：
-- - 绑定码只存 sha-256 摘要，不落明文；
-- - 一个 Telegram 会话（chat_id）只能绑定一个用户，一个用户也只能绑定一个会话；
-- - 仅支持私聊；群组 / 频道多人共用 chat_id，查询会暴露个人数据，webhook 直接拒绝。

CREATE TABLE IF NOT EXISTS telegram_links (
    chat_id TEXT PRIMARY KEY,                  -- Telegram chat id（私聊 / 群组）
    user_id TEXT NOT NULL,                     -- 对应 users.id
    username TEXT,                             -- Telegram @username（可空）
    linked_at TEXT NOT NULL,                   -- 绑定时间（ISO 8601）
    last_seen_at TEXT                          -- 最近一次命令时间（ISO 8601）
);

-- 一人一聊：同一用户重新绑定新会话时先解绑旧会话
CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_links_user
    ON telegram_links (user_id);

CREATE TABLE IF NOT EXISTS telegram_link_codes (
    code_hash TEXT PRIMARY KEY,                -- sha-256(code)，不存明文
    user_id TEXT NOT NULL,                     -- 生成绑定码的用户
    expires_at TEXT NOT NULL,                  -- 过期时间（ISO 8601，10 分钟）
    created_at TEXT NOT NULL
);

-- 生成新码时清理该用户的旧码；按用户查询便于回收
CREATE INDEX IF NOT EXISTS idx_telegram_link_codes_user
    ON telegram_link_codes (user_id, expires_at DESC);
