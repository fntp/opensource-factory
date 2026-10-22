"""仓库接口：列表查询与同步入队。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.tasks import require_internal_token
from app.db import get_db
from app.models import MyRepository
from app.schemas import (
    LicenseInfoOut,
    RepoHealthListOut,
    RepoHealthOut,
    RepoHealthRefreshRequest,
    RepoOut,
    RepoUpdatesScanRequest,
    TaskEnqueued,
)
from app.services.license import build_compliance_hint
from app.services.repo_health import normalize_status, snapshot_for_row, summarize_health
from app.tasks.jobs import refresh_repo_health as refresh_repo_health_task
from app.tasks.jobs import scan_repo_updates as scan_repo_updates_task
from app.tasks.jobs import summarize_readmes, sync_repositories

router = APIRouter(prefix="/api/repos", tags=["repos"])


@router.get("", response_model=list[RepoOut], summary="仓库列表（支持分类 / 关键字过滤）")
def list_repos(
    db: Session = Depends(get_db),
    category_id: str | None = Query(default=None, description="按分类 ID 过滤"),
    q: str | None = Query(default=None, description="按名称 / 描述模糊搜索"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[MyRepository]:
    stmt = select(MyRepository).order_by(MyRepository.stars.desc()).limit(limit).offset(offset)
    if category_id:
        stmt = stmt.where(MyRepository.category_id == category_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(MyRepository.name.like(like), MyRepository.description.like(like)))
    return list(db.execute(stmt).scalars().all())


@router.get(
    "/health",
    response_model=RepoHealthListOut,
    dependencies=[Depends(require_internal_token)],
    summary="项目健康度列表与汇总（M6-05）",
)
def list_repo_health(
    db: Session = Depends(get_db),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(active|attention|stale|archived|unknown)$",
        description="按健康度状态过滤",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> RepoHealthListOut:
    rows = list(
        db.execute(
            select(MyRepository).order_by(MyRepository.stars.desc(), MyRepository.id.asc())
        )
        .scalars()
        .all()
    )
    all_items = [
        snapshot_for_row(row).to_dict(
            repo_id=row.id,
            name=row.name,
            html_url=row.html_url,
            language=row.language,
            stars=row.stars,
            checked_at=row.health_checked_at,
        )
        for row in rows
    ]
    summary = summarize_health(all_items)
    filtered = (
        [item for item in all_items if normalize_status(item.get("status")) == status_filter]
        if status_filter
        else all_items
    )
    return RepoHealthListOut(summary=summary, items=filtered[offset : offset + limit])


@router.get(
    "/{repo_id:path}/health",
    response_model=RepoHealthOut,
    dependencies=[Depends(require_internal_token)],
    summary="单仓库健康度（M6-05）",
)
def get_repo_health(repo_id: str, db: Session = Depends(get_db)) -> RepoHealthOut:
    row = db.get(MyRepository, repo_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="repository not found")
    return RepoHealthOut(
        **snapshot_for_row(row).to_dict(
            repo_id=row.id,
            name=row.name,
            html_url=row.html_url,
            language=row.language,
            stars=row.stars,
            checked_at=row.health_checked_at,
        )
    )


@router.post(
    "/health/refresh",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    dependencies=[Depends(require_internal_token)],
    summary="入队：刷新仓库元数据并重算健康度（M6-05）",
)
async def enqueue_repo_health_refresh(payload: RepoHealthRefreshRequest) -> TaskEnqueued:
    task = refresh_repo_health_task.delay(
        repo_ids=payload.repoIds or None,
        limit=payload.limit,
    )
    return TaskEnqueued(taskId=task.id)


@router.get(
    "/{repo_id:path}/license",
    response_model=LicenseInfoOut,
    summary="单仓库 License 合规提示（未识别时返回 unknown）",
)
def get_repo_license(repo_id: str, db: Session = Depends(get_db)) -> dict:
    normalized = repo_id.strip().strip("/")
    row = db.get(MyRepository, normalized)
    if row is None:
        raise HTTPException(status_code=404, detail="repo not found")
    return row.license or build_compliance_hint(None, None)


@router.post(
    "/updates/scan",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    dependencies=[Depends(require_internal_token)],
    summary="入队：扫描收藏项目新版本 / 重大变更（M7-04）",
)
async def enqueue_repo_updates_scan(payload: RepoUpdatesScanRequest) -> TaskEnqueued:
    task = scan_repo_updates_task.delay(
        repo_ids=payload.repoIds or None,
        limit=payload.limit,
        include_prerelease=payload.includePrerelease,
    )
    return TaskEnqueued(taskId=task.id)


@router.post(
    "/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    summary="入队：GitHub 仓库同步（/api/tasks/sync 的便捷别名）",
)
async def enqueue_repos_sync(
    include_starred: bool = Query(default=True),
    with_summary: bool = Query(default=True),
) -> TaskEnqueued:
    task = sync_repositories.delay(include_starred=include_starred, with_summary=with_summary)
    return TaskEnqueued(taskId=task.id)


@router.post(
    "/summarize",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    summary="入队：README 摘要批量生成（/api/tasks/summarize 的便捷别名）",
)
async def enqueue_repos_summarize(
    repo_id: list[str] | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    batch_size: int = Query(default=10, ge=1, le=50),
    force: bool = Query(default=False),
) -> TaskEnqueued:
    task = summarize_readmes.delay(
        repo_ids=repo_id,
        limit=limit,
        batch_size=batch_size,
        force=force,
    )
    return TaskEnqueued(taskId=task.id)
