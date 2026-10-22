"""统一推送记录与回执服务（M4-08）。

职责：

- 把 Bark / Telegram / Email 三个通道的投递结果写入 `push_deliveries`；
- 维护 `push_receipts` 回执流水，支持服务商回调 / 人工补记；
- 提供列表、详情、统计查询；
- 所有对外字段统一脱敏，不落 Bark device key、Bot token、SMTP 密码。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    EmailDelivery,
    PushDelivery,
    PushReceipt,
    TelegramDelivery,
)

logger = logging.getLogger(__name__)

VALID_CHANNELS = ("bark", "telegram", "email")
VALID_STATUSES = ("pending", "sent", "delivered", "failed", "skipped")
VALID_RECEIPT_STATUSES = ("accepted", "delivered", "bounced", "failed")
VALID_RECEIPT_SOURCES = ("provider", "manual", "system")
MAX_ERROR_LENGTH = 500
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


class PushRecordError(ValueError):
    """推送记录参数或状态非法。"""


class PushDeliveryNotFound(PushRecordError):
    """指定的投递记录不存在。"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clean(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def mask_email(value: Any) -> str:
    """邮箱脱敏：保留首字符与域名，例如 `a***@example.com`。"""
    text = str(value or "").strip()
    if not text:
        return ""
    parts: list[str] = []
    for item in text.replace(";", ",").split(","):
        address = item.strip()
        if not address:
            continue
        if "@" not in address:
            parts.append(mask_target(address))
            continue
        local, domain = address.rsplit("@", 1)
        if not local:
            parts.append(f"***@{domain}")
        elif len(local) <= 1:
            parts.append(f"{local}***@{domain}")
        else:
            parts.append(f"{local[0]}***@{domain}")
    return ", ".join(parts)


def mask_target(target: Any, *, channel: str = "", target_type: str = "") -> str:
    """按目标类型脱敏；Bark group 名不是机密，原样返回。"""
    text = str(target or "").strip()
    if not text:
        return ""
    if target_type == "group" or channel == "bark":
        return text
    if "@" in text or target_type == "email" or channel == "email":
        return mask_email(text)
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def _validate_channel(channel: str) -> None:
    if channel not in VALID_CHANNELS:
        raise PushRecordError(f"未知推送通道：{channel}")


def _validate_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise PushRecordError(f"未知投递状态：{status}")


