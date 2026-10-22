"""Bark 推送通道测试（M4-03）。

覆盖：地址 / 级别归一化、消息构建、HTTP 成功与各类失败、投递幂等与重试、
限额与用户过滤、dry-run、状态统计、测试接口与 API 契约。
全部使用 httpx.MockTransport，不访问网络。
"""
from __future__ import annotations

from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import Settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import Recommendation, TrendingRepository
from app.services.bark import (
    BarkClient,
    BarkConfigError,
    BarkMessage,
    bark_status,
    build_bark_payload,
    dispatch_bark_notifications,
    format_recommendation_message,
    normalize_level,
    normalize_server_url,
    send_bark_test,
)

USER = "bark-test-user"
OTHER_USER = "bark-test-other"


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    _cleanup(session)
    yield session
    _cleanup(session)
    session.close()


def _cleanup(session) -> None:
    session.execute(delete(Recommendation).where(Recommendation.user_id.like("bark-test%")))
    session.execute(
        delete(TrendingRepository).where(TrendingRepository.id.like("bark-test/%"))
    )
    session.commit()


def _settings(**overrides) -> Settings:
    base = {
        "BARK_ENABLED": True,
        "BARK_SERVER_URL": "https://bark.example.com/",
        "BARK_DEVICE_KEY": "device-key-123",
        "BARK_GROUP": "OpenFactory",
        "BARK_SOUND": "",
        "BARK_ICON": "",
        "BARK_LEVEL": "active",
        "BARK_TIMEOUT_SECONDS": 5,
        "BARK_MAX_PER_RUN": 5,
        "BARK_DRY_RUN": False,
    }
    base.update(overrides)
    return Settings(**base)


def _seed(
    db,
    suffix: str,
    *,
    user_id: str = USER,
    status: str = "pushed",
    quality: float = 0.9,
    score: float = 0.8,
    match: float = 0.82,
) -> Recommendation:
    repo_id = f"bark-test/{suffix}"
    db.add(
        TrendingRepository(
            id=repo_id,
            platform="github",
            name=suffix,
            html_url=f"https://github.com/{repo_id}",
            stars_today=12,
            description="一个用于测试的 Python 项目",
            tech_stack="Python / FastAPI",
        )
    )
    row = Recommendation(
        id=f"bark-rec-{suffix}",
        user_id=user_id,
        repo_id=repo_id,
        score=score,
        match_score=match,
        quality_score=quality,
        reason="与你收藏的 Python 项目相似",
        status=status,
        created_at=datetime(2026, 10, 22, 9, 0, 0),
    )
    db.add(row)
    db.commit()
    return row


def _client(settings: Settings, handler) -> BarkClient:
    return BarkClient(settings, transport=httpx.MockTransport(handler))


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"code": 200, "message": "success"})


def test_normalize_server_url_and_level() -> None:
    assert normalize_server_url("") == "https://api.day.app"
    assert normalize_server_url("bark.example.com/") == "https://bark.example.com"
    assert normalize_server_url("http://127.0.0.1:8080/") == "http://127.0.0.1:8080"
    assert normalize_level("timeSensitive") == "timeSensitive"
    assert normalize_level("TIME_SENSITIVE") == "timeSensitive"
    assert normalize_level("unknown") == "active"


def test_build_payload_includes_optional_fields() -> None:
    settings = _settings(BARK_SOUND="minuet.caf", BARK_ICON="https://example.com/icon.png")
    message = BarkMessage(
        title="owner/repo",
        body="项目简介",
        url="https://github.com/owner/repo",
        group="测试分组",
        level="passive",
    )
    payload = build_bark_payload(message, settings)
    assert payload["device_key"] == "device-key-123"
    assert payload["title"] == "owner/repo"
    assert payload["body"] == "项目简介"
    assert payload["group"] == "测试分组"
    assert payload["level"] == "passive"
    assert payload["url"] == "https://github.com/owner/repo"
    assert payload["sound"] == "minuet.caf"
    assert payload["icon"] == "https://example.com/icon.png"


def test_format_recommendation_message(db) -> None:
    row = _seed(db, "format")
    repo = db.get(TrendingRepository, row.repo_id)
    message = format_recommendation_message(row, repo, _settings())
    assert message.title == "bark-test/format"
    assert "一个用于测试的 Python 项目" in message.body
    assert "与你收藏的 Python 项目相似" in message.body
    assert "匹配度 82%" in message.body
    assert "今日 +12" in message.body
    assert message.url == "https://github.com/bark-test/format"


def test_client_success(db) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = request.read()
        return httpx.Response(200, json={"code": 200, "message": "success"})

    settings = _settings()
    result = _client(settings, handler).send(
        BarkMessage(title="标题", body="正文", url="https://example.com")
    )
    assert result.ok is True
    assert result.status_code == 200
    assert seen["url"] == "https://bark.example.com/push"
    assert b"device-key-123" in seen["payload"]


def test_client_http_error() -> None:
    result = _client(
        _settings(),
        lambda request: httpx.Response(500, json={"code": 500, "message": "boom"}),
    ).send(BarkMessage(title="标题", body="正文"))
    assert result.ok is False
    assert result.status_code == 500
    assert "HTTP 500" in (result.error or "")


def test_client_bark_code_error() -> None:
    result = _client(
        _settings(),
        lambda request: httpx.Response(200, json={"code": 400, "message": "invalid key"}),
    ).send(BarkMessage(title="标题", body="正文"))
    assert result.ok is False
    assert result.code == 400
    assert "code=400" in (result.error or "")


