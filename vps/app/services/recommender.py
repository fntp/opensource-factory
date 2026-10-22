"""推荐排序、综合打分与推荐理由生成。

- `recommend`：对候选 (id, 向量) 按余弦相似度降序取 top_k（语义查询沿用）；
- `build_profile_vector`：把收藏库向量平均成用户画像；
- `score_candidate` / `rank_candidates`：相似度 + 热榜热度综合打分（M3-05）；
- `build_reason`：基于仓库信息拼接中文推荐理由（模板，不调用 LLM）。

本模块全部为纯计算，不访问数据库 / 网络，便于离线单测。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.services.embedding import EmbeddingService


@dataclass(frozen=True)
class Candidate:
    """待打分的推荐候选。"""

    repo_id: str
    vector: Sequence[float]
    stars_today: int = 0


@dataclass(frozen=True)
class RankedCandidate:
    """打分后的候选（score 为综合得分，similarity 为原始余弦相似度）。"""

    repo_id: str
    score: float
    similarity: float
    heat: float


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


def build_profile_vector(vectors: Sequence[Sequence[float]]) -> list[float]:
    """把多条仓库向量平均成用户画像向量（L2 归一化）。

    空向量会被忽略；维度不一致时返回空列表，由调用方按「画像不可用」降级。
    """
    usable = [vec for vec in vectors if vec]
    if not usable:
        return []
    dim = len(usable[0])
    if any(len(vec) != dim for vec in usable):
        return []
    averaged = [sum(float(vec[i]) for vec in usable) / len(usable) for i in range(dim)]
    return EmbeddingService.normalize(averaged)


def normalized_heat(stars_today: int, max_stars_today: int) -> float:
    """把今日新增 star 数归一化到 0~1（对数尺度，避免头部项目过度压制）。"""
    maximum = max(0, int(max_stars_today or 0))
    if maximum <= 0:
        return 0.0
    stars = max(0, int(stars_today or 0))
    return min(1.0, math.log1p(stars) / math.log1p(maximum))


def score_candidate(
    similarity: float,
    stars_today: int,
    max_stars_today: int,
    *,
    similarity_weight: float = 0.8,
    trending_weight: float = 0.2,
) -> float:
    """综合打分：相似度与热榜热度加权平均，结果裁剪到 0~1。

    权重都为 0（或为负）时退化为纯相似度；相似度为负时按 0 处理。
    """
    sim = max(0.0, min(1.0, float(similarity)))
    heat = normalized_heat(stars_today, max_stars_today)
    sim_weight = max(0.0, float(similarity_weight))
    heat_weight = max(0.0, float(trending_weight))
    total = sim_weight + heat_weight
    if total <= 0:
        return sim
    score = (sim * sim_weight + heat * heat_weight) / total
    return max(0.0, min(1.0, score))


def rank_candidates(
    profile_vec: Sequence[float],
    candidates: Sequence[Candidate],
    *,
    collected_ids: Sequence[str] | set[str] = (),
    min_score: float = 0.0,
    top_k: int = 20,
    similarity_weight: float = 0.8,
    trending_weight: float = 0.2,
) -> list[RankedCandidate]:
    """过滤已收藏 / 低分候选后按综合得分排序。

    - 已收藏的候选直接排除；
    - 最终得分低于 `min_score` 的候选排除；
    - 同分按 repo_id 升序，保证结果稳定可复现。
    """
    if not profile_vec or not candidates or top_k <= 0:
        return []
    collected = set(collected_ids)
    usable = [item for item in candidates if item.repo_id not in collected and item.vector]
    if not usable:
        return []

    max_stars = max(int(item.stars_today or 0) for item in usable)
    threshold = max(0.0, min(1.0, float(min_score)))
    ranked: list[RankedCandidate] = []
    for item in usable:
        similarity = EmbeddingService.cosine(profile_vec, item.vector)
        score = score_candidate(
            similarity,
            item.stars_today,
            max_stars,
            similarity_weight=similarity_weight,
            trending_weight=trending_weight,
        )
        if score + 1e-12 < threshold:
            continue
        ranked.append(
            RankedCandidate(
                repo_id=item.repo_id,
                score=score,
                similarity=similarity,
                heat=normalized_heat(item.stars_today, max_stars),
            )
        )

    ranked.sort(key=lambda item: (-item.score, item.repo_id))
    return ranked[: int(top_k)]


def _field(repo: Any, key: str, default: Any = "") -> Any:
    """兼容 dict / SQLAlchemy 模型 / 任意对象的字段读取。"""
    if isinstance(repo, Mapping):
        value = repo.get(key)
    else:
        value = getattr(repo, key, None)
    return value if value is not None else default


def build_reason(repo: Any, score: float, *, similarity: float | None = None) -> str:
    """生成中文推荐理由：相似度 + 语言 + 技术栈/简介 + 推荐动作。

    `similarity` 不传时沿用 `score`（兼容旧调用）；综合打分场景应显式传入原始相似度，
    避免把热榜热度误写成「兴趣相似度」。
    """
    name = _field(repo, "name") or _field(repo, "id") or "该项目"
    language = _field(repo, "language")
    description = str(_field(repo, "description") or "").strip()
    tech_stack = str(_field(repo, "tech_stack") or "").strip()
    similarity_value = score if similarity is None else similarity
    similarity_value = max(0.0, min(1.0, float(similarity_value)))

    parts: list[str] = [f"与你的兴趣相似度约 {similarity_value:.0%}。"]
    if language:
        parts.append(f"主要使用 {language} 开发；")
    if tech_stack:
        parts.append(f"技术栈涉及 {tech_stack}；")
    if description:
        parts.append(f"项目简介：{description[:60]}。")
    parts.append(f"推荐关注 {name}。")
    return "".join(parts)
