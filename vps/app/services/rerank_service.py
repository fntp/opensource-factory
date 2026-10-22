"""精排预览 / 应用的数据库适配层（REQ-202610-0966 / M7-07）。

`rerank.py` 只负责纯计算；本模块负责：

1. 读取指定用户当前活跃推荐（new / qualified / filtered）；
2. 关联热榜 / 收藏库元数据与已持久化向量；
3. 调用 `rerank_candidates`，可选地把结果写回 `recommendations`。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MyRepository, Recommendation, RepoVector, TrendingRepository
from app.services.recommend_reason import build_user_profile
from app.services.rerank import (
    RerankCandidate,
    RerankWeights,
    build_interest_terms,
    rerank_candidates,
)

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("new", "qualified", "filtered")
_VECTOR_CHUNK = 200


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _chunks(values: Sequence[str], size: int):
    step = max(1, int(size))
    for start in range(0, len(values), step):
        yield list(values[start : start + step])


def _parse_vector(raw: str | None) -> tuple[float, ...]:
    if not raw:
        return ()
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        return ()
    if not isinstance(values, list):
        return ()
    try:
        return tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return ()


def _load_vectors(db: Session, repo_ids: Sequence[str]) -> dict[str, tuple[float, ...]]:
    """读取 repo_id → 向量（同 id 多来源时优先 trending）。"""
    vectors: dict[str, tuple[float, ...]] = {}
    for chunk in _chunks(list(repo_ids), _VECTOR_CHUNK):
        rows = db.execute(
            select(RepoVector).where(RepoVector.repo_id.in_(chunk))
        ).scalars().all()
        for row in rows:
            if row.source == "trending" or row.repo_id not in vectors:
                parsed = _parse_vector(row.vector)
                if parsed:
                    vectors[row.repo_id] = parsed
    return vectors


def _split_tech_stack(raw: str | None) -> tuple[str, ...]:
    return tuple(
        part.strip()
        for part in str(raw or "").replace("，", "/").replace(",", "/").split("/")
        if part.strip()
    )


def _to_candidate(
    row: Recommendation,
    repo: Any,
    vector: tuple[float, ...],
) -> RerankCandidate:
    base_score = float(row.base_score or 0.0)
    if base_score <= 0:
        # 历史数据没有 base_score：退回当前 score（可能已经是精排分）
        base_score = float(row.score or 0.0)
    return RerankCandidate(
        repo_id=row.repo_id,
        base_score=base_score,
        similarity=float(row.match_score or 0.0),
        stars_today=int(getattr(repo, "stars_today", 0) or 0),
        stars=int(getattr(repo, "stars", 0) or 0),
        language=str(getattr(repo, "language", "") or ""),
        tech_stack=_split_tech_stack(getattr(repo, "tech_stack", None)),
        description=str(getattr(repo, "description", "") or ""),
        readme_summary=str(getattr(repo, "readme_summary", "") or ""),
        license_spdx=getattr(repo, "license_spdx", None),
        pushed_at=getattr(repo, "pushed_at", None),
        open_issues_count=int(getattr(repo, "open_issues_count", 0) or 0),
        archived=bool(getattr(repo, "archived", False)),
        disabled=bool(getattr(repo, "disabled", False)),
        health_score=getattr(repo, "health_score", None),
        vector=vector,
    )


def rerank_payload_items(
    items: Sequence[Mapping[str, Any]],
    *,
    top_k: int = 20,
    mmr_lambda: float = 0.75,
    weights: Optional[Mapping[str, float]] = None,
    interest_terms: Sequence[str] = (),
) -> dict[str, Any]:
    """无状态精排：候选由调用方（edge）传入，不读写 VPS 数据库。"""
    candidates: list[RerankCandidate] = []
    meta: dict[str, dict[str, str]] = {}
    for raw in items:
        repo_id = str(raw.get("repoId") or "").strip()
        if not repo_id:
            continue
        pushed_at = raw.get("pushedAt")
        if isinstance(pushed_at, str):
            try:
                pushed_at = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
            except ValueError:
                pushed_at = None
        candidates.append(
            RerankCandidate(
                repo_id=repo_id,
                base_score=float(raw.get("baseScore") or 0.0),
                similarity=float(raw.get("similarity") or 0.0),
                stars_today=int(raw.get("starsToday") or 0),
                stars=int(raw.get("stars") or 0),
                language=str(raw.get("language") or ""),
                tech_stack=tuple(str(item) for item in (raw.get("techStack") or [])),
                description=str(raw.get("description") or ""),
                readme_summary=str(raw.get("readmeSummary") or ""),
                license_spdx=raw.get("licenseSpdx"),
                pushed_at=pushed_at if isinstance(pushed_at, datetime) else None,
                health_score=raw.get("healthScore"),
                vector=tuple(float(value) for value in (raw.get("vector") or [])),
            )
        )
        meta[repo_id] = {
            "name": str(raw.get("name") or ""),
            "htmlUrl": str(raw.get("htmlUrl") or ""),
            "language": str(raw.get("language") or ""),
        }
    result = rerank_candidates(
        candidates,
        weights=weights,
        top_k=top_k,
        mmr_lambda=mmr_lambda,
        interest_terms=set(interest_terms),
    )
    return {
        "status": "ok" if result.items else "empty",
        "generatedAt": _utcnow(),
        "weights": result.weights,
        "mmrLambda": result.mmr_lambda,
        "metrics": result.metrics,
        "items": [
            {**item.to_dict(), **meta.get(item.repo_id, {})} for item in result.items
        ],
        "applied": False,
    }


def rerank_for_user(
    db: Session,
    user_id: str,
    *,
    top_k: int = 20,
    pool_size: int = 100,
    mmr_lambda: float = 0.75,
    min_score: Optional[float] = None,
    weights: Optional[Mapping[str, float]] = None,
    apply: bool = False,
) -> dict[str, Any]:
    """对用户当前活跃推荐做精排；`apply=True` 时写回数据库。"""
    effective_top_k = max(1, min(100, int(top_k)))
    effective_pool = max(effective_top_k, min(500, int(pool_size)))

    rows = list(
        db.execute(
            select(Recommendation)
            .where(
                Recommendation.user_id == user_id,
                Recommendation.status.in_(ACTIVE_STATUSES),
            )
            .order_by(
                Recommendation.base_score.desc(),
                Recommendation.score.desc(),
                Recommendation.created_at.desc(),
            )
            .limit(effective_pool)
        )
        .scalars()
        .all()
    )
    if min_score is not None:
        threshold = max(0.0, min(1.0, float(min_score)))
        rows = [
            row
            for row in rows
            if max(float(row.base_score or 0.0), float(row.score or 0.0)) >= threshold
        ]
    if not rows:
        return {
            "status": "empty",
            "userId": user_id,
            "generatedAt": _utcnow(),
            "weights": RerankWeights.from_mapping(weights).normalized(),
            "mmrLambda": max(0.0, min(1.0, float(mmr_lambda))),
            "metrics": {
                "total": 0,
                "selected": 0,
                "movedUp": 0,
                "movedDown": 0,
                "unchanged": 0,
                "avgRankShift": 0.0,
                "diversityBefore": 0.0,
                "diversityAfter": 0.0,
                "languageCoverage": 0.0,
            },
            "items": [],
            "applied": False,
        }

    repo_ids = [row.repo_id for row in rows]
    trending = {
        row.id: row
        for row in db.execute(
            select(TrendingRepository).where(TrendingRepository.id.in_(repo_ids))
        ).scalars().all()
    }
    mine = {
        row.id: row
        for row in db.execute(
            select(MyRepository).where(MyRepository.id.in_(repo_ids))
        ).scalars().all()
    }
    vectors = _load_vectors(db, repo_ids)
    profile_rows = list(db.execute(select(MyRepository)).scalars().all())
    profile = build_user_profile(profile_rows)
    interest_terms = build_interest_terms(profile.languages, profile.tech_terms)

    candidates: list[RerankCandidate] = []
    for row in rows:
        repo = trending.get(row.repo_id) or mine.get(row.repo_id)
        if repo is None:
            continue
        candidates.append(_to_candidate(row, repo, vectors.get(row.repo_id, ())))

    result = rerank_candidates(
        candidates,
        weights=weights,
        top_k=effective_top_k,
        mmr_lambda=mmr_lambda,
        interest_terms=interest_terms,
    )

    items: list[dict[str, Any]] = []
    by_repo = {row.repo_id: row for row in rows}
    now = _utcnow()
    for item in result.items:
        row = by_repo.get(item.repo_id)
        repo = trending.get(item.repo_id) or mine.get(item.repo_id)
        if row is None:
            continue
        payload = item.to_dict()
        if apply:
            row.score = round(float(item.rerank_score), 6)
            row.base_score = round(float(item.base_score), 6)
            row.rerank_score = round(float(item.rerank_score), 6)
            row.rerank_rank = item.rank_after
            row.rerank_detail = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            row.reranked_at = now
        items.append(
            {
                **payload,
                "name": str(getattr(repo, "name", "") or ""),
                "htmlUrl": str(getattr(repo, "html_url", "") or ""),
                "language": str(getattr(repo, "language", "") or ""),
            }
        )
    if apply and items:
        db.commit()

    return {
        "status": "ok",
        "userId": user_id,
        "generatedAt": now,
        "weights": result.weights,
        "mmrLambda": result.mmr_lambda,
        "metrics": result.metrics,
        "items": items,
        "applied": bool(apply and items),
    }
