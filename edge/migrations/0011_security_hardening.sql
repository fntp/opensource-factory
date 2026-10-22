-- M5-05 接口限流与安全加固
-- 1) rate_limit_counters：D1 固定窗口计数（bucket = scope:identityHash）
-- 2) login_attempts：登录失败 / 成功审计（仅存 IP 哈希）
-- 3) security_events：限流触发、登录锁定等安全事件

CREATE TABLE IF NOT EXISTS rate_limit_counters (
  bucket TEXT PRIMARY KEY,
  window_start INTEGER NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_counters_expires
  ON rate_limit_counters(expires_at);

CREATE TABLE IF NOT EXISTS login_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ip_hash TEXT NOT NULL,
  outcome TEXT NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_created
  ON login_attempts(ip_hash, created_at);

CREATE TABLE IF NOT EXISTS security_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  actor_hash TEXT,
  detail TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_security_events_type_created
  ON security_events(event_type, created_at);
