"""仓库接口：列表查询与同步入队。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MyRepository
from app.schemas import RepoOut, TaskEnqueued
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
