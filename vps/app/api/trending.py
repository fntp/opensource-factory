"""热榜接口：列表查询、按日快照、详情、趋势历史、抓取入队与抓取告警。"""
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
    TrendingRepoDetail,
    TrendingRepoOut,
    TrendingRetentionStatus,
    TrendingSnapshotDateOut,
    TrendingSnapshotOut,
)
from app.services.trending_retention import retention_status
from app.tasks.jobs import cleanup_trending_data, crawl_trending, summarize_readmes

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


def build_trending_summary(row: TrendingRepository) -> tuple[str, str]:
    """构造详情摘要，返回 `(摘要, 来源)`。

    优先级：M2-04 生成的 `readme_summary` → 项目描述 → 技术栈提示 → 空。
    详情页必须始终有可展示内容，同时明确标注来源，避免把描述冒充模型摘要。
    """
    summary = (row.readme_summary or "").strip()
    if summary:
        return summary, "readme"
    description = (row.description or "").strip()
    if description:
        return description, "description"
    tech_stack = (row.tech_stack or "").strip()
    if tech_stack:
        return f"该项目主要使用 {tech_stack}。", "tech"
    return "", "empty"


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


@router.get(
    "/{repo_id:path}",
    response_model=TrendingRepoDetail,
    summary="热榜详情（摘要 + 元信息）",
)
def get_trending_detail(
    repo_id: str,
    db: Session = Depends(get_db),
) -> TrendingRepoDetail:
    """按 `owner/repo` 查询热榜项目详情；不存在返回 404。"""
    normalized = repo_id.strip().strip("/")
    row = db.get(TrendingRepository, normalized)
    if row is None:
        raise HTTPException(status_code=404, detail="trending repo not found")

    summary, source = build_trending_summary(row)
    owner = row.owner or (normalized.split("/", 1)[0] if "/" in normalized else None)
    detail = TrendingRepoDetail.model_validate(row)
    return detail.model_copy(
        update={"summary": summary, "summary_source": source, "owner": owner}
    )
