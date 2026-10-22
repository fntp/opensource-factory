"""统一推送记录与回执测试（M4-08）。

覆盖：目标脱敏、记录创建 / 过滤 / 分页 / 统计、回执状态机与幂等、
Bark / Telegram / Email 三个通道的接入，以及 API 鉴权。全部离线运行。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import Settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import (
    EmailDelivery,
    PushDelivery,
    PushReceipt,
    Recommendation,
    TelegramDelivery,
    TrendingRepository,
)
from app.services.bark import BarkResult, dispatch_bark_notifications, send_bark_test
from app.services.email_channel import EmailSendResult, send_digest as send_email_digest
from app.services.push_records import (
    apply_receipt,
    create_delivery,
    delivery_detail,
    delivery_stats,
    list_deliveries,
    mask_email,
    mask_target,
)
from app.services.telegram import send_digest as send_telegram_digest
import app.services.telegram as telegram_module

NOW = datetime(2026, 10, 22, 1, 5, 0)


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    _cleanup(session)
    yield session
    _cleanup(session)
    session.close()


def _cleanup(session) -> None:
    session.execute(delete(PushReceipt))
    session.execute(delete(PushDelivery))
    session.execute(delete(TelegramDelivery))
    session.execute(delete(EmailDelivery))
    session.execute(
        delete(Recommendation).where(Recommendation.user_id.like("push-test%"))
    )
    session.execute(
        delete(TrendingRepository).where(TrendingRepository.id.like("push-test/%"))
    )
    session.commit()


def _seed_recommendation(db, suffix: str = "alpha") -> Recommendation:
    repo_id = f"push-test/{suffix}"
    db.add(
        TrendingRepository(
            id=repo_id,
            platform="github",
            name=suffix,
            html_url=f"https://github.com/{repo_id}",
            stars_today=128,
            description="推送记录测试仓库",
            tech_stack="Python",
        )
    )
    rec = Recommendation(
        id=f"push-rec-{suffix}",
        user_id="push-test-user",
        repo_id=repo_id,
        score=0.6,
        match_score=0.8,
        quality_score=0.7,
        reason="测试推荐理由",
        status="pushed",
        created_at=NOW,
    )
    db.add(rec)
    db.commit()
    return rec


# ── 脱敏 ──────────────────────────────────────────────────────


def test_mask_target_and_email():
    assert mask_email("reader@test.local") == "r***@test.local"
    assert mask_email("a@b.com, other@example.com") == "a***@b.com, o***@example.com"
    assert mask_target("123456789", channel="telegram") == "12***89"
    assert mask_target("reader@test.local", channel="email") == "r***@test.local"
    assert mask_target("OpenFactory", channel="bark", target_type="group") == "OpenFactory"
    assert mask_target("") == ""


# ── 记录与查询 ────────────────────────────────────────────────


def test_create_list_filter_and_stats(db):
    create_delivery(
        db,
        channel="email",
        kind="digest",
        target="reader@test.local",
        target_type="email",
        status="sent",
        item_count=3,
        subject="每日精选",
        dedupe_key="email:digest:2026-10-22",
    )
    create_delivery(
        db,
        channel="telegram",
        kind="digest",
        target="123456789",
        target_type="chat",
        status="failed",
        item_count=2,
        error="Telegram 超时",
    )
    create_delivery(
        db,
        channel="bark",
        kind="single",
        target="OpenFactory",
        target_type="group",
        status="skipped",
        item_count=1,
        error="dry_run",
    )

    all_rows = list_deliveries(db)
    assert all_rows["total"] == 3
    assert all_rows["items"][0]["targetMasked"] != "reader@test.local"

    email_rows = list_deliveries(db, channel="email")
    assert email_rows["total"] == 1
    assert email_rows["items"][0]["channel"] == "email"
    assert "reader@test.local" not in email_rows["items"][0]["dedupeKey"]
    assert "reader@test.local" not in email_rows["items"][0]["targetMasked"]

    failed_rows = list_deliveries(db, status="failed")
    assert failed_rows["total"] == 1

    searched = list_deliveries(db, q="每日")
    assert searched["total"] == 1

    paged = list_deliveries(db, page=2, page_size=2)
    assert paged["count"] == 1
    assert paged["total"] == 3

    stats = delivery_stats(db, days=30)
    assert stats["total"] == 3
    assert stats["byChannel"] == {"email": 1, "telegram": 1, "bark": 1}
    assert stats["byStatus"]["sent"] == 1
    assert stats["byStatus"]["failed"] == 1
    assert stats["byStatus"]["skipped"] == 1
    assert stats["deliveryRate"] == 0.0  # 无 delivered 记录


def test_delivery_detail_and_receipt_state_machine(db):
    delivery = create_delivery(
        db,
        channel="email",
        kind="digest",
        target="reader@test.local",
        target_type="email",
        status="sent",
        item_count=1,
    )
    accepted, _ = apply_receipt(
        db,
        delivery_id=delivery.id,
        status="accepted",
        source="provider",
        external_id="evt-1",
        detail="250 accepted",
        occurred_at=NOW,
    )
    assert accepted.status == "sent"
    assert accepted.receipt_status == "accepted"

    delivered, _ = apply_receipt(
        db,
        delivery_id=delivery.id,
        status="delivered",
        source="provider",
        external_id="evt-2",
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert delivered.status == "delivered"
    assert delivered.receipt_status == "delivered"
    assert delivered.delivered_at is not None

    # 迟到的 accepted 不降级，但回执流水保留
    late, _ = apply_receipt(
        db,
        delivery_id=delivery.id,
        status="accepted",
        source="provider",
        external_id="evt-3",
        occurred_at=NOW - timedelta(minutes=1),
    )
    assert late.status == "delivered"
    assert late.receipt_status == "delivered"

    detail = delivery_detail(db, delivery.id)
    assert detail is not None
    assert len(detail["receipts"]) == 3

    # 相同 external_id + status 幂等
    _, first_receipt = apply_receipt(
        db,
        delivery_id=delivery.id,
        status="delivered",
        source="provider",
        external_id="evt-2",
    )
    detail_again = delivery_detail(db, delivery.id)
    assert len(detail_again["receipts"]) == 3
    assert first_receipt.external_id == "evt-2"


def test_bounced_receipt_marks_channel_record_failed(db):
    email_row = EmailDelivery(
        id="email-delivery-1",
        recipient="reader@test.local",
        kind="digest",
        status="sent",
        item_count=1,
        subject="每日精选",
        dedupe_key="email:digest:test",
        finished_at=NOW,
    )
    db.add(email_row)
    db.commit()
    delivery = create_delivery(
        db,
        channel="email",
        kind="digest",
        target="reader@test.local",
        target_type="email",
        status="sent",
        source_id=email_row.id,
    )

    updated, _ = apply_receipt(
        db,
        delivery_id=delivery.id,
        status="bounced",
        source="provider",
        external_id="bounce-1",
        detail="550 mailbox unavailable",
    )
    assert updated.status == "failed"
    assert updated.receipt_status == "bounced"
    db.refresh(email_row)
    assert email_row.status == "failed"


# ── 通道接入 ──────────────────────────────────────────────────


class _FakeBarkClient:
    def __init__(self, result: BarkResult) -> None:
        self.result = result

    def send(self, message):  # noqa: ANN001 - 测试替身
        return self.result

    def close(self) -> None:
        pass


def _bark_settings(**overrides):
    values = {
        "BARK_ENABLED": True,
        "BARK_DEVICE_KEY": "test-device-key",
        "BARK_SERVER_URL": "https://bark.test",
        "BARK_GROUP": "OpenFactory",
        "BARK_LEVEL": "active",
        "BARK_MAX_PER_RUN": 5,
        "BARK_DRY_RUN": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_bark_dispatch_and_test_create_records(db):
    _seed_recommendation(db, "bark")
    result = dispatch_bark_notifications(
        db,
        settings=_bark_settings(),
        client=_FakeBarkClient(BarkResult(ok=True)),
    )
    assert result["sent"] == 1
    rows = list_deliveries(db, channel="bark")["items"]
    assert len(rows) == 1
    assert rows[0]["status"] == "sent"
    assert rows[0]["kind"] == "single"
    assert rows[0]["sourceId"] == "push-rec-bark"

    send_bark_test(
        settings=_bark_settings(),
        client=_FakeBarkClient(BarkResult(ok=True)),
        db=db,
    )
    assert list_deliveries(db, channel="bark", kind="test")["total"] == 1


def test_bark_dispatch_failure_creates_failed_record(db):
    _seed_recommendation(db, "bark-fail")
    result = dispatch_bark_notifications(
        db,
        settings=_bark_settings(),
        client=_FakeBarkClient(BarkResult(ok=False, error="HTTP 503")),
    )
    assert result["failed"] == 1
    row = list_deliveries(db, channel="bark")["items"][0]
    assert row["status"] == "failed"
    assert "HTTP 503" in (row["error"] or "")


def test_telegram_digest_creates_record(db, monkeypatch):
    _seed_recommendation(db, "telegram")
    settings = SimpleNamespace(
        TELEGRAM_ENABLED=True,
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_CHAT_ID="123456789",
        TELEGRAM_API_BASE="https://api.telegram.test",
        TELEGRAM_TIMEOUT_SECONDS=1.0,
        TELEGRAM_MAX_RETRIES=0,
        TELEGRAM_RETRY_BASE_SECONDS=0.0,
        TELEGRAM_DAILY_LIMIT=10,
        TELEGRAM_DIGEST_WINDOW_HOURS=24,
    )
    monkeypatch.setattr(telegram_module, "get_settings", lambda: settings)

    class _Sender:
        def send_parts(self, parts, *, chat_id=None):
            return SimpleNamespace(message_ids=["101"], parts=len(parts))

    result = send_telegram_digest(db, now=NOW, client=_Sender())
    assert result["status"] == "sent"
    rows = list_deliveries(db, channel="telegram")["items"]
    assert len(rows) == 1
    assert rows[0]["status"] == "sent"
    assert rows[0]["sourceId"] == result["deliveryId"]
    assert rows[0]["messageId"] == "101"


def test_email_digest_creates_record(db):
    _seed_recommendation(db, "email")
    settings = Settings(
        _env_file=None,
        EMAIL_ENABLED=True,
        EMAIL_SMTP_HOST="smtp.test.local",
        EMAIL_SMTP_PORT=587,
        EMAIL_SMTP_USERNAME="bot@test.local",
        EMAIL_SMTP_PASSWORD="secret",
        EMAIL_FROM="bot@test.local",
        EMAIL_TO="reader@test.local",
        EMAIL_STARTTLS=True,
        EMAIL_SSL=False,
        EMAIL_MAX_RETRIES=0,
        EMAIL_RETRY_BASE_SECONDS=0.0,
    )

    class _Sender:
        def send(self, content, recipients):
            return EmailSendResult(ok=True, message_id="<fake@test>", attempts=1)

    result = send_email_digest(
        db, settings=settings, sender=_Sender(), now=NOW
    )
    assert result["status"] == "sent"
    rows = list_deliveries(db, channel="email")["items"]
    assert len(rows) == 1
    assert rows[0]["status"] == "sent"
    assert rows[0]["sourceId"] == result["deliveryId"]
    assert rows[0]["targetMasked"] == "r***@test.local"


# ── API ───────────────────────────────────────────────────────


def test_api_records_list_detail_and_receipt(db):
    delivery = create_delivery(
        db,
        channel="telegram",
        kind="digest",
        target="123456789",
        target_type="chat",
        status="sent",
        item_count=2,
    )
    client = TestClient(app)
    listed = client.get("/api/push/records", params={"channel": "telegram"})
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == delivery.id

    stats = client.get("/api/push/records/stats", params={"days": 30})
    assert stats.status_code == 200
    assert stats.json()["total"] == 1

    detail = client.get(f"/api/push/records/{delivery.id}")
    assert detail.status_code == 200
    assert detail.json()["receipts"] == []

    receipt = client.post(
        "/api/push/receipts",
        json={
            "deliveryId": delivery.id,
            "status": "delivered",
            "source": "manual",
            "externalId": "manual-1",
            "detail": "人工确认已送达",
        },
    )
    assert receipt.status_code == 200
    assert receipt.json()["delivery"]["status"] == "delivered"
    assert receipt.json()["receipt"]["source"] == "manual"

    missing = client.get("/api/push/records/not-found")
    assert missing.status_code == 404
    missing_receipt = client.post(
        "/api/push/receipts",
        json={"deliveryId": "not-found", "status": "delivered"},
    )
    assert missing_receipt.status_code == 404


def test_api_requires_internal_token(monkeypatch):
    import app.api.tasks as tasks_module

    monkeypatch.setattr(
        tasks_module, "get_settings", lambda: SimpleNamespace(INTERNAL_TOKEN="secret")
    )
    client = TestClient(app)
    assert client.get("/api/push/records").status_code == 401
    assert (
        client.get(
            "/api/push/records", headers={"X-Internal-Token": "secret"}
        ).status_code
        == 200
    )
