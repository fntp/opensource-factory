-- 0002_incremental_sync.sql — 增量同步字段（REQ-202610-0899 / M1-07）
-- `pushed_at` 记录 GitHub 仓库最近一次代码推送时间，供 VPS 增量同步与前端展示使用。
-- `updated_at` / `synced_at` 已在 0001_init.sql 中预留，无需重复添加。

ALTER TABLE my_repositories ADD COLUMN pushed_at TEXT;
