"""热榜接口：列表查询、按日快照、趋势历史、抓取入队与抓取告警。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CrawlAlert, TrendingRepository, TrendingSnapshot
from app.schemas import (
    CrawlAlertOut,
    TaskEnqueued,
    TrendingRepoOut,
    TrendingSnapshotDateOut,
    TrendingSnapshotOut,
)
from app.tasks.jobs import crawl_trending, summarize_readmes

router = APIRouter(prefix="/api/trending", tags=["trending"])


def _parse_snapshot_date(value: Optional[str]) -> Optional[date]:
    """解析 YYYY-MM-DD；非法日期返回 422。"""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="date 需为 YYYY-MM-DD") from exc


def _latest_snapshot_date(db: Session) -> Optional[date]:
    return db.execute(select(func.max(TrendingSnapshot.snapshot_date))).scalar()


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


@router.get(
    "/snapshots",
    response_model=list[TrendingSnapshotOut],
    summary="热榜按日快照（默认最近一天，可按日期 / 语言筛选）",
)
def list_trending_snapshots(
    db: Session = Depends(get_db),
    snapshot_date: Optional[str] = Query(default=None, alias="date", description="YYYY-MM-DD，默认最近一天"),
    platform: str = Query(default="github", description="github / gitee / all"),
    language: Optional[str] = Query(default=None, description="主语言，如 Python"),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[TrendingSnapshot]:
    target = _parse_snapshot_date(snapshot_date) or _latest_snapshot_date(db)
    if target is None:
        return []
    stmt = (
        select(TrendingSnapshot)
        .where(TrendingSnapshot.snapshot_date == target)
        .order_by(TrendingSnapshot.rank.asc(), TrendingSnapshot.repo_id.asc())
        .limit(limit)
    )
    if platform and platform != "all":
        stmt = stmt.where(TrendingSnapshot.platform == platform)
    if language:
        stmt = stmt.where(func.lower(TrendingSnapshot.language) == language.strip().lower())
    return list(db.execute(stmt).scalars().all())


@router.get(
    "/dates",
    response_model=list[TrendingSnapshotDateOut],
    summary="热榜快照可用日期（倒序）",
)
def list_trending_snapshot_dates(
    db: Session = Depends(get_db),
    limit: int = Query(default=30, ge=1, le=365),
) -> list[dict]:
    stmt = (
        select(TrendingSnapshot.snapshot_date, func.count().label("count"))
        .group_by(TrendingSnapshot.snapshot_date)
        .order_by(TrendingSnapshot.snapshot_date.desc())
        .limit(limit)
    )
    return [
        {"date": row[0], "count": int(row[1])}
        for row in db.execute(stmt).all()
    ]


@router.get(
    "/history",
    response_model=list[TrendingSnapshotOut],
    summary="单仓库热榜历史（Star / 排名趋势）",
)
def trending_history(
    db: Session = Depends(get_db),
    repo_id: str = Query(alias="repoId", min_length=3, description="owner/repo"),
    days: int = Query(default=30, ge=1, le=365),
) -> list[TrendingSnapshot]:
    cutoff = date.today() - timedelta(days=days)
    stmt = (
        select(TrendingSnapshot)
        .where(
            TrendingSnapshot.repo_id == repo_id.strip(),
            TrendingSnapshot.snapshot_date >= cutoff,
        )
        .order_by(TrendingSnapshot.snapshot_date.asc())
    )
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
    with_summary: bool = Query(default=True, description="抓取完成后自动入队摘要"),
) -> TaskEnqueued:
    task = crawl_trending.delay(
        platform=platform,
        language=language,
        languages=languages,
        since=since,
        with_summary=with_summary,
    )
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
