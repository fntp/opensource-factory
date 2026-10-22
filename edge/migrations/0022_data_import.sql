-- 0022_data_import.sql — 外部收藏导入记录（M9-03 / REQ-202610-0980）
--
-- 导入本身直接写 my_repositories / categories / tags / repo_tags，
-- 本表只保存每次执行的来源格式与计数，供 admin 展示最近导入历史。
-- 不保存导入文件内容，避免把用户书签 / 描述原文长期留存在审计表里。

CREATE TABLE IF NOT EXISTS import_runs (
    id TEXT PRIMARY KEY,                       -- imp_<timestamp>_<random>
    user_id TEXT NOT NULL,                     -- users.id
    source_format TEXT NOT NULL,               -- json | csv | html
    status TEXT NOT NULL DEFAULT 'completed',  -- completed | failed
    total INTEGER NOT NULL DEFAULT 0,          -- 去重后的有效条目数
    imported INTEGER NOT NULL DEFAULT 0,       -- 新增仓库数
    updated INTEGER NOT NULL DEFAULT 0,        -- 更新本人已有仓库数
    skipped INTEGER NOT NULL DEFAULT 0,        -- 冲突 + 无效
    conflicts INTEGER NOT NULL DEFAULT 0,      -- 已被其他用户收藏
    invalid INTEGER NOT NULL DEFAULT 0,        -- 无法解析 / 非仓库链接
    categories_created INTEGER NOT NULL DEFAULT 0,
    tags_created INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_import_runs_user
    ON import_runs (user_id, created_at DESC);
