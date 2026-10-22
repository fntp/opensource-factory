"""通知通道接口（M4-04 Telegram）。

- `GET /api/notifications/telegram/status`：通道开关 / 配置状态 / 最近一次送达；
- `POST /api/notifications/telegram/test`：同步发送一条测试消息，便于启用前验证。

两个接口均受 `X-Internal-Token` 保护（未配置 INTERNAL_TOKEN 时本地开发放行）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.tasks import require_internal_token
from app.db import get_db
from app.models import TelegramDelivery
from app.schemas import (
    TelegramDeliveryOut,
    TelegramSendResponse,
    TelegramStatusOut,
    TelegramTestRequest,
)
from app.services.telegram import (
    TelegramError,
    TelegramNotConfigured,
    mask_chat_id,
    send_test_message,
    status_snapshot,
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _delivery_out(row: TelegramDelivery) -> TelegramDeliveryOut:
    """送达记录输出：chat id 脱敏，错误信息已是脱敏后的文本。"""
    return TelegramDeliveryOut(
        id=row.id,
        chatId=mask_chat_id(row.chat_id),
        kind=row.kind,
        status=row.status,
        itemCount=row.item_count,
        messageCount=row.message_count,
        messageId=row.message_id,
        error=row.error,
        createdAt=row.created_at,
        finishedAt=row.finished_at,
    )


@router.get(
    "/telegram/status",
    response_model=TelegramStatusOut,
    dependencies=[Depends(require_internal_token)],
    summary="Telegram 通道状态",
)
def telegram_status(db: Session = Depends(get_db)) -> TelegramStatusOut:
    snapshot = status_snapshot(db)
    last = snapshot.pop("lastDelivery")
    return TelegramStatusOut(
        **snapshot,
        lastDelivery=_delivery_out(last) if last is not None else None,
    )


@router.post(
    "/telegram/test",
    response_model=TelegramSendResponse,
    dependencies=[Depends(require_internal_token)],
    summary="发送 Telegram 测试消息",
)
def telegram_test(
    payload: TelegramTestRequest | None = None,
    db: Session = Depends(get_db),
) -> TelegramSendResponse:
    try:
        result = send_test_message(db, text=payload.text if payload else None)
    except TelegramNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    except TelegramError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from None
    return TelegramSendResponse(ok=True, **result)
