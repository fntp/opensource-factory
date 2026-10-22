"""推送通道接口 `/api/push/*`（M4-03 Bark）。

- `GET  /api/push/bark/status`：通道状态与投递计数（不返回 device key）；
- `POST /api/push/bark/test`：同步发送测试通知；
- `POST /api/push/bark/dispatch`：入队投递任务。

所有写操作沿用 `X-Internal-Token` 内部鉴权。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.tasks import require_internal_token
from app.db import get_db
from app.schemas import BarkStatusOut, BarkTestOut, BarkTestRequest, TaskEnqueued
from app.services.bark import (
    BarkConfigError,
    bark_status,
    send_bark_test,
)
from app.tasks.jobs import send_bark_notifications

router = APIRouter(prefix="/api/push", tags=["push"])


@router.get(
    "/bark/status",
    response_model=BarkStatusOut,
    dependencies=[Depends(require_internal_token)],
    summary="Bark 通道状态",
)
def get_bark_status(db: Session = Depends(get_db)) -> BarkStatusOut:
    return BarkStatusOut(**bark_status(db))


@router.post(
    "/bark/test",
    response_model=BarkTestOut,
    dependencies=[Depends(require_internal_token)],
    summary="发送 Bark 测试通知",
)
def test_bark(
    payload: Optional[BarkTestRequest] = None,
) -> BarkTestOut:
    request = payload or BarkTestRequest()
    try:
        result = send_bark_test(
            title=request.title,
            body=request.body,
            url=request.url,
        )
    except BarkConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return BarkTestOut(
        ok=result.ok,
        statusCode=result.status_code,
        error=result.error,
    )


@router.post(
    "/bark/dispatch",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskEnqueued,
    dependencies=[Depends(require_internal_token)],
    summary="入队：Bark 推荐推送",
)
async def enqueue_bark_dispatch(
    user_id: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None, ge=1, le=100),
) -> TaskEnqueued:
    task = send_bark_notifications.delay(user_id=user_id, limit=limit)
    return TaskEnqueued(taskId=task.id)
