-- 标签引用计数维护（REQ-202610-0902）
-- tags.count 是冗余计数；在 repo_tags 增删改后按实际关联数重算，
-- 保证仓库打标 / 同步 / 手工 SQL 等任何写入路径都不会让计数漂移。

CREATE TRIGGER IF NOT EXISTS trg_repo_tags_count_insert
AFTER INSERT ON repo_tags
BEGIN
  UPDATE tags
     SET count = (SELECT COUNT(*) FROM repo_tags WHERE tag_id = NEW.tag_id)
   WHERE id = NEW.tag_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_repo_tags_count_delete
AFTER DELETE ON repo_tags
BEGIN
  UPDATE tags
     SET count = (SELECT COUNT(*) FROM repo_tags WHERE tag_id = OLD.tag_id)
   WHERE id = OLD.tag_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_repo_tags_count_update
AFTER UPDATE OF tag_id ON repo_tags
BEGIN
  UPDATE tags
     SET count = (SELECT COUNT(*) FROM repo_tags WHERE tag_id = OLD.tag_id)
   WHERE id = OLD.tag_id;
  UPDATE tags
     SET count = (SELECT COUNT(*) FROM repo_tags WHERE tag_id = NEW.tag_id)
   WHERE id = NEW.tag_id;
END;
