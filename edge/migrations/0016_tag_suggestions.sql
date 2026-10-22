-- 自动打标建议（REQ-202610-0960 / M7-01）
-- 建议与执行分离：生成只写本表，用户采纳后才写 tags / repo_tags。
CREATE TABLE IF NOT EXISTS tag_suggestions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  repo_id TEXT NOT NULL,
  tag_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'domain',
  score REAL NOT NULL DEFAULT 0,
  reason TEXT,
  evidence TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 同一用户 + 仓库 + 标签只保留一条建议（重复生成走 upsert）
CREATE UNIQUE INDEX IF NOT EXISTS idx_tag_suggestions_unique
  ON tag_suggestions (user_id, repo_id, normalized_name);

-- 列表默认按状态过滤、更新时间倒序
CREATE INDEX IF NOT EXISTS idx_tag_suggestions_list
  ON tag_suggestions (user_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_tag_suggestions_repo
  ON tag_suggestions (user_id, repo_id, status);
