"""相似项目推荐（向量近邻「看了又看」，M6-02）。

以某个仓库自身的向量为查询向量，在本地 `repo_vectors` 中做余弦近邻检索：

- 候选默认覆盖收藏库 + 热榜，始终排除种子自身；
- 只比较 `model + dim` 一致的向量，避免跨模型 / 跨维度余弦失真；
- `exclude_saved=True` 时排除收藏库（推荐用户尚未收藏的项目）；
- 纯本地计算，不依赖 Vectorize；权限过滤与水合由 edge 按当前用户完成。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MyRepository, RepoVector, TrendingRepository
from app.services.embedding import EmbeddingService
from app.services.semantic_search import (
    SearchHit,
    _parse_vector,
    hydrate_hits,
    normalize_scope,
    search_vectors,
    sources_for,
)

logger = logging.getLogger(__name__)

SOURCES: tuple[str, ...] = ("my", "trending")


class SimilarError(RuntimeError):
    """相似推荐参数 / 种子状态错误。"""


class SeedNotFound(SimilarError):
    """种子仓库在本地镜像中不存在。"""


class SeedVectorMissing(SimilarError):
    """种子仓库存在但尚未向量化。"""


def normalize_source(source: str) -> str:
    value = (source or "").strip().lower()
    if value not in SOURCES:
        raise SimilarError(f"非法 source：{source}（可选 my / trending）")
    return value


def _seed_meta(db: Session, source: str, repo_id: str) -> dict[str, Any]:
    """读取种子仓库的展示信息；缺失时返回最小信息。"""
    if source == "my":
        row = db.get(MyRepository, repo_id)
        if row is not None:
            return {
                "source": source,
                "repoId": repo_id,
                "name": row.name,
                "description": row.description or row.readme_summary or "",
                "language": row.language or "",
            }
    else:
        row = db.get(TrendingRepository, repo_id)
        if row is not None:
            return {
                "source": source,
                "repoId": repo_id,
                "name": row.name,
                "description": row.description or "",
                "language": row.language or "",
            }
    return {
        "source": source,
        "repoId": repo_id,
        "name": repo_id.split("/")[-1],
        "description": "",
        "language": "",
    }


def _repo_exists(db: Session, source: str, repo_id: str) -> bool:
    if source == "my":
        return db.get(MyRepository, repo_id) is not None
    return db.get(TrendingRepository, repo_id) is not None


def find_similar(
    db: Session,
    source: str,
    repo_id: str,
    *,
    top_k: Optional[int] = None,
    scope: str = "all",
    min_score: Optional[float] = None,
    exclude_saved: bool = False,
    max_vectors: Optional[int] = None,
) -> dict[str, Any]:
    """返回相似项目命中（未水合），按余弦相似度降序。"""
    settings = get_settings()
    normalized_source = normalize_source(source)
    normalized_repo_id = (repo_id or "").strip()
    if not normalized_repo_id:
        raise SimilarError("repoId 不能为空")
    normalized_scope = normalize_scope(scope)
    effective_top_k = max(
        1, min(settings.SEARCH_MAX_TOP_K, int(top_k or settings.SEARCH_DEFAULT_TOP_K))
    )
    effective_min_score = (
        float(settings.SEARCH_MIN_SCORE) if min_score is None else float(min_score)
    )
    limit = max(1, int(max_vectors or settings.SEARCH_MAX_VECTORS))

    seed = db.get(RepoVector, {"source": normalized_source, "repo_id": normalized_repo_id})
    if seed is None:
        if _repo_exists(db, normalized_source, normalized_repo_id):
            raise SeedVectorMissing(f"种子仓库尚未向量化：{normalized_source}/{normalized_repo_id}")
        raise SeedNotFound(f"种子仓库不存在：{normalized_source}/{normalized_repo_id}")

    seed_vec = _parse_vector(seed.vector)
    if not seed_vec or len(seed_vec) != int(seed.dim or 0):
        raise SeedVectorMissing(f"种子向量不可用：{normalized_source}/{normalized_repo_id}")

    stmt = (
        select(RepoVector)
        .where(
            RepoVector.source.in_(sources_for(normalized_scope)),
            RepoVector.model == seed.model,
            RepoVector.dim == seed.dim,
            ~(
                (RepoVector.source == normalized_source)
                & (RepoVector.repo_id == normalized_repo_id)
            ),
        )
        .order_by(RepoVector.updated_at.desc())
        .limit(limit)
    )
    if exclude_saved:
        stmt = stmt.where(RepoVector.source != "my")
    rows = list(db.execute(stmt).scalars().all())

    hits = search_vectors(
        seed_vec,
        rows,
        top_k=effective_top_k,
        min_score=effective_min_score,
    )
    seed_meta = _seed_meta(db, normalized_source, normalized_repo_id)
    return {
        "source": normalized_source,
        "repoId": normalized_repo_id,
        "scope": normalized_scope,
        "count": len(hits),
        "topK": effective_top_k,
        "minScore": effective_min_score,
        "excludeSaved": bool(exclude_saved),
        "model": seed.model,
        "backend": seed.backend,
        "dim": int(seed.dim or len(seed_vec)),
        "scanned": len(rows),
        "seed": seed_meta,
        "items": [
            {"source": hit.source, "repoId": hit.repo_id, "score": round(hit.score, 6)}
            for hit in hits
        ],
    }


def similar_repositories(
    db: Session,
    source: str,
    repo_id: str,
    *,
    top_k: Optional[int] = None,
    scope: str = "all",
    min_score: Optional[float] = None,
    exclude_saved: bool = False,
) -> dict[str, Any]:
    """相似推荐 + 完整项目信息水合（内部调试 / CLI 使用）。"""
    result = find_similar(
        db,
        source,
        repo_id,
        top_k=top_k,
        scope=scope,
        min_score=min_score,
        exclude_saved=exclude_saved,
    )
    hits = [
        SearchHit(source=item["source"], repo_id=item["repoId"], score=float(item["score"]))
        for item in result["items"]
    ]
    seed_name = result["seed"].get("name") or result["repoId"]
    result["items"] = hydrate_hits(
        db,
        hits,
        reason_prefix=f"与「{seed_name}」语义相似度",
    )
    return result


def similarity_score(a: list[float], b: list[float]) -> float:
    """便捷函数：供测试 / 调试直接计算余弦相似度。"""
    return EmbeddingService.cosine(a, b)
