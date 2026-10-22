"""推送去重与静默策略测试（M4-07）。

覆盖：时间解析 / 跨午夜静默、去重窗口与跨通道、每日上限、事件幂等、
`daily_push` 任务接入、策略 API 与内部鉴权。全部使用本地 SQLite，不访问网络。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect, select

from app.config import Settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import PushEvent, Recommendation
from app.services.push_policy import (
    build_dedupe_key,
    build_event_key,
    evaluate_push,
    is_quiet_hours,
    next_allowed_at,
    parse_clock,
    policy_status,
    record_push_event,
)
from app.tasks import jobs


def _cfg(**overrides) -> Settings:
    """构造固定策略配置（显式参数优先于测试环境变量）。"""
    values = {
        "PUSH_POLICY_ENABLED": True,
        "PUSH_QUIET_HOURS_START": "22:00",
        "PUSH_QUIET_HOURS_END": "08:00",
        "PUSH_TIMEZONE": "Asia/Shanghai",
        "PUSH_DAILY_LIMIT": 3,
        "PUSH_DEDUPE_DAYS": 7,
        "PUSH_DEDUPE_CROSS_CHANNEL": True,
        "PUSH_RETRY_INTERVAL_MINUTES": 30,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    _cleanup(session)
    yield session
    _cleanup(session)
    session.close()


def _cleanup(session) -> None:
    session.execute(delete(PushEvent).where(PushEvent.user_id.like("push-test%")))
    session.execute(delete(Recommendation).where(Recommendation.user_id.like("push-test%")))
    session.commit()


def _seed_rec(
    db,
    suffix: str,
    *,
    user_id: str = "push-test-user",
    status: str = "qualified",
) -> Recommendation:
    row = Recommendation(
        id=f"push-test-rec-{suffix}",
        user_id=user_id,
        repo_id=f"push-test/{suffix}",
        score=0.8,
        match_score=0.8,
        quality_score=0.8,
        reason="测试推荐",
        status=status,
    )
    db.add(row)
    db.commit()
    return row


def test_parse_clock_and_keys() -> None:
    assert parse_clock("22:00").hour == 22
    assert parse_clock("08:05:30").minute == 5
    assert parse_clock("bad", None) is None
    assert parse_clock("25:00", None) is None
    assert parse_clock("", None) is None

    cfg = _cfg()
    assert build_dedupe_key("u1", "owner/repo") == "u1:owner/repo"
    key = build_event_key("u1", "owner/repo", "bark", datetime(2026, 10, 22, 2, 0), cfg)
    assert key == "u1:owner/repo:bark:2026-10-22"


def test_quiet_hours_cross_midnight_and_next_allowed() -> None:
    cfg = _cfg()
    # 2026-10-22 15:00 UTC = 23:00 Asia/Shanghai
    assert is_quiet_hours(datetime(2026, 10, 22, 15, 0), cfg) is True
    # 07:59 / 08:00 边界（结束时间不静默）
    assert is_quiet_hours(datetime(2026, 10, 21, 23, 59), cfg) is True
    assert is_quiet_hours(datetime(2026, 10, 22, 0, 0), cfg) is False
    # 12:00 不静默
    assert is_quiet_hours(datetime(2026, 10, 22, 4, 0), cfg) is False
    assert next_allowed_at(datetime(2026, 10, 22, 15, 0), cfg) == datetime(
        2026, 10, 23, 0, 0
    )
    assert next_allowed_at(datetime(2026, 10, 22, 4, 0), cfg) is None


def test_quiet_window_can_be_disabled() -> None:
    cfg = _cfg(PUSH_QUIET_HOURS_START="", PUSH_QUIET_HOURS_END="")
    assert is_quiet_hours(datetime(2026, 10, 22, 15, 0), cfg) is False


def test_dedupe_window_and_cross_channel(db) -> None:
    now = datetime(2026, 10, 22, 2, 0)  # 10:00 Asia/Shanghai
    cfg = _cfg(PUSH_DAILY_LIMIT=0)
    record_push_event(
        db,
        user_id="push-test-user",
        repo_id="push-test/repo",
        channel="bark",
        status="sent",
        now=now - timedelta(days=2),
        settings=cfg,
    )
    db.commit()

    decision = evaluate_push(
        db,
        user_id="push-test-user",
        repo_id="push-test/repo",
        channel="inapp",
        now=now,
        settings=cfg,
    )
    assert decision["allowed"] is False
    assert decision["reason"] == "duplicate_repo"
    assert decision["existingEventId"]

    # 关闭跨通道去重后，不同通道允许；同通道仍命中去重
    same_channel_cfg = _cfg(PUSH_DAILY_LIMIT=0, PUSH_DEDUPE_CROSS_CHANNEL=False)
    assert evaluate_push(
        db,
        user_id="push-test-user",
        repo_id="push-test/repo",
        channel="inapp",
        now=now,
        settings=same_channel_cfg,
    )["allowed"] is True
    assert evaluate_push(
        db,
        user_id="push-test-user",
        repo_id="push-test/repo",
        channel="bark",
        now=now,
        settings=same_channel_cfg,
    )["reason"] == "duplicate_repo"

    # 窗口过期后允许再次推送
    assert evaluate_push(
        db,
        user_id="push-test-user",
        repo_id="push-test/repo",
        channel="inapp",
        now=now + timedelta(days=8),
        settings=cfg,
    )["allowed"] is True


def test_daily_limit_counts_active_events_only(db) -> None:
    now = datetime(2026, 10, 22, 2, 0)
    cfg = _cfg(PUSH_DAILY_LIMIT=2, PUSH_DEDUPE_DAYS=0)
    record_push_event(
        db,
        user_id="push-test-user",
        repo_id="push-test/a",
        channel="inapp",
        status="sent",
        now=now,
        settings=cfg,
    )
    record_push_event(
        db,
        user_id="push-test-user",
        repo_id="push-test/b",
        channel="inapp",
        status="failed",
        now=now,
        settings=cfg,
    )
    db.commit()

    # 只有 sent 的 a 占额度，failed 的 b 不占
    allowed = evaluate_push(
        db,
        user_id="push-test-user",
        repo_id="push-test/c",
        channel="inapp",
        now=now,
        settings=cfg,
    )
    assert allowed["allowed"] is True
    assert allowed["dailyUsed"] == 1

    record_push_event(
        db,
        user_id="push-test-user",
        repo_id="push-test/c",
        channel="inapp",
        status="sent",
        now=now,
        settings=cfg,
    )
    db.commit()
    blocked = evaluate_push(
        db,
        user_id="push-test-user",
        repo_id="push-test/d",
        channel="inapp",
        now=now,
        settings=cfg,
    )
    assert blocked["allowed"] is False
    assert blocked["reason"] == "daily_limit"


def test_record_push_event_is_idempotent_and_status_only_rises(db) -> None:
    now = datetime(2026, 10, 22, 2, 0)
    cfg = _cfg()
    first = record_push_event(
        db,
        user_id="push-test-user",
        repo_id="push-test/repo",
        channel="bark",
        status="prepared",
        now=now,
        settings=cfg,
    )
    second = record_push_event(
        db,
        user_id="push-test-user",
        repo_id="push-test/repo",
        channel="bark",
        status="sent",
        now=now + timedelta(minutes=1),
        settings=cfg,
    )
    third = record_push_event(
        db,
        user_id="push-test-user",
        repo_id="push-test/repo",
        channel="bark",
        status="skipped",
        reason="late_skip",
        now=now + timedelta(minutes=2),
        settings=cfg,
    )
    db.commit()

    assert first["created"] is True
    assert second["created"] is False
    assert second["status"] == "sent"
    assert third["status"] == "sent"  # 不允许降级
    row = db.execute(
        select(PushEvent).where(PushEvent.user_id == "push-test-user")
    ).scalar_one()
    assert row.status == "sent"
    assert row.sent_at == now + timedelta(minutes=1)


def test_daily_push_normal_path_marks_pushed_and_records_event(db) -> None:
    _seed_rec(db, "normal")
    result = jobs.daily_push()
    assert result["status"] == "ok"
    assert result["pushed"] == 1

    db.expire_all()
    row = db.get(Recommendation, "push-test-rec-normal")
    assert row.status == "pushed"
    event = db.execute(
        select(PushEvent).where(PushEvent.user_id == "push-test-user")
    ).scalar_one()
    assert event.status == "prepared"
    assert event.repo_id == "push-test/normal"


def test_daily_push_duplicate_marks_expired(db) -> None:
    _seed_rec(db, "dup")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    record_push_event(
        db,
        user_id="push-test-user",
        repo_id="push-test/dup",
        channel="bark",
        status="sent",
        now=now - timedelta(days=1),
        settings=_cfg(),
    )
    db.commit()

    result = jobs.daily_push()

    assert result["pushed"] == 0
    assert result["expired"] == 1
    assert result["skippedReasons"]["duplicate_repo"] == 1
    db.expire_all()
    assert db.get(Recommendation, "push-test-rec-dup").status == "expired"


def test_daily_push_daily_limit_keeps_qualified(db) -> None:
    _seed_rec(db, "limit-a")
    _seed_rec(db, "limit-b")
    cfg = _cfg(
        PUSH_DAILY_LIMIT=1,
        PUSH_DEDUPE_DAYS=0,
        PUSH_QUIET_HOURS_START="",
        PUSH_QUIET_HOURS_END="",
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    record_push_event(
        db,
        user_id="push-test-user",
        repo_id="push-test/other",
        channel="inapp",
        status="sent",
        now=now,
        settings=cfg,
    )
    db.commit()

    original = jobs.get_settings
    jobs.get_settings = lambda: cfg
    try:
        result = jobs.daily_push()
    finally:
        jobs.get_settings = original

    assert result["pushed"] == 0
    assert result["deferred"] == 2
    assert result["skippedReasons"]["daily_limit"] == 2
    db.expire_all()
    assert db.get(Recommendation, "push-test-rec-limit-a").status == "qualified"
    assert db.get(Recommendation, "push-test-rec-limit-b").status == "qualified"


def test_daily_push_silenced_keeps_qualified(db) -> None:
    _seed_rec(db, "quiet")
    # 构造一个覆盖当前本地时刻的静默窗口，避免测试受运行时间影响
    from app.services.push_policy import _local_now

    local = _local_now(datetime.now(timezone.utc).replace(tzinfo=None), "Asia/Shanghai")
    cfg = _cfg(
        PUSH_QUIET_HOURS_START=(local - timedelta(hours=1)).strftime("%H:%M"),
        PUSH_QUIET_HOURS_END=(local + timedelta(hours=1)).strftime("%H:%M"),
    )
    original = jobs.get_settings
    jobs.get_settings = lambda: cfg
    try:
        result = jobs.daily_push()
    finally:
        jobs.get_settings = original

    assert result["status"] == "silenced"
    assert result["deferred"] == 1
    assert result["nextAllowedAt"]
    db.expire_all()
    assert db.get(Recommendation, "push-test-rec-quiet").status == "qualified"
    assert db.execute(select(PushEvent)).scalars().all() == []


def test_policy_status_snapshot(db) -> None:
    now = datetime(2026, 10, 22, 2, 0)
    cfg = _cfg()
    record_push_event(
        db,
        user_id="push-test-user",
        repo_id="push-test/repo",
        channel="inapp",
        status="sent",
        now=now,
        settings=cfg,
    )
    db.commit()

    status = policy_status(db, now=now, settings=cfg)
    assert status["enabled"] is True
    assert status["quietHours"]["start"] == "22:00"
    assert status["quietHours"]["end"] == "08:00"
    assert status["quietHours"]["active"] is False
    assert status["limits"]["dailyLimit"] == 3
    assert status["today"]["sent"] == 1
    assert status["today"]["repos"] == 1
    assert len(status["recentEvents"]) == 1


def test_push_events_table_created(db) -> None:
    assert "push_events" in inspect(db.bind).get_table_names()


def test_policy_api_check_and_events(db) -> None:
    with TestClient(app) as client:
        status_resp = client.get("/api/push/policy/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["enabled"] is True

        check_resp = client.post(
            "/api/push/policy/check",
            json={"userId": "push-test-api", "repoId": "push-test/api", "channel": "inapp"},
        )
        assert check_resp.status_code == 200
        assert check_resp.json()["allowed"] is True

        event_resp = client.post(
            "/api/push/policy/events",
            json={
                "userId": "push-test-api",
                "repoId": "push-test/api",
                "channel": "bark",
                "status": "sent",
            },
        )
        assert event_resp.status_code == 201
        body = event_resp.json()
        assert body["created"] is True
        assert body["status"] == "sent"

        duplicate = client.post(
            "/api/push/policy/check",
            json={"userId": "push-test-api", "repoId": "push-test/api", "channel": "inapp"},
        )
        assert duplicate.json()["allowed"] is False
        assert duplicate.json()["reason"] == "duplicate_repo"

        events = client.get(
            "/api/push/policy/events",
            params={"userId": "push-test-api", "status": "sent"},
        )
        assert events.status_code == 200
        assert events.json()["count"] == 1


def test_policy_api_requires_internal_token(monkeypatch) -> None:
    import app.security as security_api

    class _FakeSettings:
        INTERNAL_TOKEN = "policy-secret"

    monkeypatch.setattr(security_api, "get_settings", lambda: _FakeSettings())
    with TestClient(app) as client:
        unauthorized = client.get("/api/push/policy/status")
        authorized = client.get(
            "/api/push/policy/status", headers={"X-Internal-Token": "policy-secret"}
        )
    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
