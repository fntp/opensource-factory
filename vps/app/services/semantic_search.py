"""语义搜索：查询向量化 + 本地向量余弦检索（Vectorize 不可用时的降级路径）。

设计要点：

- 查询向量与仓库向量使用同一个 `EmbeddingService`，模型缺失时统一降级为 hash 向量；
- 本地检索直接读取 M3-02 的 `repo_vectors`，不再即时编码仓库文本；
- 维度不一致 / 非法 JSON / 零向量的条目跳过，不阻断整次检索；
- `hydrate_hits` 负责把命中结果拼成完整项目信息，供内部接口与调试使用；
- 用户维度的权限过滤在 edge 完成（VPS 本地镜像不承担多租户隔离职责）。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MyRepository, RepoVector, TrendingRepository
from app.services.embedding import EmbeddingService, get_embedding_service
from app.services.vector_pipeline import list_runs, run_to_dict

logger = logging.getLogger(__name__)

SOURCES: tuple[str, ...] = ("my", "trending")
SCOPES: tuple[str, ...] = ("my", "trending", "all")


class SearchError(RuntimeError):
    """语义搜索参数 / 状态错误。"""


@dataclass(frozen=True)
class SearchHit:
    """一条向量命中。"""

    source: str
    repo_id: str
    score: float


def normalize_scope(scope: str) -> str:
    value = (scope or "all").strip().lower()
    if value not in SCOPES:
        raise SearchError(f"非法 scope：{scope}（可选 my / trending / all）")
    return value


def sources_for(scope: str) -> list[str]:
    normalized = normalize_scope(scope)
    return list(SOURCES) if normalized == "all" else [normalized]


def normalize_query(query: str) -> str:
    value = " ".join((query or "").split())
    if not value:
        raise SearchError("查询不能为空")
    return value


def _parse_vector(raw: Any) -> Optional[list[float]]:
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(values, list) or not values:
        return None
    try:
        return [float(item) for item in values]
    except (TypeError, ValueError):
        return None


def search_vectors(
    query_vec: Sequence[float],
    rows: Iterable[RepoVector],
    *,
    top_k: int = 10,
    min_score: float = 0.0,
) -> list[SearchHit]:
    """对已持久化向量做余弦排序（纯计算，可离线单测）。"""
    if not query_vec or top_k <= 0:
        return []

    scored: list[SearchHit] = []
    for row in rows:
        vector = _parse_vector(row.vector)
        if vector is None or len(vector) != len(query_vec):
            continue
        score = EmbeddingService.cosine(query_vec, vector)
        if score < min_score:
            continue
        scored.append(SearchHit(source=row.source, repo_id=row.repo_id, score=score))

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:top_k]


def load_vectors(
    db: Session,
    scope: str = "all",
    *,
    max_vectors: Optional[int] = None,
) -> list[RepoVector]:
    """按来源读取本地向量；超出上限时优先保留最近更新的条目。"""
    limit = max(1, int(max_vectors or get_settings().SEARCH_MAX_VECTORS))
    stmt = (
        select(RepoVector)
        .where(RepoVector.source.in_(sources_for(scope)))
        .order_by(RepoVector.updated_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def search_local(
    db: Session,
    query: str,
    *,
    top_k: Optional[int] = None,
    scope: str = "all",
    min_score: Optional[float] = None,
    service: Optional[EmbeddingService] = None,
) -> dict[str, Any]:
    """本地语义检索：查询向量化 + `repo_vectors` 余弦排序。"""
    settings = get_settings()
    normalized_query = normalize_query(query)
    normalized_scope = normalize_scope(scope)
    effective_top_k = max(1, min(settings.SEARCH_MAX_TOP_K, int(top_k or settings.SEARCH_DEFAULT_TOP_K)))
    effective_min_score = (
        float(settings.SEARCH_MIN_SCORE) if min_score is None else float(min_score)
    )

    embedder = service or get_embedding_service()
    query_vec = embedder.encode_one(normalized_query)
    rows = load_vectors(db, normalized_scope)
    hits = search_vectors(
        query_vec,
        rows,
        top_k=effective_top_k,
        min_score=effective_min_score,
    )

    return {
        "query": normalized_query,
        "scope": normalized_scope,
        "count": len(hits),
        "topK": effective_top_k,
        "minScore": effective_min_score,
        "model": embedder.model_name,
        "backend": embedder.backend,
        "dim": len(query_vec),
        "scanned": len(rows),
        "items": [
            {"source": hit.source, "repoId": hit.repo_id, "score": round(hit.score, 6)}
            for hit in hits
        ],
    }


def _build_reason(score: float, language: str, description: str) -> str:
    parts = [f"与查询语义相似度 {max(0.0, min(1.0, score)):.0%}。"]
    if language:
        parts.append(f"主要使用 {language} 开发；")
    if description:
        parts.append(f"项目简介：{description[:80]}。")
    return "".join(parts)


def hydrate_hits(db: Session, hits: Iterable[SearchHit]) -> list[dict[str, Any]]:
    """把向量命中水合为完整项目信息；缺失行（已删除 / 无权限）自动跳过。"""
    items: list[dict[str, Any]] = []
    for hit in hits:
        if hit.source == "my":
            row = db.get(MyRepository, hit.repo_id)
            if row is None:
                continue
            language = row.language or ""
            description = row.description or row.readme_summary or ""
            items.append(
                {
                    "id": row.id,
                    "source": "my",
                    "fullName": row.id,
                    "name": row.name,
                    "description": description,
                    "language": language,
                    "stars": int(row.stars or 0),
                    "starsToday": 0,
                    "url": row.html_url,
                    "score": round(hit.score, 6),
                    "reason": _build_reason(hit.score, language, description),
                }
            )
        elif hit.source == "trending":
            row = db.get(TrendingRepository, hit.repo_id)
            if row is None:
                continue
            language = ""
            description = row.description or ""
            if row.tech_stack:
                description = f"{description}（技术栈：{row.tech_stack}）" if description else row.tech_stack
            items.append(
                {
                    "id": row.id,
                    "source": "trending",
                    "fullName": row.id,
                    "name": row.name,
                    "description": description,
                    "language": language,
                    "stars": 0,
                    "starsToday": int(row.stars_today or 0),
                    "url": row.html_url,
                    "score": round(hit.score, 6),
                    "reason": _build_reason(hit.score, language, description),
                }
            )
    return items


def search_semantic(
    db: Session,
    query: str,
    *,
    top_k: Optional[int] = None,
    scope: str = "all",
    min_score: Optional[float] = None,
) -> dict[str, Any]:
    """本地语义搜索并直接返回水合结果（内部 / 调试 / CLI）。"""
    result = search_local(
        db,
        query,
        top_k=top_k,
        scope=scope,
        min_score=min_score,
    )
    hits = [
        SearchHit(source=item["source"], repo_id=item["repoId"], score=float(item["score"]))
        for item in result["items"]
    ]
    items = hydrate_hits(db, hits)
    return {
        "query": result["query"],
        "scope": result["scope"],
        "count": len(items),
        "model": result["model"],
        "backend": result["backend"],
        "dim": result["dim"],
        "scanned": result["scanned"],
        "items": items,
    }


def get_status(db: Session) -> dict[str, Any]:
    """向量覆盖率与模型分布，附最近向量化运行。"""
    total_vectors = int(db.scalar(select(func.count()).select_from(RepoVector)) or 0)
    by_source = {
        str(source): int(count)
        for source, count in db.execute(
            select(RepoVector.source, func.count()).group_by(RepoVector.source)
        ).all()
    }
    by_model = [
        {"model": str(model), "backend": str(backend), "count": int(count)}
        for model, backend, count in db.execute(
            select(RepoVector.model, RepoVector.backend, func.count())
            .group_by(RepoVector.model, RepoVector.backend)
            .order_by(func.count().desc())
        ).all()
    ]
    dimensions = [
        int(dim)
        for dim in db.execute(
            select(RepoVector.dim).group_by(RepoVector.dim).order_by(RepoVector.dim)
        ).scalars()
        if dim is not None
    ]
    return {
        "totalVectors": total_vectors,
        "bySource": by_source,
        "byModel": by_model,
        "dimensions": dimensions,
        "latestRuns": [run_to_dict(run) for run in list_runs(db, limit=5)],
    }
