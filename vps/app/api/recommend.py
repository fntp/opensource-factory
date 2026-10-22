"""推荐接口：语义查询、推荐生成、每日评估与合格推荐查询。"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MyRepository, Recommendation, RecommendationEvaluationRun
from app.schemas import (
    EvaluationRunListResponse,
    EvaluationRunOut,
    QualifiedListResponse,
    QualifiedRecommendationOut,
    RecommendItem,
    RecommendQuery,
    RecommendResponse,
    TaskEnqueued,
)
from app.services.embedding import get_embedding_service
from app.services.recommendation_eval import get_run, list_qualified, list_runs
from app.services.recommender import build_reason, recommend
from app.tasks.jobs import evaluate_recommendations, generate_recommendations

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
    "/evaluate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    summary="入队：每日推荐评估（质量分 + 匹配度阈值）",
)
async def enqueue_evaluate(
    user_id: str | None = Query(default=None),
    match_threshold: float | None = Query(default=None, ge=0.0, le=1.0),
    quality_threshold: float | None = Query(default=None, ge=0.0, le=1.0),
) -> TaskEnqueued:
    task = evaluate_recommendations.delay(
        user_id=user_id,
        match_threshold=match_threshold,
        quality_threshold=quality_threshold,
    )
    return TaskEnqueued(taskId=task.id)


def _run_out(run: RecommendationEvaluationRun) -> EvaluationRunOut:
    """ORM 运行记录 → API 输出（字段名保持 camelCase）。"""
    return EvaluationRunOut(
        runId=run.id,
        userId=run.user_id,
        status=run.status,
        matchThreshold=run.match_threshold,
        qualityThreshold=run.quality_threshold,
        total=run.total,
        qualified=run.qualified,
        filtered=run.filtered,
        skipped=run.skipped,
        failed=run.failed,
        error=run.error,
        createdAt=run.created_at,
        finishedAt=run.finished_at,
    )


@router.get(
    "/evaluations",
    response_model=EvaluationRunListResponse,
    summary="最近推荐评估运行",
)
def list_evaluation_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> EvaluationRunListResponse:
    runs = list_runs(db, limit=limit)
    return EvaluationRunListResponse(count=len(runs), items=[_run_out(run) for run in runs])


@router.get(
    "/evaluations/{run_id}",
    response_model=EvaluationRunOut,
    summary="推荐评估运行详情",
)
def get_evaluation_run(run_id: str, db: Session = Depends(get_db)) -> EvaluationRunOut:
    run = get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="evaluation run not found")
    return _run_out(run)


def _parse_detail(raw: Optional[str]) -> Optional[dict[str, Any]]:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _qualified_out(row: Recommendation) -> QualifiedRecommendationOut:
    return QualifiedRecommendationOut(
        id=row.id,
        userId=row.user_id,
        repoId=row.repo_id,
        score=row.score,
        matchScore=row.match_score,
        qualityScore=row.quality_score,
        qualityDetail=_parse_detail(row.quality_detail),
        reason=row.reason,
        status=row.status,
        evaluatedAt=row.evaluated_at,
    )


@router.get(
    "/qualified",
    response_model=QualifiedListResponse,
    summary="通过每日评估、等待推送的推荐",
)
def list_qualified_recommendations(
    user_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> QualifiedListResponse:
    rows = list_qualified(db, user_id=user_id, limit=limit)
    return QualifiedListResponse(count=len(rows), items=[_qualified_out(row) for row in rows])
