"""Vectorize 索引同步接口 `/api/vector-index/*`。

- POST /sync：入队增量 / 全量同步，返回 taskId + runId；
- GET  /status：本地向量数、状态分布、最近运行；
- GET  /runs：运行列表；
- GET  /runs/{run_id}：单次运行详情；
- POST /reconcile：同步执行对账（可选修复），返回统计。

所有接口复用 `/api/tasks/*` 的内部令牌依赖；未配置 INTERNAL_TOKEN 时本地开发不鉴权。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.security import require_internal_token
from app.schemas import VectorReconcileRequest, VectorSyncEnqueued, VectorSyncRequest
from app.services import vector_index
from app.tasks.jobs import reconcile_vector_index, sync_vector_index

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/vector-index",
    tags=["vector-index"],
    dependencies=[Depends(require_internal_token)],
)


@router.post(
    "/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=VectorSyncEnqueued,
    summary="入队：Vectorize 索引同步",
)
async def enqueue_sync(payload: VectorSyncRequest) -> VectorSyncEnqueued:
    run_id = vector_index.create_run(payload.mode, payload.scope)
    task = sync_vector_index.delay(
        run_id=run_id,
        mode=payload.mode,
        scope=payload.scope,
        limit=payload.limit,
        batch_size=payload.batchSize,
    )
    return VectorSyncEnqueued(taskId=task.id, runId=run_id)


@router.get("/status", summary="Vectorize 索引同步状态")
async def get_status() -> dict:
    return vector_index.index_status()


@router.get("/runs", summary="Vectorize 索引同步运行列表")
async def get_runs(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    return {"items": vector_index.list_runs(limit)}


@router.get("/runs/{run_id}", summary="Vectorize 索引同步运行详情")
async def get_run(run_id: str) -> dict:
    run = vector_index.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return run


@router.post("/reconcile", summary="对账：校验本地向量与 Vectorize 索引")
async def reconcile(payload: VectorReconcileRequest) -> dict:
    return vector_index.reconcile_vectors(
        scope=payload.scope,
        repair=payload.repair,
        limit=payload.limit,
    )
