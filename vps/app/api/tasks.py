"""任务接口 `/api/tasks/*` —— 与 Cloudflare 边缘 Worker 的集成契约。

- 入队接口一律返回 `202 {"taskId": "..."}`（camelCase）；
- 当设置了 `INTERNAL_TOKEN` 时，所有接口必须携带 `X-Internal-Token` 请求头；
- `GET /api/tasks/{task_id}` 返回任务状态（pending / started / success / failure）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.config import get_settings
from app.db import SessionLocal
from app.models import VectorizationRun
from app.schemas import TaskEnqueued, TaskStatus, VectorizeEnqueued
from app.services.vector_pipeline import (
    RunFinished,
    RunNotFound,
    VectorRunError,
    create_run,
)
from app.tasks.celery_app import celery_app
from app.tasks.jobs import (
    crawl_trending,
    daily_push,
    evaluate_recommendations,
    generate_recommendations,
    sync_repositories,
    vectorize_repositories,
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
    summary="入队：GitHub 仓库同步",
)
async def enqueue_sync(include_starred: bool = Query(default=True)) -> TaskEnqueued:
    task = sync_repositories.delay(include_starred=include_starred)
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
    language: str | None = Query(default=None),
) -> TaskEnqueued:
    task = crawl_trending.delay(platform=platform, language=language)
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
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
) -> TaskEnqueued:
    task = generate_recommendations.delay(
        user_id=user_id, top_k=top_k, min_score=min_score
    )
    return TaskEnqueued(taskId=task.id)


@router.post(
    "/evaluate-recommendations",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    dependencies=[Depends(require_internal_token)],
    summary="入队：每日推荐评估（质量分 + 匹配度阈值）",
)
async def enqueue_evaluate_recommendations(
    user_id: str | None = Query(default=None),
    match_threshold: float | None = Query(default=None, ge=0.0, le=1.0),
    quality_threshold: float | None = Query(default=None, ge=0.0, le=1.0),
) -> TaskEnqueued:
    task = evaluate_recommendations.delay(
        user_id=user_id,
        match_threshold=match_threshold,
        quality_threshold=quality_threshold,
    )
    return TaskEnqueued(taskId=task.id)


@router.post(
    "/daily-push",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    dependencies=[Depends(require_internal_token)],
    summary="入队：每日推送准备（按用户偏好筛选）",
)
async def enqueue_daily_push(
    user_id: str | None = Query(default=None),
    respect_schedule: bool = Query(
        default=False, description="是否按用户推送时间窗口筛选（定时任务使用）"
    ),
) -> TaskEnqueued:
    task = daily_push.delay(
        user_id=user_id, respect_schedule=respect_schedule
    )
    return TaskEnqueued(taskId=task.id)


@router.post(
    "/vectorize",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=VectorizeEnqueued,
    dependencies=[Depends(require_internal_token)],
    summary="入队：向量化（收藏库 / 热榜 / 全部；支持续跑）",
)
async def enqueue_vectorize(
    scope: str = Query(default="all", pattern="^(my|trending|all)$"),
    limit: int | None = Query(default=None, ge=1, le=100000),
    batch_size: int | None = Query(default=None, ge=1, le=256),
    force: bool = Query(default=False),
    run_id: str | None = Query(default=None, description="失败运行的 id，用于断点续跑"),
) -> VectorizeEnqueued:
    db = SessionLocal()
    try:
        run = create_run(
            db,
            scope=scope,
            limit=limit,
            batch_size=batch_size,
            force=force,
            run_id=run_id,
        )
        active_run_id = run.id
    except RunNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RunFinished as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except VectorRunError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        db.close()

    try:
        task = vectorize_repositories.delay(run_id=active_run_id)
    except Exception as exc:  # noqa: BLE001 - 入队失败标记运行失败，便于人工重试
        db = SessionLocal()
        try:
            failed = db.get(VectorizationRun, active_run_id)
            if failed is not None:
                failed.status = "failed"
                failed.error = f"任务入队失败：{str(exc)[:200]}"
                db.commit()
        finally:
            db.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="向量化任务入队失败"
        ) from exc
    return VectorizeEnqueued(taskId=task.id, runId=active_run_id)


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
        return payload
    except Exception as exc:  # noqa: BLE001 - 后端不可用属于预期降级路径
        logger.warning("任务状态查询失败 %s: %s", task_id, exc)
        return TaskStatus(taskId=task_id, status="unknown", error=f"任务状态暂不可查: {str(exc)[:200]}")
