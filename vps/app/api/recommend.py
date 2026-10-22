"""推荐接口：语义查询（即时计算）、本地推荐查询与推荐生成入队。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Category, MyRepository, Recommendation, TrendingRepository
from app.schemas import (
    RecommendItem,
    RecommendQuery,
    RecommendResponse,
    RecommendationOut,
    TaskEnqueued,
)
from app.services.embedding import get_embedding_service
from app.services.recommend_reason import (
    build_reason_detail,
    build_user_profile,
    parse_based_on,
)
from app.services.recommender import recommend
from app.tasks.jobs import generate_recommendations

router = APIRouter(prefix="/api/recommend", tags=["recommend"])

# 即时查询参与排序的本地仓库上限（防止全表向量化过慢）
_MAX_CANDIDATES = 500


@router.post("/query", response_model=RecommendResponse, summary="语义查询：对本地仓库排序")
def query_recommend(payload: RecommendQuery, db: Session = Depends(get_db)) -> RecommendResponse:
    service = get_embedding_service()
    query_vec = service.encode_one(payload.query)

    repos = list(db.execute(select(MyRepository).limit(_MAX_CANDIDATES)).scalars().all())
    if not repos:
        return RecommendResponse(query=payload.query, count=0, items=[])

    category_names = {
        row.id: row.name for row in db.execute(select(Category)).scalars().all()
    }
    profile = build_user_profile(repos, category_names)

    texts = [
        " ".join(filter(None, [r.name, r.description or "", r.readme_summary or "", r.language or ""]))
        for r in repos
    ]
    vectors = service.encode(texts)
    ranked = recommend(query_vec, [(r.id, vec) for r, vec in zip(repos, vectors)], top_k=payload.top_k)

    by_id = {r.id: r for r in repos}
    items: list[RecommendItem] = []
    for repo_id, score in ranked:
        row = by_id.get(repo_id)
        if row is None:
            continue
        detail = build_reason_detail(row, score, profile)
        items.append(
            RecommendItem(
                repo_id=row.id,
                name=row.name,
                html_url=row.html_url,
                language=row.language or "",
                description=row.description or "",
                score=round(float(score), 4),
                reason=detail.reason,
                based_on=list(detail.based_on),
            )
        )
    return RecommendResponse(query=payload.query, count=len(items), items=items)


@router.get(
    "/list",
    response_model=list[RecommendationOut],
    summary="查询本地已生成的推荐（含中文理由与依据字段）",
)
def list_recommendations(
    user_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[RecommendationOut]:
    stmt = select(Recommendation).order_by(Recommendation.score.desc()).limit(limit)
    if user_id:
        stmt = stmt.where(Recommendation.user_id == user_id)
    rows = list(db.execute(stmt).scalars().all())
    if not rows:
        return []

    repo_ids = {row.repo_id for row in rows}
    trending = {
        item.id: item
        for item in db.execute(
            select(TrendingRepository).where(TrendingRepository.id.in_(repo_ids))
        ).scalars().all()
    }
    mine = {
        item.id: item
        for item in db.execute(
            select(MyRepository).where(MyRepository.id.in_(repo_ids))
        ).scalars().all()
    }

    result: list[RecommendationOut] = []
    for row in rows:
        source = trending.get(row.repo_id) or mine.get(row.repo_id)
        result.append(
            RecommendationOut(
                id=row.id,
                user_id=row.user_id,
                repo_id=row.repo_id,
                name=source.name if source is not None else row.repo_id,
                html_url=getattr(source, "html_url", "") or "",
                description=getattr(source, "description", "") or "",
                language=getattr(source, "language", "") or "",
                tech_stack=getattr(source, "tech_stack", "") or "",
                score=float(row.score or 0),
                reason=row.reason or "",
                based_on=parse_based_on(row.based_on),
                status=row.status or "new",
                created_at=row.created_at,
            )
        )
    return result


@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    summary="入队：推荐生成（/api/tasks/generate-recommendations 的便捷别名）",
)
async def enqueue_generate(
    user_id: str | None = Query(default=None),
    top_k: int = Query(default=20, ge=1, le=100),
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
) -> TaskEnqueued:
    task = generate_recommendations.delay(
        user_id=user_id, top_k=top_k, min_score=min_score
    )
    return TaskEnqueued(taskId=task.id)
