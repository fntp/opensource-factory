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
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.local_ui import resolve_admin_dir
from app.models import Category, MyRepository, Recommendation, TrendingRepository
from app.schemas import (
    LocalAuthUser,
    LocalCategoriesPayload,
    LocalCategoryItem,
    LocalDashboardStats,
    LocalRecommendation,
    LocalRepoItem,
    LocalStatus,
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


@router.get("/trending", response_model=list[LocalTrendingRepo], summary="热榜列表")
def list_trending(
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[LocalTrendingRepo]:
    stmt = (
        select(TrendingRepository)
        .order_by(TrendingRepository.stars_today.desc(), TrendingRepository.stars.desc())
        .limit(limit)
    )
    rows = list(db.execute(stmt).scalars().all())
    items: list[LocalTrendingRepo] = []
    for row in rows:
        owner = row.owner or _split_repo_id(row.id)[0]
        items.append(
            LocalTrendingRepo(
                id=row.id,
                owner=owner,
                name=row.name,
                description=row.description,
                language=row.language,
                stars=row.stars or 0,
                starsToday=row.stars_today or 0,
                url=row.html_url,
            )
        )
    return items


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
                owner=owner or None,
                name=name or None,
                description=description,
                language=language,
                stars=stars,
                score=row.score or 0.0,
                reason=row.reason,
                basedOn=_parse_based_on(row.based_on),
                url=url,
            )
        )
    return items


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
