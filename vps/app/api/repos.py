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


def _escape_like(value: str) -> str:
    """转义 LIKE 通配符，避免用户输入放大扫描范围。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=list[RepoOut], summary="仓库列表（支持分类 / 关键字过滤）")
def list_repos(
    db: Session = Depends(get_db),
    category_id: str | None = Query(default=None, description="按分类 ID 过滤"),
    q: str | None = Query(default=None, description="按名称 / ID / 描述模糊搜索"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[MyRepository]:
    """仓库列表：按 Star 降序；分类与关键字条件下推 SQL，配合检索索引。"""
    stmt = (
        select(MyRepository)
        .order_by(MyRepository.stars.desc())
        .limit(limit)
        .offset(offset)
    )
    if category_id:
        stmt = stmt.where(MyRepository.category_id == category_id)
    keyword = (q or "").strip()[:100]
    if keyword:
        like = f"%{_escape_like(keyword)}%"
        stmt = stmt.where(
            or_(
                MyRepository.name.like(like, escape="\\"),
                MyRepository.id.like(like, escape="\\"),
                MyRepository.description.like(like, escape="\\"),
            )
        )
    return list(db.execute(stmt).scalars().all())


@router.post(
    "/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    summary="入队：GitHub 仓库同步（/api/tasks/sync 的便捷别名）",
)
async def enqueue_repos_sync(include_starred: bool = Query(default=True)) -> TaskEnqueued:
    task = sync_repositories.delay(include_starred=include_starred)
    return TaskEnqueued(taskId=task.id)
