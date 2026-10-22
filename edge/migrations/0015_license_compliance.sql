-- REQ-202610-0953 License 识别与合规提示（M6-06）
-- 识别优先级：GitHub API license → README 启发式 → unknown；
-- license_source 记录来源（github / readme / none），分类与风险在读取时由目录映射。

ALTER TABLE my_repositories ADD COLUMN license_spdx TEXT;
ALTER TABLE my_repositories ADD COLUMN license_name TEXT;
ALTER TABLE my_repositories ADD COLUMN license_source TEXT;
ALTER TABLE my_repositories ADD COLUMN license_checked_at DATETIME;

ALTER TABLE trending_repositories ADD COLUMN license_spdx TEXT;
ALTER TABLE trending_repositories ADD COLUMN license_name TEXT;
ALTER TABLE trending_repositories ADD COLUMN license_source TEXT;
ALTER TABLE trending_repositories ADD COLUMN license_checked_at DATETIME;

CREATE INDEX IF NOT EXISTS idx_my_repositories_license_spdx
    ON my_repositories (license_spdx);
CREATE INDEX IF NOT EXISTS idx_trending_repositories_license_spdx
    ON trending_repositories (license_spdx);
