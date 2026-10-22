-- 0002_sync_tasks.sql — 同步任务表（REQ-202610-0900 / M1-08）
-- 说明：记录 edge 入队到 VPS 的同步任务，供 admin 查询进度与历史。

CREATE TABLE sync_tasks (
    id TEXT PRIMARY KEY,             -- VPS / Celery 返回的 taskId
    user_id TEXT,                    -- 触发用户（admin 仅能查看自己的任务）
    task_type TEXT NOT NULL DEFAULT 'sync',  -- sync / sync-starred / ...
    status TEXT NOT NULL DEFAULT 'pending',  -- pending / started / progress / success / failure / unknown
    progress TEXT,                   -- 进度快照 JSON（camelCase）
    result TEXT,                     -- 结果 JSON
    error TEXT,                      -- 错误摘要
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME
);

CREATE INDEX idx_sync_tasks_user_created ON sync_tasks (user_id, created_at DESC);
CREATE INDEX idx_sync_tasks_status ON sync_tasks (status);
