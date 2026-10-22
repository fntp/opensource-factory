"""本机一体化只读 API（REQ-202610-0940 / M5-02）。

与 edge Worker 的前端契约对齐，但直接读取本机 SQLite 镜像：
`my_repositories` / `trending_repositories` / `categories` / `recommendations`。

设计边界：
- 仅在 `LOCAL_MODE=true` 时可用（默认 404），避免混合部署意外暴露单用户接口；
- 只读：不提供收藏 / 分类编辑等写操作，写路径仍由 VPS 任务与后续迭代承担；
- 单用户：身份来自 `LOCAL_USER_*` 配置，不做 GitHub OAuth / Cookie 会话；
- 所有字段使用 camelCase，与 admin 现有 `fetchWithFallback` 调用完全兼容。
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.local_ui import resolve_admin_dir
from app.models import (
    Category,
    MyRepository,
    Recommendation,
    TrendingRepository,
    TrendingSnapshot,
)
from app.schemas import (
    LocalAuthUser,
    LocalCategoriesPayload,
    LocalCategoryItem,
    LocalDashboardStats,
    LocalRecommendation,
    LocalRecommendationStats,
    LocalRepoItem,
    LocalStatus,
    LocalTrendingDates,
    LocalTrendingDetail,
    LocalTrendingLanguageItem,
    LocalTrendingLanguages,
    LocalTrendingRepo,
)


def require_local_mode() -> None:
    """未开启本机一体化模式时返回 404（与不存在的路由一致）。"""
    if not get_settings().LOCAL_MODE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="local_mode_disabled")


router = APIRouter(prefix="/api", tags=["local"], dependencies=[Depends(require_local_mode)])


def _split_repo_id(repo_id: str) -> tuple[str, str]:
    """`owner/name` → (owner, name)；无斜杠时 owner 为空。"""
    if "/" in repo_id:
        owner, name = repo_id.split("/", 1)
        return owner, name
    return "", repo_id


def _parse_based_on(raw: str | None) -> list[str]:
    """解析推荐依据（JSON 数组，兼容逗号分隔旧格式）。"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def _iso(value: Any) -> str | None:
    """datetime/date → ISO 字符串；空值返回 None。"""
    if value is None:
        return None
    return value.isoformat()


@router.get("/auth/me", response_model=LocalAuthUser, summary="本机当前用户")
def current_user() -> LocalAuthUser:
    settings = get_settings()
    return LocalAuthUser(
        id=settings.LOCAL_USER_ID,
        login=settings.LOCAL_USER_LOGIN,
        name=settings.LOCAL_USER_NAME,
        email=None,
        avatarUrl=None,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="退出（本机无会话，空操作）")
def logout() -> None:
    return None


@router.get("/repos", response_model=list[LocalRepoItem], summary="仓库列表")
def list_repos(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, description="名称 / 描述模糊搜索"),
    categoryId: str | None = Query(default=None, description="按分类 ID 过滤"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[LocalRepoItem]:
    stmt = select(MyRepository).order_by(MyRepository.stars.desc(), MyRepository.created_at.desc())
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                MyRepository.id.like(like),
                MyRepository.name.like(like),
                MyRepository.description.like(like),
            )
        )
    if categoryId:
        stmt = stmt.where(MyRepository.category_id == categoryId)
    rows = list(db.execute(stmt.limit(limit)).scalars().all())

    categories = {
        item.id: item.name for item in db.execute(select(Category)).scalars().all()
    }
    return [
        LocalRepoItem(
            id=row.id,
            fullName=row.id,
            description=row.description or row.readme_summary,
            summary=row.readme_summary,
            language=row.language,
            stars=row.stars or 0,
            forks=0,
            category=categories.get(row.category_id or "") or row.category_id,
            tags=[],
            updatedAt=_iso(row.created_at),
            url=row.html_url,
        )
        for row in rows
    ]


