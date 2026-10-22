"""数据保留与隐私（M9-06）：本地镜像删除、保留期清理与内部接口。"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import Base, SessionLocal, init_db
from app.main import app
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
from app.services.privacy_retention import (
    PRIVACY_POLICY_VERSION,
    cleanup_expired_data,
    purge_user_data,
    retention_status,
)

NOW = datetime(2026, 10, 22, 12, 0, 0)


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def _recommendation(rec_id: str, user_id: str, created_at: datetime, status: str = "new"):
    return Recommendation(
        id=rec_id,
        user_id=user_id,
        repo_id=f"owner/{rec_id}",
        status=status,
        created_at=created_at,
    )


def _privacy_settings(**overrides) -> Settings:
    values = {
        "PRIVACY_RECOMMENDATION_RETENTION_DAYS": 90,
        "PRIVACY_SAVED_RECOMMENDATION_RETENTION_DAYS": 365,
        "PRIVACY_EVALUATION_RUN_RETENTION_DAYS": 180,
        "PRIVACY_PUSH_EVENT_RETENTION_DAYS": 180,
        "PRIVACY_PUSH_DELIVERY_RETENTION_DAYS": 365,
        "PRIVACY_EVENT_RETENTION_DAYS": 365,
    }
    values.update(overrides)
    return Settings(**values)


def test_purge_user_data_removes_all_local_rows_and_audits() -> None:
    db = _session()
    try:
        db.add(User(id="privacy-u1", username="alice"))
        db.add(_recommendation("rec-u1", "privacy-u1", NOW))
        db.add(
            RecommendationEvaluationRun(
                id="eval-u1", user_id="privacy-u1", status="completed", created_at=NOW
            )
        )
        db.add(
            PushEvent(
                id="event-u1",
                user_id="privacy-u1",
                repo_id="owner/repo",
                dedupe_key="privacy-u1:owner/repo",
                event_key="privacy-u1:owner/repo:inapp:2026-10-22",
            )
        )
        db.add(
            PushDelivery(
                id="delivery-u1",
                channel="email",
                target="alice@example.com",
                user_id="privacy-u1",
            )
        )
        db.add(PushReceipt(id="receipt-u1", delivery_id="delivery-u1", status="delivered"))
        db.commit()

        result = purge_user_data(db, "privacy-u1")

        assert result["status"] == "ok"
        assert result["policyVersion"] == PRIVACY_POLICY_VERSION
        assert result["total"] == 6
        assert result["deleted"]["users"] == 1
        assert result["deleted"]["pushReceipts"] == 1
        assert db.execute(select(User).where(User.id == "privacy-u1")).first() is None
        assert (
            db.execute(select(Recommendation).where(Recommendation.user_id == "privacy-u1")).first()
            is None
        )
        assert (
            db.execute(
                select(RecommendationEvaluationRun).where(
                    RecommendationEvaluationRun.user_id == "privacy-u1"
                )
            ).first()
            is None
        )
        assert db.execute(select(PushEvent).where(PushEvent.user_id == "privacy-u1")).first() is None
        assert (
            db.execute(select(PushDelivery).where(PushDelivery.user_id == "privacy-u1")).first()
            is None
        )
        audit = db.execute(select(PrivacyEvent).where(PrivacyEvent.event_type == "delete")).scalar_one()
        assert audit.actor_hash != "privacy-u1"
        assert "privacy-u1" not in audit.detail
        assert "deleted" in audit.detail
    finally:
        db.close()


def test_cleanup_respects_retention_windows_and_dry_run() -> None:
    db = _session()
    try:
        db.add_all(
            [
                _recommendation("old-unsaved", "privacy-u2", NOW - timedelta(days=100)),
                _recommendation(
                    "old-saved", "privacy-u2", NOW - timedelta(days=400), status="saved"
                ),
                _recommendation("recent-unsaved", "privacy-u2", NOW - timedelta(days=10)),
                RecommendationEvaluationRun(
                    id="old-eval",
                    user_id="privacy-u2",
                    created_at=NOW - timedelta(days=200),
                ),
                PushEvent(
                    id="old-event",
                    user_id="privacy-u2",
                    repo_id="owner/repo",
                    dedupe_key="privacy-u2:owner/repo",
                    event_key="privacy-u2:owner/repo:inapp:2026-01-01",
                    created_at=NOW - timedelta(days=200),
                ),
                PushDelivery(
                    id="old-delivery",
                    channel="email",
                    target="alice@example.com",
                    user_id="privacy-u2",
                    created_at=NOW - timedelta(days=400),
                ),
                EmailDelivery(
                    id="old-email",
                    recipient="alice@example.com",
                    dedupe_key="privacy-email-old",
                    created_at=NOW - timedelta(days=400),
                ),
                TelegramDelivery(
                    id="old-telegram",
                    chat_id="123",
                    dedupe_key="privacy-telegram-old",
                    created_at=NOW - timedelta(days=400),
                ),
                PrivacyEvent(
                    id="pe_old",
                    event_type="export",
                    detail="{}",
                    created_at=NOW - timedelta(days=400),
                ),
            ]
        )
        db.commit()

        dry = cleanup_expired_data(db, now=NOW, settings=_privacy_settings(), dry_run=True)
        assert dry["status"] == "dry_run"
        assert dry["deleted"]["recommendationsUnsaved"] == 1
        assert dry["deleted"]["recommendationsSaved"] == 1
        assert dry["deleted"]["recommendationEvaluationRuns"] == 1
        assert dry["deleted"]["pushEvents"] == 1
        assert dry["deleted"]["pushDeliveries"] == 1
        assert dry["deleted"]["emailDeliveries"] == 1
        assert dry["deleted"]["telegramDeliveries"] == 1
        assert dry["deleted"]["privacyEvents"] == 1
        assert db.execute(select(Recommendation)).scalars().all()

        result = cleanup_expired_data(db, now=NOW, settings=_privacy_settings())
        assert result["status"] == "ok"
        assert result["total"] >= 8
        remaining = {
            row.id for row in db.execute(select(Recommendation)).scalars().all()
        }
        assert remaining == {"recent-unsaved"}
        assert db.execute(select(RecommendationEvaluationRun)).first() is None
        assert db.execute(select(PushEvent)).first() is None
        assert db.execute(select(PushDelivery)).first() is None
        assert db.execute(select(EmailDelivery)).first() is None
        assert db.execute(select(TelegramDelivery)).first() is None
        audit = db.execute(
            select(PrivacyEvent).where(PrivacyEvent.event_type == "retention_cleanup")
        ).scalar_one()
        assert audit.actor_hash is None
        assert "total" in audit.detail
    finally:
        db.close()


def test_retention_status_reports_pending_counts() -> None:
    db = _session()
    try:
        db.add(_recommendation("status-old", "privacy-u3", NOW - timedelta(days=100)))
        db.add(_recommendation("status-recent", "privacy-u3", NOW - timedelta(days=1)))
        db.commit()

        status = retention_status(db, now=NOW, settings=_privacy_settings())
        assert status["enabled"] is True
        assert status["policyVersion"] == PRIVACY_POLICY_VERSION
        assert status["retentionDays"]["recommendationsUnsaved"] == 90
        assert status["pending"]["recommendationsUnsaved"] == 1
        assert status["pendingTotal"] >= 1
    finally:
        db.close()


def test_internal_privacy_api_purge_and_cleanup() -> None:
    init_db()
    user_id = "req0983-api-user"
    db = SessionLocal()
    try:
        db.execute(Recommendation.__table__.delete().where(Recommendation.user_id == user_id))
        db.execute(User.__table__.delete().where(User.id == user_id))
        db.add(User(id=user_id, username="api-user"))
        db.add(_recommendation("api-rec", user_id, NOW))
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.post(
            "/api/privacy/purge-user",
            json={"userId": user_id, "login": "api-user"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["deleted"]["users"] == 1

        cleanup = client.post("/api/privacy/cleanup", json={"dryRun": True})
        assert cleanup.status_code == 200
        assert cleanup.json()["status"] == "dry_run"

        status = client.get("/api/privacy/retention")
        assert status.status_code == 200
        assert status.json()["policyVersion"] == PRIVACY_POLICY_VERSION
