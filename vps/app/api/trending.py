"""热榜接口：列表查询、按日快照、趋势历史与抓取入队。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import TrendingRepository, TrendingSnapshot
from app.schemas import (
    TaskEnqueued,
    TrendingRepoOut,
    TrendingRetentionStatus,
    TrendingSnapshotDateOut,
    TrendingSnapshotOut,
)
from app.services.trending_retention import retention_status
from app.tasks.jobs import cleanup_trending_data, crawl_trending

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


@router.get(
    "/retention",
    response_model=TrendingRetentionStatus,
    summary="热榜数据保留策略状态（窗口 / 归档 / 磁盘占用）",
)
def get_trending_retention(db: Session = Depends(get_db)) -> dict:
    """返回当前保留窗口、过期快照数、SQLite 文件与归档目录占用。"""
    return retention_status(db)


@router.post(
    "/retention/cleanup",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    summary="入队：热榜快照归档与清理",
)
async def enqueue_trending_cleanup(
    dry_run: bool = Query(default=False, alias="dryRun", description="只统计不删除"),
    retention_days: int | None = Query(
        default=None,
        alias="retentionDays",
        ge=0,
        le=3650,
        description="覆盖默认保留天数；0 = 暂停清理",
    ),
    archive: bool = Query(default=True, description="清理前是否归档"),
) -> TaskEnqueued:
    task = cleanup_trending_data.delay(
        retention_days=retention_days,
        archive=archive,
        dry_run=dry_run,
    )
    return TaskEnqueued(taskId=task.id)


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
