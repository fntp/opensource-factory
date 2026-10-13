"""推荐接口：语义查询（即时计算）与推荐生成入队。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MyRepository
from app.schemas import RecommendItem, RecommendQuery, RecommendResponse, TaskEnqueued
from app.services.embedding import get_embedding_service
from app.services.recommender import build_reason, recommend
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
        items.append(
            RecommendItem(
                repo_id=row.id,
                name=row.name,
                html_url=row.html_url,
                language=row.language or "",
                description=row.description or "",
                score=round(float(score), 4),
                reason=build_reason(row, score),
            )
        )
    return RecommendResponse(query=payload.query, count=len(items), items=items)


@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    summary="入队：推荐生成（/api/tasks/generate-recommendations 的便捷别名）",
)
async def enqueue_generate(
    user_id: str | None = Query(default=None),
    top_k: int = Query(default=20, ge=1, le=100),
) -> TaskEnqueued:
    task = generate_recommendations.delay(user_id=user_id, top_k=top_k)
    return TaskEnqueued(taskId=task.id)
