"""推送接口 `/api/push/*`（M4-03 Bark / M4-08 推送记录与回执）。

- `GET  /api/push/bark/status`：Bark 通道状态与投递计数（不返回 device key）；
- `POST /api/push/bark/test`：同步发送 Bark 测试通知；
- `POST /api/push/bark/dispatch`：入队 Bark 投递任务；
- `GET  /api/push/records`：统一投递记录列表（通道 / 状态 / 时间过滤 + 分页）；
- `GET  /api/push/records/stats`：投递量、状态分布与送达率；
- `GET  /api/push/records/{id}`：投递详情 + 回执时间线；
- `POST /api/push/receipts`：写入送达回执（服务商回调 / 人工补记）。

所有接口沿用 `X-Internal-Token` 内部鉴权。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.tasks import require_internal_token
from app.db import get_db
from app.schemas import (
    BarkStatusOut,
    BarkTestOut,
    BarkTestRequest,
    PushDeliveryDetailOut,
    PushReceiptCreate,
    PushReceiptResponse,
    PushRecordListOut,
    PushStatsOut,
    TaskEnqueued,
)
from app.services.bark import (
    BarkConfigError,
    bark_status,
    send_bark_test,
)
from app.services.push_records import (
    PushDeliveryNotFound,
    PushRecordError,
    apply_receipt,
    build_receipt_response,
    delivery_detail,
    delivery_stats,
    list_deliveries,
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
    db: Session = Depends(get_db),
) -> BarkTestOut:
    request = payload or BarkTestRequest()
    try:
        result = send_bark_test(
            title=request.title,
            body=request.body,
            url=request.url,
            db=db,
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


# ── 推送记录与回执（M4-08）────────────────────────────────────


@router.get(
    "/records",
    response_model=PushRecordListOut,
    dependencies=[Depends(require_internal_token)],
    summary="统一推送记录列表",
)
def list_push_records(
    channel: Optional[str] = Query(
        default=None, pattern="^(bark|telegram|email)$"
    ),
    delivery_status: Optional[str] = Query(
        default=None,
        alias="status",
        pattern="^(pending|sent|delivered|failed|skipped)$",
    ),
    kind: Optional[str] = Query(default=None, max_length=16),
    user_id: Optional[str] = Query(default=None, max_length=128),
    q: Optional[str] = Query(default=None, max_length=100),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PushRecordListOut:
    data = list_deliveries(
        db,
        channel=channel,
        status=delivery_status,
        kind=kind,
        user_id=user_id,
        q=q,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return PushRecordListOut(**data)


@router.get(
    "/records/stats",
    response_model=PushStatsOut,
    dependencies=[Depends(require_internal_token)],
    summary="推送投递统计",
)
def push_records_stats(
    days: int = Query(default=30, ge=1, le=365),
    channel: Optional[str] = Query(
        default=None, pattern="^(bark|telegram|email)$"
    ),
    db: Session = Depends(get_db),
) -> PushStatsOut:
    return PushStatsOut(**delivery_stats(db, days=days, channel=channel))


@router.get(
    "/records/{delivery_id}",
    response_model=PushDeliveryDetailOut,
    dependencies=[Depends(require_internal_token)],
    summary="推送投递详情（含回执时间线）",
)
def get_push_record(
    delivery_id: str,
    db: Session = Depends(get_db),
) -> PushDeliveryDetailOut:
    data = delivery_detail(db, delivery_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="投递记录不存在"
        )
    return PushDeliveryDetailOut(**data)


@router.post(
    "/receipts",
    response_model=PushReceiptResponse,
    dependencies=[Depends(require_internal_token)],
    summary="写入推送送达回执",
)
def create_push_receipt(
    payload: PushReceiptCreate,
    db: Session = Depends(get_db),
) -> PushReceiptResponse:
    try:
        delivery, receipt = apply_receipt(
            db,
            delivery_id=payload.deliveryId,
            status=payload.status,
            source=payload.source,
            external_id=payload.externalId or "",
            detail=payload.detail,
            occurred_at=payload.occurredAt,
        )
    except PushDeliveryNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except PushRecordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return PushReceiptResponse(**build_receipt_response(delivery, receipt))
