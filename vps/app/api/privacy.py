"""数据保留与隐私内部接口（REQ-202610-0983 / M9-06）。

供边缘 Worker / 运维调用，统一要求 `X-Internal-Token`（未配置时不启用）：

- ``POST /api/privacy/purge-user``：删除指定用户的 VPS 本地镜像数据；
- ``GET  /api/privacy/retention``：查看保留配置与待清理计数；
- ``POST /api/privacy/cleanup``：立即执行一轮保留清理（支持 dryRun）。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import PrivacyCleanupRequest, PrivacyPurgeUserRequest
from app.security import require_internal_token
from app.services.privacy_retention import (
    cleanup_expired_data,
    purge_user_data,
    retention_status,
)

router = APIRouter(
    prefix="/api/privacy",
    tags=["privacy"],
    dependencies=[Depends(require_internal_token)],
)


@router.post("/purge-user", summary="清理指定用户的 VPS 本地镜像")
def purge_user(
    payload: PrivacyPurgeUserRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """按 userId 删除推荐 / 评估 / 推送记录；幂等，可安全重试。"""
    return purge_user_data(db, payload.userId)


@router.get("/retention", summary="保留策略与待清理状态")
def get_retention(db: Session = Depends(get_db)) -> dict[str, Any]:
    return retention_status(db)


@router.post("/cleanup", summary="手动触发本地保留清理")
def run_cleanup(
    payload: Optional[PrivacyCleanupRequest] = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    dry_run = bool(payload.dryRun) if payload else False
    return cleanup_expired_data(db, dry_run=dry_run)
