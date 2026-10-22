"""热榜接口：列表查询与抓取入队。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import TrendingRepository
from app.schemas import TaskEnqueued, TrendingRepoOut
from app.tasks.jobs import crawl_trending, summarize_readmes

router = APIRouter(prefix="/api/trending", tags=["trending"])


@router.get("", response_model=list[TrendingRepoOut], summary="热榜列表")
def list_trending(
    db: Session = Depends(get_db),
    platform: str = Query(default="github", description="github / gitee / all"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[TrendingRepository]:
    stmt = (
        select(TrendingRepository)
        .order_by(TrendingRepository.crawled_at.desc(), TrendingRepository.stars_today.desc())
        .limit(limit)
    )
    if platform and platform != "all":
        stmt = stmt.where(TrendingRepository.platform == platform)
    return list(db.execute(stmt).scalars().all())


@router.post(
    "/crawl",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    summary="入队：热榜抓取（/api/tasks/crawl-trending 的便捷别名）",
)
async def enqueue_trending_crawl(
    platform: str = Query(default="github", pattern="^(github|gitee|all)$"),
    language: str | None = Query(default=None),
    with_summary: bool = Query(default=True, description="抓取完成后自动入队摘要"),
) -> TaskEnqueued:
    task = crawl_trending.delay(platform=platform, language=language, with_summary=with_summary)
    return TaskEnqueued(taskId=task.id)


@router.post(
    "/summarize",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    summary="入队：热榜仓库中文摘要批量生成",
)
async def enqueue_trending_summarize(
    repo_id: list[str] | None = Query(default=None, description="仅处理指定仓库，可重复传"),
    limit: int = Query(default=200, ge=1, le=1000),
    batch_size: int = Query(default=10, ge=1, le=50),
    force: bool = Query(default=False),
    max_chars: int = Query(default=800, ge=200, le=4000),
) -> TaskEnqueued:
    task = summarize_readmes.delay(
        repo_ids=repo_id,
        limit=limit,
        batch_size=batch_size,
        force=force,
        max_chars=max_chars,
        source="trending",
    )
    return TaskEnqueued(taskId=task.id)
