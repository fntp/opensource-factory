"""备份与恢复运维接口（REQ-202610-0942 / M5-04）。

所有端点都要求 ``X-Internal-Token``（未配置 INTERNAL_TOKEN 时与项目其他内部接口一致，
本地开发不鉴权）。恢复生产库只提供 CLI，不通过 HTTP 暴露，避免误操作。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.tasks import require_internal_token
from app.backup import (
    BackupError,
    D1_KIND,
    SQLITE_KIND,
    backup_status,
    create_sqlite_snapshot,
    list_backups,
    run_restore_drill,
    sqlite_path_from_url,
    verify_d1_dump,
    verify_sqlite_snapshot,
)
from app.config import get_settings
from app.schemas import (
    BackupActionIn,
    BackupDrillOut,
    BackupEntryOut,
    BackupFilesOut,
    BackupStatusOut,
    BackupVerifyOut,
)

router = APIRouter(prefix="/api/backup", tags=["backup"])


def _settings():
    return get_settings()


def _backup_dir() -> Path:
    return Path(_settings().BACKUP_DIR)


def _resolve_name(kind: str, name: str | None):
    """按文件名查找备份，拒绝路径穿越。"""
    if name and Path(name).name != name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="备份名不能包含路径")
    entries = list_backups(_backup_dir(), kind)
    if not entries:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"没有可用的 {kind} 备份")
    if not name:
        return entries[0]
    for entry in entries:
        if entry.name == name:
            return entry
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"未找到备份：{name}")


@router.get(
    "/status",
    response_model=BackupStatusOut,
    dependencies=[Depends(require_internal_token)],
    summary="备份目录状态",
)
def get_status() -> BackupStatusOut:
    settings = _settings()
    return BackupStatusOut(
        **backup_status(
            _backup_dir(),
            retention=settings.BACKUP_RETENTION_COUNT,
            max_total_mb=settings.BACKUP_MAX_TOTAL_MB,
        )
    )


@router.get(
    "/files",
    response_model=BackupFilesOut,
    dependencies=[Depends(require_internal_token)],
    summary="备份产物列表",
)
def get_files(
    kind: str | None = Query(default=None, pattern=f"^({SQLITE_KIND}|{D1_KIND})$"),
) -> BackupFilesOut:
    entries = list_backups(_backup_dir(), kind)
    return BackupFilesOut(
        count=len(entries),
        items=[BackupEntryOut(**entry.to_dict()) for entry in entries],
    )


@router.post(
    "/sqlite",
    response_model=BackupEntryOut,
    dependencies=[Depends(require_internal_token)],
    summary="立即创建 SQLite 快照",
)
def create_sqlite_backup(payload: BackupActionIn | None = None) -> BackupEntryOut:
    settings = _settings()
    if not settings.BACKUP_ENABLED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="BACKUP_ENABLED=false")
    payload = payload or BackupActionIn()
    database = sqlite_path_from_url(settings.DATABASE_URL)
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 SQLite 数据库（DATABASE_URL 必须为 sqlite:///）",
        )
    try:
        entry = create_sqlite_snapshot(
            database,
            _backup_dir(),
            label=payload.label,
            keep=payload.keep or settings.BACKUP_RETENTION_COUNT,
            max_total_bytes=(payload.maxTotalMb if payload.maxTotalMb is not None else settings.BACKUP_MAX_TOTAL_MB)
            * 1024
            * 1024,
        )
    except BackupError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return BackupEntryOut(**entry.to_dict())


@router.post(
    "/sqlite/verify",
    response_model=BackupVerifyOut,
    dependencies=[Depends(require_internal_token)],
    summary="校验 SQLite 快照",
)
def verify_sqlite(payload: BackupActionIn | None = None) -> BackupVerifyOut:
    entry = _resolve_name(SQLITE_KIND, (payload or BackupActionIn()).name)
    return BackupVerifyOut(**verify_sqlite_snapshot(entry.path))


@router.post(
    "/sqlite/drill",
    response_model=BackupDrillOut,
    dependencies=[Depends(require_internal_token)],
    summary="执行 SQLite 恢复演练",
)
def drill_sqlite(payload: BackupActionIn | None = None) -> BackupDrillOut:
    if not _settings().BACKUP_DRILL_ENABLED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="BACKUP_DRILL_ENABLED=false")
    entry = _resolve_name(SQLITE_KIND, (payload or BackupActionIn()).name)
    return BackupDrillOut(**run_restore_drill(_backup_dir(), name=entry.name))


@router.post(
    "/d1/verify",
    response_model=BackupVerifyOut,
    dependencies=[Depends(require_internal_token)],
    summary="校验 D1 SQL 导出",
)
def verify_d1(payload: BackupActionIn | None = None) -> BackupVerifyOut:
    entry = _resolve_name(D1_KIND, (payload or BackupActionIn()).name)
    return BackupVerifyOut(**verify_d1_dump(entry.path))