def _trend_value(raw: str | None, is_new: int = 0) -> str:
    """快照趋势值 → admin 契约（up / down / new / same）。"""
    if is_new:
        return "new"
    return {"up": "up", "down": "down", "new": "new", "steady": "same", "same": "same"}.get(
        (raw or "").lower(), "same"
    )


def _snapshot_item(row: TrendingSnapshot) -> LocalTrendingRepo:
    owner, name = _split_repo_id(row.repo_id)
    return LocalTrendingRepo(
        id=row.repo_id,
        owner=row.owner or owner,
        name=row.name or name,
        description=row.description,
        language=row.language,
        stars=row.stars or 0,
        starsToday=row.stars_today or 0,
        url=row.html_url,
        snapshotDate=row.snapshot_date.isoformat(),
        rank=row.rank or 0,
        rankChange=None if row.is_new else (row.rank_delta or 0),
        trend=_trend_value(row.trend, row.is_new),
    )


def _latest_snapshot_date(db: Session) -> date | None:
    return db.execute(select(func.max(TrendingSnapshot.snapshot_date))).scalar_one_or_none()


def _parse_tech_stack(raw: str | None) -> list[str]:
    """技术栈字段可能是 JSON 数组或逗号 / 顿号分隔文本。"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in re.split(r"[,，、/|]", raw) if item.strip()]


@router.get("/trending", response_model=list[LocalTrendingRepo], summary="热榜列表")
def list_trending(
    db: Session = Depends(get_db),
    date_str: str | None = Query(default=None, alias="date", description="快照日期 YYYY-MM-DD"),
    language: str | None = Query(default=None, description="按语言过滤"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[LocalTrendingRepo]:
    if date_str:
        try:
            snapshot_date = date.fromisoformat(date_str)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid_date") from exc
        stmt = select(TrendingSnapshot).where(TrendingSnapshot.snapshot_date == snapshot_date)
        if language:
            stmt = stmt.where(TrendingSnapshot.language == language)
        rows = list(db.execute(stmt.order_by(TrendingSnapshot.rank.asc()).limit(limit)).scalars())
        return [_snapshot_item(row) for row in rows]

    stmt = select(TrendingRepository)
    if language:
        stmt = stmt.where(TrendingRepository.language == language)
    rows = list(
        db.execute(
            stmt.order_by(TrendingRepository.stars_today.desc(), TrendingRepository.stars.desc()).limit(limit)
        ).scalars()
    )
    items: list[LocalTrendingRepo] = []
    for index, row in enumerate(rows, start=1):
        owner, name = _split_repo_id(row.id)
        items.append(
            LocalTrendingRepo(
                id=row.id,
                owner=row.owner or owner,
                name=row.name or name,
                description=row.description,
                language=row.language,
                stars=row.stars or 0,
                starsToday=row.stars_today or 0,
                url=row.html_url,
                snapshotDate=row.crawled_at.isoformat() if row.crawled_at else None,
                rank=index,
                rankChange=None,
                trend="same",
            )
        )
    return items


@router.get("/trending/dates", response_model=LocalTrendingDates, summary="热榜可用日期")
def trending_dates(db: Session = Depends(get_db)) -> LocalTrendingDates:
    dates = [
        item.isoformat()
        for item in db.execute(
            select(TrendingSnapshot.snapshot_date)
            .distinct()
            .order_by(TrendingSnapshot.snapshot_date.desc())
            .limit(30)
        ).scalars()
    ]
    if not dates:
        dates = [
            item.isoformat()
            for item in db.execute(
                select(TrendingRepository.crawled_at)
                .distinct()
                .order_by(TrendingRepository.crawled_at.desc())
                .limit(30)
            ).scalars()
            if item is not None
        ]
    return LocalTrendingDates(dates=dates, latest=dates[0] if dates else None)


@router.get("/trending/languages", response_model=LocalTrendingLanguages, summary="热榜语言分布")
def trending_languages(
    db: Session = Depends(get_db),
    date_str: str | None = Query(default=None, alias="date"),
) -> LocalTrendingLanguages:
    snapshot_date: date | None = None
    if date_str:
        try:
            snapshot_date = date.fromisoformat(date_str)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid_date") from exc
    else:
        snapshot_date = _latest_snapshot_date(db)

    if snapshot_date is not None:
        rows = db.execute(
            select(TrendingSnapshot.language, func.count(TrendingSnapshot.repo_id))
            .where(TrendingSnapshot.snapshot_date == snapshot_date)
            .group_by(TrendingSnapshot.language)
            .order_by(func.count(TrendingSnapshot.repo_id).desc())
        ).all()
        resolved = snapshot_date
    else:
        rows = db.execute(
            select(TrendingRepository.language, func.count(TrendingRepository.id))
            .group_by(TrendingRepository.language)
            .order_by(func.count(TrendingRepository.id).desc())
        ).all()
        resolved = None
    return LocalTrendingLanguages(
        date=resolved.isoformat() if resolved else None,
        languages=[
            LocalTrendingLanguageItem(language=language or "未知", count=int(count))
            for language, count in rows
        ],
    )


@router.get("/trending/{owner}/{name}", response_model=LocalTrendingDetail, summary="热榜详情")
def trending_detail(owner: str, name: str, db: Session = Depends(get_db)) -> LocalTrendingDetail:
    repo_id = f"{owner}/{name}"
    row = db.get(TrendingRepository, repo_id)
    snapshot_date = _latest_snapshot_date(db)
    snapshot = (
        db.execute(
            select(TrendingSnapshot).where(
                TrendingSnapshot.snapshot_date == snapshot_date,
                TrendingSnapshot.repo_id == repo_id,
            )
        ).scalar_one_or_none()
        if snapshot_date
        else None
    )
    if row is None and snapshot is None:
        raise HTTPException(status_code=404, detail="not_found")

    if row is not None:
        base = LocalTrendingRepo(
            id=row.id,
            owner=row.owner or owner,
            name=row.name or name,
            description=row.description,
            language=row.language,
            stars=row.stars or 0,
            starsToday=row.stars_today or 0,
            url=row.html_url,
            snapshotDate=row.crawled_at.isoformat() if row.crawled_at else None,
            rank=snapshot.rank if snapshot else 0,
            rankChange=None if snapshot is None or snapshot.is_new else (snapshot.rank_delta or 0),
            trend=_trend_value(snapshot.trend, snapshot.is_new) if snapshot else "same",
        )
        platform = row.platform
        tech_stack = _parse_tech_stack(row.tech_stack)
        summary = row.readme_summary
        crawled_at = row.crawled_at.isoformat() if row.crawled_at else None
    else:
        assert snapshot is not None
        base = _snapshot_item(snapshot)
        platform = snapshot.platform
        tech_stack = _parse_tech_stack(snapshot.tech_stack)
        summary = None
        crawled_at = snapshot.snapshot_date.isoformat()

    if summary:
        summary_source = "readme"
    elif base.description:
        summary_source = "description"
    elif tech_stack:
        summary_source = "tech"
    else:
        summary_source = "empty"
    return LocalTrendingDetail(
        **base.model_dump(),
        platform=platform,
        techStack=tech_stack,
        summary=summary,
        summarySource=summary_source,
        crawledAt=crawled_at,
        isFavorited=db.get(MyRepository, repo_id) is not None,
    )


@router.get(
    "/recommendations",
    response_model=list[LocalRecommendation],
    summary="推荐列表",
)
def list_recommendations(
    db: Session = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[LocalRecommendation]:
    stmt = select(Recommendation).order_by(Recommendation.score.desc()).limit(limit)
    if status_filter and status_filter != "all":
        stmt = stmt.where(Recommendation.status == status_filter)
    rows = list(db.execute(stmt).scalars().all())

    # 批量水合仓库元信息，避免逐条查询
    repo_ids = [row.repo_id for row in rows]
    my_map: dict[str, MyRepository] = {}
    trending_map: dict[str, TrendingRepository] = {}
    if repo_ids:
        my_map = {
            item.id: item
            for item in db.execute(
                select(MyRepository).where(MyRepository.id.in_(repo_ids))
            ).scalars()
        }
        trending_map = {
            item.id: item
            for item in db.execute(
                select(TrendingRepository).where(TrendingRepository.id.in_(repo_ids))
            ).scalars()
        }

    items: list[LocalRecommendation] = []
    for row in rows:
        owner, name = _split_repo_id(row.repo_id)
        my_repo = my_map.get(row.repo_id)
        trending = trending_map.get(row.repo_id)
        if my_repo is not None:
            owner, name = _split_repo_id(my_repo.id)
            description = my_repo.description or my_repo.readme_summary
            language = my_repo.language
            stars = my_repo.stars or 0
            url = my_repo.html_url
        elif trending is not None:
            owner = trending.owner or owner
            name = trending.name or name
            description = trending.description
            language = trending.language
            stars = trending.stars or 0
            url = trending.html_url
        else:
            description = None
            language = None
            stars = 0
            url = None
        items.append(
            LocalRecommendation(
                id=row.id,
                repoId=row.repo_id,
                owner=owner or None,
                name=name or None,
                description=description,
                language=language,
                stars=stars,
                score=row.score or 0.0,
                reason=row.reason,
                basedOn=_parse_based_on(row.based_on),
                url=url,
                status=row.status or "new",
                createdAt=_iso(row.created_at),
            )
        )
    return items


@router.get(
    "/recommendations/stats",
    response_model=LocalRecommendationStats,
    summary="推荐状态统计",
)
def recommendation_stats(db: Session = Depends(get_db)) -> LocalRecommendationStats:
    counts = {
        str(status): int(count)
        for status, count in db.execute(
            select(Recommendation.status, func.count(Recommendation.id)).group_by(
                Recommendation.status
            )
        ).all()
    }
    return LocalRecommendationStats(
        new=counts.get("new", 0),
        saved=counts.get("saved", 0),
        dismissed=counts.get("dismissed", 0),
        pushed=counts.get("pushed", 0),
        clicked=0,
    )


@router.get("/categories", response_model=LocalCategoriesPayload, summary="分类 + 标签")
def list_categories(db: Session = Depends(get_db)) -> LocalCategoriesPayload:
    counts = dict(
        db.execute(
            select(MyRepository.category_id, func.count(MyRepository.id)).group_by(
                MyRepository.category_id
            )
        ).all()
    )
    rows = list(db.execute(select(Category).order_by(Category.name.asc())).scalars().all())
    return LocalCategoriesPayload(
        categories=[
            LocalCategoryItem(
                id=row.id,
                name=row.name,
                count=int(counts.get(row.id, 0)),
                description=None,
            )
            for row in rows
        ],
        tags=[],
    )


@router.get("/dashboard/stats", response_model=LocalDashboardStats, summary="仪表盘统计")
def dashboard_stats(db: Session = Depends(get_db)) -> LocalDashboardStats:
    total_repos = int(db.execute(select(func.count(MyRepository.id))).scalar_one())
    trending_today = int(
        db.execute(
            select(func.count(TrendingRepository.id)).where(
                TrendingRepository.crawled_at == date.today()
            )
        ).scalar_one()
    )
    pending = int(
        db.execute(
            select(func.count(Recommendation.id)).where(Recommendation.status == "new")
        ).scalar_one()
    )
    category_count = int(db.execute(select(func.count(Category.id))).scalar_one())
    return LocalDashboardStats(
        totalRepos=total_repos,
        trendingToday=trending_today,
        pendingRecommendations=pending,
        categoryCount=category_count,
    )


@router.get("/local/status", response_model=LocalStatus, summary="本机一体化模式状态")
def local_status() -> LocalStatus:
    settings = get_settings()
    admin_dir = resolve_admin_dir(settings)
    return LocalStatus(
        mode="local",
        version=settings.VERSION,
        readOnly=True,
        userId=settings.LOCAL_USER_ID,
        adminDir=str(admin_dir),
        adminReady=(admin_dir / "index.html").is_file(),
        database=settings.DATABASE_URL.split(":", 1)[0],
    )
