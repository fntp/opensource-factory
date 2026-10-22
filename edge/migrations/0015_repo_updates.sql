-- 0015_repo_updates.sql — 收藏项目更新提醒（M7-04）
-- VPS 每日扫描 GitHub Release / Tag，经内部接口回写后按仓库归属扇出到收藏用户。
-- `repo_updates` 为事实表；站内通知中心同步写入 type='repo_update' 的提醒。

CREATE TABLE IF NOT EXISTS repo_updates (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    repo_name TEXT,
    repo_url TEXT,
    type TEXT NOT NULL DEFAULT 'release',        -- release / major
    version TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    published_at DATETIME,
    detected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'unread',       -- unread / read / dismissed
    read_at DATETIME,
    payload TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 同一用户 + 同一仓库 + 同一版本只提醒一次（重复扫描幂等）
CREATE UNIQUE INDEX IF NOT EXISTS idx_repo_updates_user_repo_version
    ON repo_updates (user_id, repo_id, version);

-- 列表与未读统计
CREATE INDEX IF NOT EXISTS idx_repo_updates_user_status_detected
    ON repo_updates (user_id, status, detected_at DESC);

-- 按类型筛选（重大变更 / 新版本）
CREATE INDEX IF NOT EXISTS idx_repo_updates_user_type_detected
    ON repo_updates (user_id, type, detected_at DESC);
