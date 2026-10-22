"""依赖分析内部接口 `/api/analysis/*`（M6-07 / REQ-202610-0954）。

供 edge Worker 调用，统一要求 `X-Internal-Token`（`INTERNAL_TOKEN` 为空时不鉴权）：

- `GET  /api/analysis/dependencies?repoIds=a,b&top=20`：聚合查询（只读本地表）；
- `POST /api/analysis/dependencies/refresh`：按仓库 id 扫描清单并入库。

`repoIds` 为空表示全部已同步仓库；edge 始终传入当前用户的仓库 id，
避免越权读取他人的依赖明细。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.tasks import require_internal_token
from app.db import get_db
from app.schemas import (
    DependencyAnalysisResponse,
    DependencyRefreshRequest,
    DependencyRefreshResponse,
)
from app.services.dependency_analysis import aggregate_dependencies, scan_repositories

router = APIRouter(
    prefix="/api/analysis",
    tags=["analysis"],
    dependencies=[Depends(require_internal_token)],
)


def _split_ids(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


@router.get(
    "/dependencies",
    response_model=DependencyAnalysisResponse,
    summary="依赖分析聚合（技术栈 / 生态 / 依赖覆盖）",
)
def dependency_analysis(
    repoIds: str = Query(default="", description="逗号分隔的仓库 id；为空表示全部"),
    top: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> DependencyAnalysisResponse:
    return DependencyAnalysisResponse(
        **aggregate_dependencies(db, _split_ids(repoIds), top=top)
    )


@router.post(
    "/dependencies/refresh",
    response_model=DependencyRefreshResponse,
    summary="扫描仓库依赖清单并入库",
)
def refresh_dependencies(
    payload: DependencyRefreshRequest,
    db: Session = Depends(get_db),
) -> DependencyRefreshResponse:
    result = scan_repositories(
        db,
        payload.repoIds,
        force=payload.force,
        limit=payload.limit,
    )
    return DependencyRefreshResponse(**result)
