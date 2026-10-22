"""通知通道接口 `/api/notifications/*`（M4-05 Email）。

- `GET /api/notifications/email/status`：通道开关、配置完整性与最近一次送达；
- `POST /api/notifications/email/test`：发送测试邮件，验证 SMTP 配置；
- 与 `/api/tasks/*` 一致，配置 `INTERNAL_TOKEN` 后要求 `X-Internal-Token`。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.tasks import require_internal_token
from app.config import get_settings
from app.db import get_db
from app.schemas import EmailSendResponse, EmailStatusOut, EmailTestRequest
from app.services.email_channel import (
    EmailConfigError,
    delivery_to_dict,
    get_email_status,
    send_test_email,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_internal_token)],
)


@router.get(
    "/email/status",
    response_model=EmailStatusOut,
    summary="Email 通道状态",
)
def email_status(db: Session = Depends(get_db)) -> EmailStatusOut:
    """返回通道开关与配置快照；SMTP 密码 / 用户名不会出现在响应中。"""
    data = get_email_status(db)
    last = data.pop("lastDelivery", None)
    return EmailStatusOut(**data, lastDelivery=delivery_to_dict(last) if last else None)


@router.post(
    "/email/test",
    response_model=EmailSendResponse,
    summary="发送 Email 测试邮件",
)
def email_test(
    payload: EmailTestRequest | None = None,
    db: Session = Depends(get_db),
) -> EmailSendResponse:
    """发送一封测试邮件。

    通道关闭或配置不完整时返回 409（便于前端提示先补配置）；
    SMTP 投递失败仍返回 200 + `ok=false`，错误信息已脱敏，便于排查。
    """
    settings = get_settings()
    if not settings.EMAIL_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email 通道未启用（EMAIL_ENABLED=false）",
        )
    request = payload or EmailTestRequest()
    try:
        result = send_test_email(
            db,
            to=request.to,
            subject=request.subject,
            body=request.body,
        )
    except EmailConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return EmailSendResponse(**result)
