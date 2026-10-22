"""仓库接口：列表查询与同步入队。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MyRepository
from app.schemas import RepoOut, TaskEnqueued
from app.tasks.jobs import sync_repositories

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


@router.post(
    "/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    summary="入队：GitHub 仓库同步（/api/tasks/sync 的便捷别名）",
)
async def enqueue_repos_sync(
    include_starred: bool = Query(default=True),
    include_own: bool | None = Query(default=None, description="覆盖配置：是否同步自有仓库"),
    include_orgs: bool | None = Query(default=None, description="覆盖配置：是否同步组织仓库"),
    include_forks: bool | None = Query(default=None, description="覆盖配置：是否包含 fork"),
    include_archived: bool | None = Query(default=None, description="覆盖配置：是否包含已归档"),
) -> TaskEnqueued:
    task = sync_repositories.delay(
        include_starred=include_starred,
        include_own=include_own,
        include_orgs=include_orgs,
        include_forks=include_forks,
        include_archived=include_archived,
    )
    return TaskEnqueued(taskId=task.id)
