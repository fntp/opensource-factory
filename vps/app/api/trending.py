"""热榜接口：列表查询、详情与抓取入队。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import TrendingRepository
from app.schemas import TaskEnqueued, TrendingRepoDetail, TrendingRepoOut
from app.tasks.jobs import crawl_trending

router = APIRouter(prefix="/api/trending", tags=["trending"])


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
