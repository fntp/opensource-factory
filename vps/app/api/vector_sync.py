"""Vectorize 索引同步接口 `/api/vector-index/*`。

- 写操作（同步 / 对账）统一入队 Celery，返回 `202 {"taskId": "..."}`；
- 读操作提供本地覆盖率、同步状态分布与运行记录；
- 与 `/api/tasks/*` 一致，配置 `INTERNAL_TOKEN` 后要求 `X-Internal-Token`。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.tasks import require_internal_token
from app.db import get_db
from app.schemas import (
    TaskEnqueued,
    VectorSyncRequest,
    VectorSyncRunOut,
    VectorSyncStatusOut,
)
from app.services.vector_sync import (
    VectorIndexError,
    get_run,
    get_status,
    list_runs,
    run_to_dict,
)
from app.tasks.jobs import sync_vector_index

router = APIRouter(prefix="/api/vector-index", tags=["vector-index"])


@router.post(
    "/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    dependencies=[Depends(require_internal_token)],
    summary="入队：Vectorize 索引同步 / 对账",
)
async def enqueue_vector_sync(payload: VectorSyncRequest) -> TaskEnqueued:
    task = sync_vector_index.delay(
        kind=payload.kind,
        scope=payload.scope,
        limit=payload.limit,
        batch_size=payload.batchSize,
        force=payload.force,
    )
    return TaskEnqueued(taskId=task.id)


@router.get(
    "/status",
    response_model=VectorSyncStatusOut,
    dependencies=[Depends(require_internal_token)],
    summary="索引同步状态与本地覆盖率",
)
def vector_sync_status(db: Session = Depends(get_db)) -> VectorSyncStatusOut:
    return VectorSyncStatusOut(**get_status(db))


@router.get(
    "/runs",
    response_model=list[VectorSyncRunOut],
    dependencies=[Depends(require_internal_token)],
    summary="最近同步运行",
)
def vector_sync_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[VectorSyncRunOut]:
    return [VectorSyncRunOut(**run_to_dict(run)) for run in list_runs(db, limit=limit)]


@router.get(
    "/runs/{run_id}",
    response_model=VectorSyncRunOut,
    dependencies=[Depends(require_internal_token)],
    summary="单次同步运行详情",
)
def vector_sync_run_detail(run_id: str, db: Session = Depends(get_db)) -> VectorSyncRunOut:
    try:
        run = get_run(db, run_id)
    except VectorIndexError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return VectorSyncRunOut(**run_to_dict(run))
