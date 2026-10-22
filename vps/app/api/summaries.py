"""摘要质量抽检接口（REQ-202610-0912 / M2-04）。

- `GET  /api/summaries/quality/samples`：样本列表（按状态 / 来源 / 批次过滤）
- `POST /api/summaries/quality/samples/{id}/review`：人工复核
- `GET  /api/summaries/quality/stats`：质量统计
- `POST /api/summaries/quality/sample-existing`：对存量摘要补抽样

所有接口沿用内部鉴权：配置 `INTERNAL_TOKEN` 后必须携带 `X-Internal-Token`。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.security import require_internal_token
from app.db import get_db
from app.models import SummaryQualitySample
from app.schemas import (
    QualityReviewIn,
    QualitySampleExistingIn,
    QualitySampleList,
    QualitySampleOut,
    QualityStatsOut,
)
from app.services.summary_quality import sample_existing_summaries

router = APIRouter(
    prefix="/api/summaries/quality",
    tags=["summaries"],
    dependencies=[Depends(require_internal_token)],
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_checks(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


def _sample_out(sample: SummaryQualitySample) -> QualitySampleOut:
    return QualitySampleOut(
        id=sample.id,
        batchId=sample.batch_id,
        repoId=sample.repo_id,
        repoSource=sample.repo_source,
        summary=sample.summary,
        source=sample.source,
        model=sample.model,
        maxChars=sample.max_chars,
        score=sample.score,
        verdict=sample.verdict,
        checks=_parse_checks(sample.checks),
        status=sample.status,
        reviewer=sample.reviewer,
        reviewNote=sample.review_note,
        reviewedAt=sample.reviewed_at,
        createdAt=sample.created_at,
    )


@router.get("/samples", response_model=QualitySampleList, summary="抽检样本列表")
def list_samples(
    db: Session = Depends(get_db),
    status_filter: str = Query(default="all", alias="status", pattern="^(all|pending|passed|failed)$"),
    repo_source: str = Query(default="all", alias="repoSource", pattern="^(all|my|trending)$"),
    batch_id: str | None = Query(default=None, alias="batchId"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> QualitySampleList:
    conditions = []
    if status_filter != "all":
        conditions.append(SummaryQualitySample.status == status_filter)
    if repo_source != "all":
        conditions.append(SummaryQualitySample.repo_source == repo_source)
    if batch_id:
        conditions.append(SummaryQualitySample.batch_id == batch_id)

    count_stmt = select(func.count()).select_from(SummaryQualitySample)
    list_stmt = select(SummaryQualitySample)
    for condition in conditions:
        count_stmt = count_stmt.where(condition)
        list_stmt = list_stmt.where(condition)

    total = int(db.execute(count_stmt).scalar() or 0)
    rows = list(
        db.execute(
            list_stmt.order_by(
                SummaryQualitySample.created_at.desc(), SummaryQualitySample.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return QualitySampleList(total=total, items=[_sample_out(row) for row in rows])


@router.post(
    "/samples/{sample_id}/review",
    response_model=QualitySampleOut,
    summary="人工复核抽检样本",
)
def review_sample(
    sample_id: str,
    payload: QualityReviewIn,
    db: Session = Depends(get_db),
) -> QualitySampleOut:
    sample = db.get(SummaryQualitySample, sample_id)
    if sample is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sample not found")
    sample.status = payload.result
    sample.reviewer = (payload.reviewer or "").strip() or None
    sample.review_note = (payload.note or "").strip() or None
    sample.reviewed_at = _utcnow()
    db.commit()
    db.refresh(sample)
    return _sample_out(sample)


@router.get("/stats", response_model=QualityStatsOut, summary="摘要质量统计")
def quality_stats(db: Session = Depends(get_db)) -> QualityStatsOut:
    status_rows = db.execute(
        select(SummaryQualitySample.status, func.count()).group_by(SummaryQualitySample.status)
    ).all()
    counts = {str(row[0]): int(row[1]) for row in status_rows}
    total = sum(counts.values())
    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0)
    reviewed = passed + failed
    avg_score = float(
        db.execute(select(func.avg(SummaryQualitySample.score))).scalar() or 0.0
    )

    by_source = {
        str(row[0] or ""): int(row[1])
        for row in db.execute(
            select(SummaryQualitySample.source, func.count()).group_by(
                SummaryQualitySample.source
            )
        ).all()
    }
    by_repo_source = {
        str(row[0] or ""): int(row[1])
        for row in db.execute(
            select(SummaryQualitySample.repo_source, func.count()).group_by(
                SummaryQualitySample.repo_source
            )
        ).all()
    }
    recent_rows = db.execute(
        select(
            SummaryQualitySample.batch_id,
            func.count(),
            func.avg(SummaryQualitySample.score),
            func.max(SummaryQualitySample.created_at),
        )
        .where(SummaryQualitySample.batch_id != "")
        .group_by(SummaryQualitySample.batch_id)
        .order_by(func.max(SummaryQualitySample.created_at).desc())
        .limit(5)
    ).all()
    recent_batches = [
        {
            "batchId": row[0],
            "total": int(row[1]),
            "avgScore": round(float(row[2] or 0.0), 1),
            "createdAt": row[3],
        }
        for row in recent_rows
    ]
    return QualityStatsOut(
        total=total,
        pending=counts.get("pending", 0),
        passed=passed,
        failed=failed,
        passRate=round(passed / reviewed, 3) if reviewed else 0.0,
        avgScore=round(avg_score, 1),
        bySource=by_source,
        byRepoSource=by_repo_source,
        recentBatches=recent_batches,
    )


@router.post("/sample-existing", summary="对存量摘要补抽样")
def sample_existing(
    payload: QualitySampleExistingIn,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return sample_existing_summaries(
        db,
        source=payload.source,
        limit=payload.limit,
        rate=payload.rate,
        batch_id=payload.batchId,
    )
