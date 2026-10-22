"""推荐接口：语义查询（即时计算）、推荐生成入队与质量评估。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MyRepository
from app.schemas import (
    RecommendEvalReport,
    RecommendEvalRequest,
    RecommendItem,
    RecommendQuery,
    RecommendResponse,
    TaskEnqueued,
)
from app.services.embedding import get_embedding_service
from app.services.recommendation_eval import evaluate_recommendation_quality
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
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
) -> TaskEnqueued:
    task = generate_recommendations.delay(
        user_id=user_id, top_k=top_k, min_score=min_score
    )
    return TaskEnqueued(taskId=task.id)


@router.post(
    "/eval",
    response_model=RecommendEvalReport,
    summary="推荐质量评估与阈值调优（抽样评估集）",
)
def evaluate_recommend(
    payload: RecommendEvalRequest,
    db: Session = Depends(get_db),
) -> RecommendEvalReport:
    """离线评估推荐排序质量，并给出 min_score / 权重的调参建议。

    评估基于收藏库留出集与热榜负样本，不修改推荐结果与运行配置；
    数据不足时返回 `status=insufficient_data`。
    """
    report = evaluate_recommendation_quality(
        db,
        user_id=payload.userId,
        sample_size=payload.sampleSize,
        top_k=payload.topK,
        holdout_ratio=payload.holdoutRatio,
        negatives_per_positive=payload.negativesPerPositive,
        seed=payload.seed,
    )
    return RecommendEvalReport.model_validate(report)
