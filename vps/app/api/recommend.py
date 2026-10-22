"""推荐接口：语义查询（即时计算）、本地推荐查询、推荐生成入队、质量评估与每日评估。"""
from __future__ import annotations

import json
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Category,
    MyRepository,
    Recommendation,
    RecommendationEvaluationRun,
    TrendingRepository,
)
from app.schemas import (
    EvaluationRunListResponse,
    EvaluationRunOut,
    QualifiedListResponse,
    QualifiedRecommendationOut,
    RecommendEvalReport,
    RecommendEvalRequest,
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
from app.services.recommendation_eval import get_run, list_qualified, list_runs
from app.services.recommendation_quality import evaluate_recommendation_quality
from app.services.recommender import recommend
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
