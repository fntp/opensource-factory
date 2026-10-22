"""推荐排序与推荐理由生成。

`recommend`：对候选 (id, 向量) 按余弦相似度降序取 top_k（纯计算，可离线单测）；
`build_reason`：兼容入口，实际委托给 `recommend_reason.build_reason_detail`
（中文理由 + 依据字段，纯规则，不调用 LLM）。
"""
from __future__ import annotations

from typing import Any, Sequence

from app.services.embedding import EmbeddingService
from app.services.recommend_reason import build_reason as _build_reason


def recommend(
    query_vec: Sequence[float],
    candidates: list[tuple[str, Sequence[float]]],
    top_k: int = 10,
) -> list[tuple[str, float]]:
    """按余弦相似度对候选排序，返回 [(id, score), ...]（降序，最多 top_k 条）。"""
    if not query_vec or not candidates or top_k <= 0:
        return []
    scored = [
        (candidate_id, EmbeddingService.cosine(query_vec, vec))
        for candidate_id, vec in candidates
        if vec
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]


def build_reason(repo: Any, score: float) -> str:
    """生成中文推荐理由（兼容旧调用，委托给 recommend_reason）。"""
    return _build_reason(repo, score)
