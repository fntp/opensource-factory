"""热榜接口：列表查询与抓取入队。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import TrendingRepository
from app.schemas import TaskEnqueued, TrendingRepoOut
from app.tasks.jobs import crawl_trending

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
    language: str | None = Query(default=None, description="只抓单个语言页（如 python）"),
    languages: str | None = Query(
        default=None,
        description="逗号分隔的语言页列表；留空使用 TRENDING_LANGUAGES 配置",
    ),
    since: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
) -> TaskEnqueued:
    task = crawl_trending.delay(
        platform=platform,
        language=language,
        languages=languages,
        since=since,
    )
    return TaskEnqueued(taskId=task.id)
