-- REQ-202610-0966 Rerank 精排（M7-07）
-- 保留粗排分 / 精排分 / 精排名次与可解释明细，供推荐列表按精排分排序与前端展示。

ALTER TABLE recommendations ADD COLUMN base_score REAL;
ALTER TABLE recommendations ADD COLUMN rerank_score REAL;
ALTER TABLE recommendations ADD COLUMN rerank_rank INTEGER;
ALTER TABLE recommendations ADD COLUMN rerank_detail TEXT;
ALTER TABLE recommendations ADD COLUMN reranked_at DATETIME;

CREATE INDEX IF NOT EXISTS idx_recommendations_rerank_score
    ON recommendations (rerank_score DESC);