def create_delivery(
    db: Session,
    *,
    channel: str,
    kind: str = "digest",
    target: str = "",
    target_type: str = "",
    status: str = "pending",
    item_count: int = 0,
    message_count: int = 0,
    message_id: Optional[str] = None,
    subject: Optional[str] = None,
    dedupe_key: str = "",
    error: Optional[str] = None,
    source_id: str = "",
    user_id: Optional[str] = None,
    sent_at: Optional[datetime] = None,
) -> PushDelivery:
    """创建一条统一投递记录并提交。"""
    _validate_channel(channel)
    _validate_status(status)
    now = _utcnow()
    terminal = status in ("sent", "delivered", "failed", "skipped")
    row = PushDelivery(
        id=uuid4().hex,
        channel=channel,
        kind=_clean(kind, 16) or "digest",
        target=_clean(target, 255),
        target_type=_clean(target_type, 16),
        status=status,
        item_count=max(0, int(item_count or 0)),
        message_count=max(0, int(message_count or 0)),
        message_id=(_clean(message_id, 255) or None) if message_id else None,
        subject=(_clean(subject, 255) or None) if subject else None,
        dedupe_key=_clean(dedupe_key, 255),
        error=(_clean(error, MAX_ERROR_LENGTH) or None) if error else None,
        source_id=_clean(source_id, 64),
        user_id=(_clean(user_id, 128) or None) if user_id else None,
        created_at=now,
        sent_at=sent_at or (now if status in ("sent", "delivered") else None),
        finished_at=now if terminal else None,
        delivered_at=now if status == "delivered" else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def finish_delivery(
    db: Session,
    delivery: PushDelivery,
    *,
    status: str,
    message_count: Optional[int] = None,
    message_id: Optional[str] = None,
    error: Optional[str] = None,
) -> PushDelivery:
    """回写投递结果并提交。"""
    _validate_status(status)
    now = _utcnow()
    delivery.status = status
    if message_count is not None:
        delivery.message_count = max(0, int(message_count))
    if message_id is not None:
        delivery.message_id = _clean(message_id, 255) or None
    if error is not None:
        delivery.error = _clean(error, MAX_ERROR_LENGTH) or None
    if status in ("sent", "delivered") and delivery.sent_at is None:
        delivery.sent_at = now
    if status in ("sent", "delivered", "failed", "skipped"):
        delivery.finished_at = now
    if status == "delivered" and delivery.delivered_at is None:
        delivery.delivered_at = now
    db.commit()
    db.refresh(delivery)
    return delivery


def record_delivery(
    db: Session,
    *,
    channel: str,
    kind: str = "digest",
    target: str = "",
    target_type: str = "",
    ok: bool,
    item_count: int = 0,
    message_count: int = 0,
    message_id: Optional[str] = None,
    subject: Optional[str] = None,
    dedupe_key: str = "",
    error: Optional[str] = None,
    source_id: str = "",
    user_id: Optional[str] = None,
) -> PushDelivery:
    """一次性写入已完成的投递记录（Email 等同步发送场景）。"""
    return create_delivery(
        db,
        channel=channel,
        kind=kind,
        target=target,
        target_type=target_type,
        status="sent" if ok else "failed",
        item_count=item_count,
        message_count=message_count,
        message_id=message_id,
        subject=subject,
        dedupe_key=dedupe_key,
        error=error,
        source_id=source_id,
        user_id=user_id,
    )


def find_by_source(
    db: Session, *, channel: str, source_id: str
) -> Optional[PushDelivery]:
    if not source_id:
        return None
    return (
        db.execute(
            select(PushDelivery)
            .where(
                PushDelivery.channel == channel,
                PushDelivery.source_id == source_id,
            )
            .order_by(PushDelivery.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def finish_by_source(
    db: Session,
    *,
    channel: str,
    source_id: str,
    status: str,
    message_count: Optional[int] = None,
    message_id: Optional[str] = None,
    error: Optional[str] = None,
) -> Optional[PushDelivery]:
    """按通道原表 id 回写统一记录；找不到时静默返回 None。"""
    row = find_by_source(db, channel=channel, source_id=source_id)
    if row is None:
        return None
    return finish_delivery(
        db,
        row,
        status=status,
        message_count=message_count,
        message_id=message_id,
        error=error,
    )


def _mask_embedded_target(text: Optional[str], row: PushDelivery) -> Optional[str]:
    """把自由文本里出现的原始目标替换为脱敏值（幂等键 / 错误 / 回执详情）。"""
    if not text or not row.target:
        return text
    masked = mask_target(row.target, channel=row.channel, target_type=row.target_type)
    value = str(text)
    parts = [part.strip() for part in row.target.replace(";", ",").split(",") if part.strip()]
    for part in sorted(parts, key=len, reverse=True):
        part_masked = mask_target(
            part, channel=row.channel, target_type=row.target_type
        )
        value = value.replace(part, part_masked)
    if row.target in value:
        value = value.replace(row.target, masked)
    return value


def delivery_to_dict(row: PushDelivery, *, mask: bool = True) -> dict[str, Any]:
    target_masked = (
        mask_target(row.target, channel=row.channel, target_type=row.target_type)
        if mask
        else row.target
    )
    return {
        "id": row.id,
        "channel": row.channel,
        "kind": row.kind,
        "targetMasked": target_masked,
        "targetType": row.target_type,
        "status": row.status,
        "itemCount": row.item_count,
        "messageCount": row.message_count,
        "messageId": row.message_id,
        "subject": row.subject,
        "dedupeKey": _mask_embedded_target(row.dedupe_key, row) if mask else row.dedupe_key,
        "receiptStatus": row.receipt_status or None,
        "receiptDetail": _mask_embedded_target(row.receipt_detail, row)
        if mask
        else row.receipt_detail,
        "error": _mask_embedded_target(row.error, row) if mask else row.error,
        "attempts": row.attempts,
        "sourceId": row.source_id,
        "userId": row.user_id,
        "createdAt": row.created_at,
        "sentAt": row.sent_at,
        "finishedAt": row.finished_at,
        "deliveredAt": row.delivered_at,
    }


def receipt_to_dict(row: PushReceipt) -> dict[str, Any]:
    return {
        "id": row.id,
        "deliveryId": row.delivery_id,
        "channel": row.channel,
        "status": row.status,
        "source": row.source,
        "externalId": row.external_id or None,
        "detail": row.detail,
        "occurredAt": row.occurred_at,
        "createdAt": row.created_at,
    }


def list_deliveries(
    db: Session,
    *,
    channel: Optional[str] = None,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    user_id: Optional[str] = None,
    q: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """分页查询投递记录，按创建时间倒序。"""
    conditions: list[Any] = []
    if channel:
        _validate_channel(channel)
        conditions.append(PushDelivery.channel == channel)
    if status:
        _validate_status(status)
        conditions.append(PushDelivery.status == status)
    if kind:
        conditions.append(PushDelivery.kind == kind)
    if user_id:
        conditions.append(PushDelivery.user_id == user_id)
    if date_from:
        conditions.append(PushDelivery.created_at >= date_from)
    if date_to:
        conditions.append(PushDelivery.created_at <= date_to)
    if q:
        like = f"%{q.strip()}%"
        conditions.append(
            or_(
                PushDelivery.subject.like(like),
                PushDelivery.dedupe_key.like(like),
                PushDelivery.source_id.like(like),
            )
        )

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    count_stmt = select(func.count()).select_from(PushDelivery)
    rows_stmt = select(PushDelivery)
    for condition in conditions:
        count_stmt = count_stmt.where(condition)
        rows_stmt = rows_stmt.where(condition)

    total = int(db.execute(count_stmt).scalar() or 0)
    rows = list(
        db.execute(
            rows_stmt.order_by(
                PushDelivery.created_at.desc(), PushDelivery.id.desc()
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return {
        "total": total,
        "count": len(rows),
        "page": page,
        "pageSize": page_size,
        "items": [delivery_to_dict(row) for row in rows],
    }


def get_delivery(db: Session, delivery_id: str) -> Optional[PushDelivery]:
    return db.get(PushDelivery, delivery_id)


def list_receipts(db: Session, delivery_id: str) -> list[PushReceipt]:
    return list(
        db.execute(
            select(PushReceipt)
            .where(PushReceipt.delivery_id == delivery_id)
            .order_by(PushReceipt.occurred_at.asc(), PushReceipt.created_at.asc())
        )
        .scalars()
        .all()
    )


def delivery_detail(db: Session, delivery_id: str) -> Optional[dict[str, Any]]:
    row = get_delivery(db, delivery_id)
    if row is None:
        return None
    data = delivery_to_dict(row)
    data["receipts"] = [receipt_to_dict(item) for item in list_receipts(db, delivery_id)]
    return data


def delivery_stats(
    db: Session,
    *,
    days: int = 30,
    channel: Optional[str] = None,
) -> dict[str, Any]:
    """按窗口统计投递量、状态分布与送达率。"""
    days = max(1, min(int(days or 30), 365))
    since = _utcnow() - timedelta(days=days)
    conditions: list[Any] = [PushDelivery.created_at >= since]
    if channel:
        _validate_channel(channel)
        conditions.append(PushDelivery.channel == channel)

    by_channel: dict[str, int] = {}
    for name, count in db.execute(
        select(PushDelivery.channel, func.count())
        .where(*conditions)
        .group_by(PushDelivery.channel)
    ):
        by_channel[str(name)] = int(count)

    by_status: dict[str, int] = {}
    for name, count in db.execute(
        select(PushDelivery.status, func.count())
        .where(*conditions)
        .group_by(PushDelivery.status)
    ):
        by_status[str(name)] = int(count)

    receipt_conditions: list[Any] = [PushReceipt.occurred_at >= since]
    if channel:
        receipt_conditions.append(PushReceipt.channel == channel)
    receipts: dict[str, int] = {}
    for name, count in db.execute(
        select(PushReceipt.status, func.count())
        .where(*receipt_conditions)
        .group_by(PushReceipt.status)
    ):
        receipts[str(name)] = int(count)

    total = sum(by_status.values())
    denominator = total - by_status.get("skipped", 0) - by_status.get("pending", 0)
    delivered = by_status.get("delivered", 0)
    delivery_rate = round(delivered / denominator, 4) if denominator > 0 else 0.0
    return {
        "windowDays": days,
        "total": total,
        "byChannel": by_channel,
        "byStatus": by_status,
        "receipts": receipts,
        "deliveryRate": delivery_rate,
    }


def _receipt_rank(status: str) -> int:
    return {"accepted": 1, "delivered": 2, "bounced": 2, "failed": 2}.get(status, 0)


def _sync_channel_record(
    db: Session, delivery: PushDelivery, receipt_status: str
) -> None:
    """把回执结果同步到通道原表，避免两套状态不一致。"""
    if not delivery.source_id:
        return
    if delivery.channel == "email":
        row = db.get(EmailDelivery, delivery.source_id)
        if row is not None and receipt_status in ("bounced", "failed"):
            row.status = "failed"
        elif row is not None and receipt_status == "delivered" and row.status == "failed":
            row.status = "sent"
    elif delivery.channel == "telegram":
        row = db.get(TelegramDelivery, delivery.source_id)
        if row is not None and receipt_status in ("bounced", "failed"):
            row.status = "failed"
        elif row is not None and receipt_status == "delivered" and row.status == "failed":
            row.status = "sent"


def apply_receipt(
    db: Session,
    *,
    delivery_id: str,
    status: str,
    source: str = "provider",
    external_id: str = "",
    detail: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
) -> tuple[PushDelivery, PushReceipt]:
    """写入一条回执并更新投递状态。

    幂等：相同 `delivery_id + external_id + status` 已存在时直接返回原回执。
    迟到回执不会把 `delivered` 降级为 `accepted` / `bounced` / `failed`。
    """
    if status not in VALID_RECEIPT_STATUSES:
        raise PushRecordError(f"未知回执状态：{status}")
    if source not in VALID_RECEIPT_SOURCES:
        raise PushRecordError(f"未知回执来源：{source}")
    delivery = get_delivery(db, delivery_id)
    if delivery is None:
        raise PushDeliveryNotFound(f"投递记录不存在：{delivery_id}")

    clean_external = _clean(external_id, 255)
    if clean_external:
        existing = (
            db.execute(
                select(PushReceipt)
                .where(
                    PushReceipt.delivery_id == delivery_id,
                    PushReceipt.external_id == clean_external,
                    PushReceipt.status == status,
                )
                .limit(1)
            )
            .scalars()
            .first()
        )
        if existing is not None:
            return delivery, existing

    now = _utcnow()
    happened = occurred_at or now
    receipt = PushReceipt(
        id=uuid4().hex,
        delivery_id=delivery_id,
        channel=delivery.channel,
        status=status,
        source=source,
        external_id=clean_external,
        detail=_clean(detail, MAX_ERROR_LENGTH) or None,
        occurred_at=happened,
        created_at=now,
    )
    db.add(receipt)

    current = delivery.receipt_status or ""
    stale = False
    if current == "delivered" and status != "delivered":
        stale = True
    elif current in ("bounced", "failed") and status == "accepted":
        stale = True
    elif current and _receipt_rank(status) < _receipt_rank(current):
        stale = True

    if not stale:
        delivery.receipt_status = status
        delivery.receipt_detail = _clean(detail, MAX_ERROR_LENGTH) or None
        if status == "delivered":
            delivery.status = "delivered"
            delivery.delivered_at = happened
            if delivery.sent_at is None:
                delivery.sent_at = happened
        elif status in ("bounced", "failed"):
            if delivery.status != "delivered":
                delivery.status = "failed"
        elif status == "accepted":
            if delivery.status == "pending":
                delivery.status = "sent"
                delivery.sent_at = happened
        _sync_channel_record(db, delivery, status)

    db.commit()
    db.refresh(delivery)
    db.refresh(receipt)
    logger.info(
        "推送回执: delivery=%s channel=%s status=%s source=%s stale=%s",
        delivery_id,
        delivery.channel,
        status,
        source,
        stale,
    )
    return delivery, receipt


def build_receipt_response(
    delivery: PushDelivery, receipt: PushReceipt
) -> dict[str, Any]:
    return {
        "ok": True,
        "delivery": delivery_to_dict(delivery),
        "receipt": receipt_to_dict(receipt),
    }
