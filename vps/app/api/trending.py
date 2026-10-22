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
    TrendingSnapshotDateOut,
    TrendingSnapshotOut,
)
from app.tasks.jobs import crawl_trending

router = APIRouter(prefix="/api/trending", tags=["trending"])


def _parse_snapshot_date(value: Optional[str]) -> Optional[date]:
    """解析 YYYY-MM-DD；非法日期返回 422。"""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="date 需为 YYYY-MM-DD") from exc


def _latest_snapshot_date(db: Session, platform: str = "all") -> Optional[date]:
    stmt = select(func.max(TrendingSnapshot.snapshot_date))
    if platform and platform != "all":
        stmt = stmt.where(TrendingSnapshot.platform == platform)
    return db.execute(stmt).scalar()


def _trend_of(row: TrendingSnapshot) -> str:
    """页面趋势按排名变化符号标注（M2-05 的 trend 字段采用 ±3 阈值）。"""
    if row.is_new:
        return "new"
    if (row.rank_delta or 0) > 0:
        return "up"
    if (row.rank_delta or 0) < 0:
        return "down"
    return "same"


def _snapshot_out(row: TrendingSnapshot) -> TrendingRepoOut:
    return TrendingRepoOut(
        id=row.repo_id,
        platform=row.platform,
        name=row.name,
        html_url=row.html_url,
        stars_today=row.stars_today or 0,
        description=row.description,
        tech_stack=row.tech_stack,
        crawled_at=row.created_at.date() if row.created_at else None,
        owner=row.owner,
        language=row.language,
        stars=row.stars or 0,
        snapshot_date=row.snapshot_date,
        rank=row.rank or 0,
        rank_change=None if row.is_new else (row.rank_delta or 0),
        trend=_trend_of(row),
    )


def _latest_out(row: TrendingRepository, rank: int) -> TrendingRepoOut:
    return TrendingRepoOut(
        id=row.id,
        platform=row.platform,
        name=row.name,
        html_url=row.html_url,
        stars_today=row.stars_today or 0,
        description=row.description,
        tech_stack=row.tech_stack,
        crawled_at=row.crawled_at,
        owner=row.owner,
        language=row.language,
        stars=row.stars or 0,
        snapshot_date=row.crawled_at,
        rank=rank,
        rank_change=0,
        trend="same",
    )


@router.get("", response_model=list[TrendingRepoOut], summary="热榜列表（按日快照）")
def list_trending(
    db: Session = Depends(get_db),
    platform: str = Query(default="github", description="github / gitee / all"),
    snapshot_date: Optional[date] = Query(default=None, alias="date", description="YYYY-MM-DD"),
    language: Optional[str] = Query(default=None, description="按主语言筛选"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[TrendingRepoOut]:
    target = snapshot_date or _latest_snapshot_date(db, platform)

    if target is not None:
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
        rows = list(db.execute(stmt).scalars().all())
        if rows:
            return [_snapshot_out(row) for row in rows]

        # 明确指定日期 / 语言但无匹配：返回空列表，不静默回退
        if snapshot_date is not None or language:
            return []

    # 兼容旧数据：尚无任何快照时读最新状态表
    stmt = (
        select(TrendingRepository)
        .order_by(TrendingRepository.stars_today.desc(), TrendingRepository.id.asc())
        .limit(limit)
    )
    if platform and platform != "all":
        stmt = stmt.where(TrendingRepository.platform == platform)
    if language:
        stmt = stmt.where(func.lower(TrendingRepository.language) == language.strip().lower())
    rows = list(db.execute(stmt).scalars().all())
    return [_latest_out(row, index) for index, row in enumerate(rows, start=1)]


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
    rows = [
        {"date": row[0], "count": int(row[1])}
        for row in db.execute(stmt).all()
    ]
    if rows:
        return rows

    # 兼容旧数据：没有快照时用最新表的抓取日期
    fallback = (
        select(TrendingRepository.crawled_at, func.count().label("count"))
        .where(TrendingRepository.crawled_at.is_not(None))
        .group_by(TrendingRepository.crawled_at)
        .order_by(TrendingRepository.crawled_at.desc())
        .limit(limit)
    )
    return [
        {"date": row[0], "count": int(row[1])}
        for row in db.execute(fallback).all()
    ]


@router.get("/languages", summary="指定日期的语言分布")
def list_languages(
    db: Session = Depends(get_db),
    snapshot_date: Optional[date] = Query(default=None, alias="date", description="YYYY-MM-DD"),
) -> dict[str, object]:
    target = snapshot_date or _latest_snapshot_date(db)
    rows: list[tuple[str, int]] = []
    if target is not None:
        rows = [
            (language, int(count))
            for language, count in db.execute(
                select(TrendingSnapshot.language, func.count())
                .where(
                    TrendingSnapshot.snapshot_date == target,
                    TrendingSnapshot.language.is_not(None),
                    TrendingSnapshot.language != "",
                )
                .group_by(TrendingSnapshot.language)
                .order_by(func.count().desc(), TrendingSnapshot.language.asc())
            ).all()
        ]
    if not rows:
        rows = [
            (language, int(count))
            for language, count in db.execute(
                select(TrendingRepository.language, func.count())
                .where(
                    TrendingRepository.language.is_not(None),
                    TrendingRepository.language != "",
                )
                .group_by(TrendingRepository.language)
                .order_by(func.count().desc(), TrendingRepository.language.asc())
            ).all()
        ]
    return {
        "date": target.isoformat() if target is not None else None,
        "languages": [{"language": language, "count": count} for language, count in rows],
    }


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
) -> TaskEnqueued:
    task = crawl_trending.delay(
        platform=platform,
        language=language,
        languages=languages,
        since=since,
    )
    return TaskEnqueued(taskId=task.id)
