"""热榜接口：列表查询、抓取入队与抓取告警。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CrawlAlert, TrendingRepository
from app.schemas import CrawlAlertOut, TaskEnqueued, TrendingRepoOut
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
    language: str | None = Query(default=None),
) -> TaskEnqueued:
    task = crawl_trending.delay(platform=platform, language=language)
    return TaskEnqueued(taskId=task.id)


@router.get(
    "/alerts",
    response_model=list[CrawlAlertOut],
    summary="热榜抓取告警列表（结构变更 / 抓取失败 / 条数骤降）",
)
def list_crawl_alerts(
    db: Session = Depends(get_db),
    status_filter: str = Query(
        default="open",
        alias="status",
        pattern="^(open|acknowledged|all)$",
        description="open / acknowledged / all",
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CrawlAlert]:
    stmt = select(CrawlAlert).order_by(CrawlAlert.last_seen_at.desc()).limit(limit)
    if status_filter != "all":
        stmt = stmt.where(CrawlAlert.status == status_filter)
    return list(db.execute(stmt).scalars().all())


@router.post(
    "/alerts/{alert_id}/ack",
    response_model=CrawlAlertOut,
    summary="确认（acknowledge）一条抓取告警",
)
def acknowledge_crawl_alert(alert_id: str, db: Session = Depends(get_db)) -> CrawlAlert:
    alert = db.get(CrawlAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    if alert.status != "acknowledged":
        alert.status = "acknowledged"
        alert.acknowledged_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        db.refresh(alert)
    return alert
