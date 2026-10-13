"""推荐排序与推荐理由生成。

`recommend`：对候选 (id, 向量) 按余弦相似度降序取 top_k（纯计算，可离线单测）；
`build_reason`：基于仓库信息拼接中文推荐理由（模板，不调用 LLM）。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.services.embedding import EmbeddingService


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


def _field(repo: Any, key: str, default: Any = "") -> Any:
    """兼容 dict / SQLAlchemy 模型 / 任意对象的字段读取。"""
    if isinstance(repo, Mapping):
        value = repo.get(key)
    else:
        value = getattr(repo, key, None)
    return value if value is not None else default


def build_reason(repo: Any, score: float) -> str:
    """生成中文推荐理由：相似度 + 语言 + 技术栈/简介 + 推荐动作。"""
    name = _field(repo, "name") or _field(repo, "id") or "该项目"
    language = _field(repo, "language")
    description = str(_field(repo, "description") or "").strip()
    tech_stack = str(_field(repo, "tech_stack") or "").strip()
    similarity = max(0.0, min(1.0, float(score)))

    parts: list[str] = [f"与你的兴趣相似度约 {similarity:.0%}。"]
    if language:
        parts.append(f"主要使用 {language} 开发；")
    if tech_stack:
        parts.append(f"技术栈涉及 {tech_stack}；")
    if description:
        parts.append(f"项目简介：{description[:60]}。")
    parts.append(f"推荐关注 {name}。")
    return "".join(parts)
