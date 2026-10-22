"""任务接口 `/api/tasks/*` —— 与 Cloudflare 边缘 Worker 的集成契约。

- 入队接口一律返回 `202 {"taskId": "..."}`（camelCase）；
- 当设置了 `INTERNAL_TOKEN` 时，所有接口必须携带 `X-Internal-Token` 请求头；
- `GET /api/tasks/{task_id}` 返回任务状态（pending / started / success / failure）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.config import get_settings
from app.schemas import TaskEnqueued, TaskStatus
from app.tasks.celery_app import celery_app
from app.tasks.jobs import (
    crawl_trending,
    daily_push,
    generate_recommendations,
    summarize_readmes,
    sync_repositories,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def require_internal_token(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    """内部鉴权依赖：INTERNAL_TOKEN 未配置时不启用（本地开发）；配置后严格校验。"""
    expected = (get_settings().INTERNAL_TOKEN or "").strip()
    if not expected:
        return
    if x_internal_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


@router.post(
    "/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    dependencies=[Depends(require_internal_token)],
    summary="入队：GitHub 仓库同步（完成后自动排队摘要）",
)
async def enqueue_sync(
    include_starred: bool = Query(default=True),
    with_summary: bool = Query(default=True),
) -> TaskEnqueued:
    task = sync_repositories.delay(include_starred=include_starred, with_summary=with_summary)
    return TaskEnqueued(taskId=task.id)


@router.post(
    "/summarize",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    dependencies=[Depends(require_internal_token)],
    summary="入队：README 摘要批量生成",
)
async def enqueue_summarize(
    repo_id: list[str] | None = Query(default=None, description="仅处理指定仓库，可重复传"),
    limit: int = Query(default=200, ge=1, le=1000),
    batch_size: int = Query(default=10, ge=1, le=50),
    force: bool = Query(default=False, description="已有摘要也重新生成"),
    max_chars: int = Query(default=800, ge=200, le=4000),
    source: str = Query(default="my", pattern="^(my|trending|all)$", description="摘要来源"),
) -> TaskEnqueued:
    task = summarize_readmes.delay(
        repo_ids=repo_id,
        limit=limit,
        batch_size=batch_size,
        force=force,
        max_chars=max_chars,
        source=source,
    )
    return TaskEnqueued(taskId=task.id)


@router.post(
    "/crawl-trending",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    dependencies=[Depends(require_internal_token)],
    summary="入队：热榜抓取（github / gitee / all）",
)
async def enqueue_crawl_trending(
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


@router.post(
    "/generate-recommendations",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    dependencies=[Depends(require_internal_token)],
    summary="入队：推荐生成",
)
async def enqueue_generate_recommendations(
    user_id: str | None = Query(default=None),
    top_k: int = Query(default=20, ge=1, le=100),
) -> TaskEnqueued:
    task = generate_recommendations.delay(user_id=user_id, top_k=top_k)
    return TaskEnqueued(taskId=task.id)


@router.post(
    "/daily-push",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    dependencies=[Depends(require_internal_token)],
    summary="入队：每日推送准备",
)
async def enqueue_daily_push() -> TaskEnqueued:
    task = daily_push.delay()
    return TaskEnqueued(taskId=task.id)


@router.get(
    "/{task_id}",
    response_model=TaskStatus,
    dependencies=[Depends(require_internal_token)],
    summary="查询任务状态",
)
async def get_task_status(task_id: str) -> TaskStatus:
    """查询任务状态；结果后端（Redis）不可用时降级返回 unknown。"""
    try:
        result = celery_app.AsyncResult(task_id)
        state = str(result.state).lower()
        payload = TaskStatus(taskId=task_id, status=state)
        if result.successful():
            payload.result = result.result
        elif result.failed():
            payload.error = str(result.result)[:500]
        elif state in ("progress", "started") and isinstance(result.info, dict):
            payload.progress = result.info
        return payload
    except Exception as exc:  # noqa: BLE001 - 后端不可用属于预期降级路径
        logger.warning("任务状态查询失败 %s: %s", task_id, exc)
        return TaskStatus(taskId=task_id, status="unknown", error=f"任务状态暂不可查: {str(exc)[:200]}")
