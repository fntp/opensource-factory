"""VPS 本地镜像数据保留与删除（REQ-202610-0983 / M9-06）。

边缘 D1 是主数据源；VPS 只保留推荐 / 推送 / 评估等本地镜像。
本模块负责两件事：

- ``purge_user_data``：边缘删除账号后，按 user_id 清理本地镜像（内部接口调用）；
- ``cleanup_expired_data``：每日 Celery 任务按保留期清理过期数据，并写隐私审计事件。

安全约定：审计事件只保存用户 id 的 SHA-256 与聚合计数，不保存原始 id、邮箱、
令牌或推送目标。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import (
    EmailDelivery,
    PrivacyEvent,
    PushDelivery,
    PushEvent,
    PushReceipt,
    Recommendation,
    RecommendationEvaluationRun,
    TelegramDelivery,
    User,
)

# 与 edge/src/privacy/policy.ts 的 PRIVACY_POLICY_VERSION 保持一致
PRIVACY_POLICY_VERSION = "2026-10-22"


def _utcnow() -> datetime:
    """与模型层一致的无时区 UTC 时间。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _cutoff(now: datetime, days: int) -> datetime:
    return now - timedelta(days=max(0, int(days)))


def _actor_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


def _record_event(
    db: Session,
    event_type: str,
    detail: dict[str, Any],
    *,
    actor_hash: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """写入隐私审计事件；调用方负责 commit。"""
    import uuid

    db.add(
        PrivacyEvent(
            id=f"pe_{uuid.uuid4().hex}",
            event_type=event_type,
            actor_hash=actor_hash,
            detail=json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
            created_at=now or _utcnow(),
        )
    )


def purge_user_data(db: Session, user_id: str) -> dict[str, Any]:
    """删除指定用户在 VPS 本地镜像中的全部关联数据。

    ``my_repositories`` 等全局仓库镜像没有 user_id，属于工作区共享数据，不在此删除。
    """
    counts: dict[str, int] = {}

    # 先删回执，避免 push_deliveries 删除后留下无法归属的流水
    delivery_ids = select(PushDelivery.id).where(PushDelivery.user_id == user_id)
    counts["pushReceipts"] = (
        db.execute(delete(PushReceipt).where(PushReceipt.delivery_id.in_(delivery_ids))).rowcount
        or 0
    )

    for key, model, column in (
        ("recommendations", Recommendation, Recommendation.user_id),
        ("recommendationEvaluationRuns", RecommendationEvaluationRun, RecommendationEvaluationRun.user_id),
        ("pushEvents", PushEvent, PushEvent.user_id),
        ("pushDeliveries", PushDelivery, PushDelivery.user_id),
        ("users", User, User.id),
    ):
        counts[key] = db.execute(delete(model).where(column == user_id)).rowcount or 0

    total = sum(counts.values())
    _record_event(
        db,
        "delete",
        {"policyVersion": PRIVACY_POLICY_VERSION, "deleted": counts, "total": total},
        actor_hash=_actor_hash(user_id),
    )
    db.commit()
    return {
        "status": "ok",
        "policyVersion": PRIVACY_POLICY_VERSION,
        "userId": user_id,
        "deleted": counts,
        "total": total,
    }


def _retention_targets(
    now: datetime, settings: Settings
) -> list[tuple[str, Any, Any]]:
    """返回 (key, model, where 条件) 列表，供清理与状态查询共用。"""
    return [
        (
            "recommendationsUnsaved",
            Recommendation,
            (Recommendation.status != "saved")
            & (Recommendation.created_at < _cutoff(now, settings.PRIVACY_RECOMMENDATION_RETENTION_DAYS)),
        ),
        (
            "recommendationsSaved",
            Recommendation,
            (Recommendation.status == "saved")
            & (
                Recommendation.created_at
                < _cutoff(now, settings.PRIVACY_SAVED_RECOMMENDATION_RETENTION_DAYS)
            ),
        ),
        (
            "recommendationEvaluationRuns",
            RecommendationEvaluationRun,
            RecommendationEvaluationRun.created_at
            < _cutoff(now, settings.PRIVACY_EVALUATION_RUN_RETENTION_DAYS),
        ),
        (
            "pushEvents",
            PushEvent,
            PushEvent.created_at < _cutoff(now, settings.PRIVACY_PUSH_EVENT_RETENTION_DAYS),
        ),
        (
            "pushDeliveries",
            PushDelivery,
            PushDelivery.created_at
            < _cutoff(now, settings.PRIVACY_PUSH_DELIVERY_RETENTION_DAYS),
        ),
        (
            "emailDeliveries",
            EmailDelivery,
            EmailDelivery.created_at
            < _cutoff(now, settings.PRIVACY_PUSH_DELIVERY_RETENTION_DAYS),
        ),
        (
            "telegramDeliveries",
            TelegramDelivery,
            TelegramDelivery.created_at
            < _cutoff(now, settings.PRIVACY_PUSH_DELIVERY_RETENTION_DAYS),
        ),
        (
            "pushReceipts",
            PushReceipt,
            PushReceipt.occurred_at
            < _cutoff(now, settings.PRIVACY_PUSH_DELIVERY_RETENTION_DAYS),
        ),
        (
            "privacyEvents",
            PrivacyEvent,
            PrivacyEvent.created_at < _cutoff(now, settings.PRIVACY_EVENT_RETENTION_DAYS),
        ),
    ]


def cleanup_expired_data(
    db: Session,
    *,
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """按保留期清理本地镜像；dry_run 只统计不删除。"""
    current = now or _utcnow()
    config = settings or get_settings()
    targets = _retention_targets(current, config)

    counts: dict[str, int] = {}
    for key, model, condition in targets:
        if dry_run:
            counts[key] = int(
                db.execute(select(func.count()).select_from(model).where(condition)).scalar() or 0
            )
        else:
            counts[key] = db.execute(delete(model).where(condition)).rowcount or 0

    total = sum(counts.values())
    if not dry_run:
        # 清理后仍无归属的回执（例如历史数据缺 delivery）一并删除
        orphan_condition = PushReceipt.delivery_id.not_in(select(PushDelivery.id))
        counts["pushReceiptsOrphan"] = (
            db.execute(delete(PushReceipt).where(orphan_condition)).rowcount or 0
        )
        total = sum(counts.values())
        _record_event(
            db,
            "retention_cleanup",
            {"policyVersion": PRIVACY_POLICY_VERSION, "deleted": counts, "total": total},
            now=current,
        )
        db.commit()

    return {
        "status": "dry_run" if dry_run else "ok",
        "policyVersion": PRIVACY_POLICY_VERSION,
        "executedAt": current.isoformat(),
        "deleted": counts,
        "total": total,
    }


def retention_status(
    db: Session,
    *,
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """返回保留配置与待清理行数，供运维 / 内部接口查询。"""
    current = now or _utcnow()
    config = settings or get_settings()
    pending: dict[str, int] = {}
    for key, model, condition in _retention_targets(current, config):
        pending[key] = int(
            db.execute(select(func.count()).select_from(model).where(condition)).scalar() or 0
        )

    return {
        "enabled": bool(config.PRIVACY_RETENTION_ENABLED),
        "policyVersion": PRIVACY_POLICY_VERSION,
        "checkedAt": current.isoformat(),
        "retentionDays": {
            "recommendationsUnsaved": config.PRIVACY_RECOMMENDATION_RETENTION_DAYS,
            "recommendationsSaved": config.PRIVACY_SAVED_RECOMMENDATION_RETENTION_DAYS,
            "recommendationEvaluationRuns": config.PRIVACY_EVALUATION_RUN_RETENTION_DAYS,
            "pushEvents": config.PRIVACY_PUSH_EVENT_RETENTION_DAYS,
            "pushDeliveries": config.PRIVACY_PUSH_DELIVERY_RETENTION_DAYS,
            "privacyEvents": config.PRIVACY_EVENT_RETENTION_DAYS,
        },
        "pending": pending,
        "pendingTotal": sum(pending.values()),
    }
