"""向量化查询接口：统计、运行状态与单条向量。

写操作（入队 / 续跑）统一在 `/api/tasks/vectorize`，本路由只读。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import VectorDetail, VectorRunOut, VectorStatsResponse
from app.services.vector_pipeline import (
    RunNotFound,
    VectorRunError,
    get_run,
    get_stats,
    get_vector,
    list_runs,
    run_to_dict,
)

router = APIRouter(prefix="/api/vectors", tags=["vectors"])


@router.get("/stats", response_model=VectorStatsResponse, summary="向量化覆盖率与最近运行")
def vector_stats(db: Session = Depends(get_db)) -> VectorStatsResponse:
    return VectorStatsResponse(**get_stats(db))


@router.get("/runs", response_model=list[VectorRunOut], summary="最近向量化运行")
def vector_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[VectorRunOut]:
    return [VectorRunOut(**run_to_dict(run)) for run in list_runs(db, limit=limit)]


@router.get("/runs/{run_id}", response_model=VectorRunOut, summary="向量化运行详情")
def vector_run_detail(run_id: str, db: Session = Depends(get_db)) -> VectorRunOut:
    try:
        run = get_run(db, run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return VectorRunOut(**run_to_dict(run))


@router.get("/{source}/{repo_id:path}", response_model=VectorDetail, summary="单条仓库向量")
def vector_detail(source: str, repo_id: str, db: Session = Depends(get_db)) -> VectorDetail:
    try:
        item = get_vector(db, source, repo_id)
    except VectorRunError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="向量不存在")
    return VectorDetail(**item)