def test_client_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = _client(_settings(), handler).send(BarkMessage(title="标题", body="正文"))
    assert result.ok is False
    assert "请求失败" in (result.error or "")


def test_dispatch_marks_sent(db) -> None:
    _seed(db, "one")
    _seed(db, "two")
    result = dispatch_bark_notifications(
        db, settings=_settings(), client=_client(_settings(), _ok_handler)
    )
    assert result["status"] == "ok"
    assert result["candidates"] == 2
    assert result["sent"] == 2
    assert result["failed"] == 0
    rows = db.query(Recommendation).filter(Recommendation.user_id == USER).all()
    assert all(row.bark_sent_at is not None for row in rows)
    assert all(row.bark_error is None for row in rows)


def test_dispatch_failure_keeps_pending_and_retries(db) -> None:
    _seed(db, "fail")

    def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"code": 503, "message": "unavailable"})

    first = dispatch_bark_notifications(
        db, settings=_settings(), client=_client(_settings(), fail_handler)
    )
    assert first["status"] == "error"
    assert first["failed"] == 1
    row = db.get(Recommendation, "bark-rec-fail")
    assert row is not None
    assert row.bark_sent_at is None
    assert row.bark_error and "HTTP 503" in row.bark_error

    second = dispatch_bark_notifications(
        db, settings=_settings(), client=_client(_settings(), _ok_handler)
    )
    assert second["sent"] == 1
    db.refresh(row)
    assert row.bark_sent_at is not None
    assert row.bark_error is None


def test_dispatch_limit_and_user_filter(db) -> None:
    _seed(db, "high", quality=0.99)
    _seed(db, "low", quality=0.10)
    _seed(db, "other", user_id=OTHER_USER, quality=0.95)

    limited = dispatch_bark_notifications(
        db,
        user_id=USER,
        limit=1,
        settings=_settings(),
        client=_client(_settings(), _ok_handler),
    )
    assert limited["candidates"] == 1
    assert limited["sent"] == 1
    assert db.get(Recommendation, "bark-rec-high").bark_sent_at is not None
    assert db.get(Recommendation, "bark-rec-low").bark_sent_at is None
    assert db.get(Recommendation, "bark-rec-other").bark_sent_at is None


def test_dispatch_skips_when_disabled_or_missing_key(db) -> None:
    _seed(db, "skip")
    disabled = dispatch_bark_notifications(
        db, settings=_settings(BARK_ENABLED=False), client=_client(_settings(), _ok_handler)
    )
    assert disabled["status"] == "skipped"

    missing = dispatch_bark_notifications(
        db, settings=_settings(BARK_DEVICE_KEY=""), client=_client(_settings(), _ok_handler)
    )
    assert missing["status"] == "skipped"
    assert "BARK_DEVICE_KEY" in missing["reason"]
    assert db.get(Recommendation, "bark-rec-skip").bark_sent_at is None


def test_dispatch_dry_run(db) -> None:
    _seed(db, "dry")
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"code": 200})

    result = dispatch_bark_notifications(
        db,
        settings=_settings(BARK_DRY_RUN=True),
        client=_client(_settings(BARK_DRY_RUN=True), handler),
    )
    assert called is False
    assert result["status"] == "dry_run"
    assert result["skipped"] == 1
    assert result["previews"][0]["title"] == "bark-test/dry"
    assert db.get(Recommendation, "bark-rec-dry").bark_sent_at is None


def test_bark_status_counts(db) -> None:
    sent = _seed(db, "sent")
    sent.bark_sent_at = datetime(2026, 10, 22, 9, 5, 0)
    failed = _seed(db, "failed")
    failed.bark_error = "HTTP 500"
    _seed(db, "pending")
    db.commit()

    status = bark_status(db, _settings())
    assert status["enabled"] is True
    assert status["configured"] is True
    assert status["serverUrl"] == "https://bark.example.com"
    assert status["pending"] == 2
    assert status["sent"] == 1
    assert status["failed"] == 1
    assert status["lastError"] == "HTTP 500"
    assert "deviceKey" not in status


def test_send_bark_test_requires_config() -> None:
    with pytest.raises(BarkConfigError):
        send_bark_test(settings=_settings(BARK_ENABLED=False))
    with pytest.raises(BarkConfigError):
        send_bark_test(settings=_settings(BARK_DEVICE_KEY=""))


def test_send_bark_test_success() -> None:
    result = send_bark_test(
        title="测试", body="正文", settings=_settings(), client=_client(_settings(), _ok_handler)
    )
    assert result.ok is True


def test_api_status_and_dispatch(db, monkeypatch) -> None:
    monkeypatch.setattr("app.services.bark.get_settings", lambda: _settings())

    class _FakeTask:
        def delay(self, **kwargs):
            return type("FakeAsyncResult", (), {"id": "bark-task-1"})()

    monkeypatch.setattr("app.api.push.send_bark_notifications", _FakeTask())
    client = TestClient(app)
    response = client.get("/api/push/bark/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["serverUrl"] == "https://bark.example.com"
    assert "deviceKey" not in payload

    dispatched = client.post("/api/push/bark/dispatch", params={"limit": 1})
    assert dispatched.status_code == 202
    assert dispatched.json()["taskId"] == "bark-task-1"


def test_api_test_endpoint_returns_400_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.bark.get_settings", lambda: _settings(BARK_ENABLED=False)
    )
    client = TestClient(app)
    response = client.post("/api/push/bark/test", json={"title": "t", "body": "b"})
    assert response.status_code == 400
    assert "BARK_ENABLED" in response.json()["detail"]
