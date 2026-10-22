-- Agent 工作流（REQ-202610-0968 / M7-09）
-- 每次执行落一条 agent_runs（计划 / 结果可回放），生成的草稿落 agent_drafts。
CREATE TABLE IF NOT EXISTS agent_runs (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  template TEXT NOT NULL CHECK (template IN ('organize', 'draft', 'full')),
  mode TEXT NOT NULL DEFAULT 'preview' CHECK (mode IN ('preview', 'apply')),
  status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('completed', 'failed')),
  threshold REAL NOT NULL DEFAULT 0.75,
  repo_count INTEGER NOT NULL DEFAULT 0,
  plan TEXT NOT NULL DEFAULT '[]',
  result TEXT NOT NULL DEFAULT '{}',
  draft_id TEXT,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user_created
  ON agent_runs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_user_template
  ON agent_runs (user_id, template, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_drafts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  run_id TEXT,
  kind TEXT NOT NULL DEFAULT 'collection_digest',
  title TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'applied', 'discarded')),
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_drafts_user_created
  ON agent_drafts (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_drafts_user_status
  ON agent_drafts (user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_drafts_run
  ON agent_drafts (user_id, run_id);
