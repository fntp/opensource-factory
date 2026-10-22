"""重复 / 相似项目检测内部接口（M6-03）。

- `POST /api/duplicates/scan`：按 scope 扫描收藏库 / 热榜，返回重复簇与合并建议。

检测只读，不修改任何仓库；edge 负责按当前用户传入 `myRepoIds` 并二次过滤。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.tasks import require_internal_token
from app.db import get_db
from app.schemas import DuplicateScanRequest, DuplicateScanResponse
from app.services.duplicates import DuplicateError, detect_duplicates

router = APIRouter(
    prefix="/api/duplicates",
    tags=["duplicates"],
    dependencies=[Depends(require_internal_token)],
)


@router.post("/scan", response_model=DuplicateScanResponse, summary="扫描重复 / 相似项目")
def scan_duplicates(
    payload: DuplicateScanRequest,
    db: Session = Depends(get_db),
) -> DuplicateScanResponse:
    try:
        result = detect_duplicates(
            db,
            payload.scope,
            my_repo_ids=payload.myRepoIds,
            min_score=payload.minScore,
            name_threshold=payload.nameThreshold,
            max_repos=payload.maxRepos,
            max_clusters=payload.maxClusters,
        )
    except DuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DuplicateScanResponse(**result)
