"""Telegram 推送通道测试（M4-04）。

覆盖：HTML 转义 / 分片、Bot API 成功与重试、错误脱敏、摘要取数 / 幂等 / 失败记录、
测试消息、状态接口与内部令牌鉴权。全部使用本地 SQLite 与 httpx.MockTransport，不访问网络。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.services.telegram as telegram_module
from app.db import SessionLocal, init_db
from app.main import app
from app.models import Recommendation, TelegramDelivery, TrendingRepository
from app.services.telegram import (
    DigestItem,
    TelegramClient,
    TelegramError,
    TelegramNotConfigured,
    TelegramSendResult,
    build_digest_messages,
    format_percent,
    mask_chat_id,
    send_digest,
    send_test_message,
    split_text,
)
from app.tasks.jobs import send_telegram_digest

NOW = datetime(2026, 10, 22, 1, 5, 0)


def _settings(**overrides):
    values = {
        "TELEGRAM_ENABLED": True,
        "TELEGRAM_BOT_TOKEN": "test-token-123456",
        "TELEGRAM_CHAT_ID": "123456789",
        "TELEGRAM_API_BASE": "https://api.telegram.test",
        "TELEGRAM_TIMEOUT_SECONDS": 1.0,
        "TELEGRAM_MAX_RETRIES": 2,
        "TELEGRAM_RETRY_BASE_SECONDS": 0.0,
        "TELEGRAM_DAILY_LIMIT": 10,
        "TELEGRAM_DIGEST_WINDOW_HOURS": 24,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    _cleanup(session)
    yield session
    _cleanup(session)
    session.close()


def _cleanup(session) -> None:
    session.execute(delete(Recommendation).where(Recommendation.user_id.like("tg-test%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like("tg-test/%")))
    session.execute(delete(TelegramDelivery))
    session.commit()


def _seed(db, suffix: str = "alpha", *, status: str = "pushed", created_at: datetime = NOW):
    repo_id = f"tg-test/{suffix}"
    repo = TrendingRepository(
        id=repo_id,
        platform="github",
        name=suffix,
        html_url=f"https://github.com/tg-test/{suffix}?a=1&b=2",
        stars_today=321,
        description="一个用于测试的 <b>仓库</b> 简介",
        tech_stack="Python / FastAPI",
    )
    rec = Recommendation(
        id=f"tg-rec-{suffix}",
        user_id="tg-test-user",
        repo_id=repo_id,
        score=0.61,
        match_score=0.82,
        quality_score=0.78,
        reason="与你的收藏相似度 82%，技术栈匹配 Python / FastAPI；<script>alert(1)</script>",
        status=status,
        created_at=created_at,
    )
    db.add(repo)
    db.add(rec)
    db.commit()
    return rec


class FakeSender:
    """测试替身：记录发送内容，按需返回 / 抛错。"""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.parts: list[list[str]] = []

    def send_parts(self, parts, *, chat_id=None) -> TelegramSendResult:
        self.parts.append(list(parts))
        if self.error:
            raise self.error
        return TelegramSendResult(message_ids=["101"], parts=len(parts))

    def send_text(self, text: str, *, chat_id=None) -> TelegramSendResult:
        return self.send_parts([text], chat_id=chat_id)


def test_mask_chat_id_and_format_percent():
    assert mask_chat_id("123456789") == "***6789"
    assert mask_chat_id("-1001234567890") == "***7890"
    assert mask_chat_id("") == ""
    assert format_percent(0.826) == "83%"
    assert format_percent(None) == "0%"


def test_split_text_prefers_line_boundaries():
    text = "a" * 5 + "\n" + "b" * 5 + "\n" + "c" * 5
    assert split_text(text, limit=12) == ["aaaaa\nbbbbb", "ccccc"]
    assert split_text("x" * 25, limit=10) == ["x" * 10, "x" * 10, "x" * 5]


def test_build_digest_messages_escapes_and_splits():
    items = [
        DigestItem(
            repo_id=f"tg-test/{index}",
            title=f"owner/repo-{index} & <x>",
            url=f"https://github.com/owner/repo-{index}?a=1&b=2",
            reason="理由 <script>alert(1)</script> " + "长" * 200,
            match_score=0.8,
            quality_score=0.7,
            stars_today=10,
            tech_stack="Python <FastAPI>",
        )
        for index in range(1, 21)
    ]
    messages = build_digest_messages(items, now=NOW)
    assert len(messages) > 1
    assert all(len(message) <= 4096 for message in messages)
    joined = "\n".join(messages)
    assert "<script>" not in joined
    assert "&lt;script&gt;" in joined
    assert "owner/repo-1 &amp; &lt;x&gt;" in joined
    assert "a=1&amp;b=2" in joined
    assert "每日精选" in messages[0]


def test_send_text_success():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    client = TelegramClient(
        token="token-abc",
        chat_id="123",
        api_base="https://api.telegram.test",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    result = client.send_text("hello")
    assert result.parts == 1
    assert result.message_ids == ["42"]
    assert len(calls) == 1
    assert calls[0].url.path == "/bottoken-abc/sendMessage"
    import json

    assert json.loads(calls[0].content)["parse_mode"] == "HTML"


def test_send_text_retries_429_then_succeeds():
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                json={"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 1}},
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

    client = TelegramClient(
        token="t",
        chat_id="1",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        max_retries=2,
    )
    assert client.send_text("hi").message_ids == ["7"]
    assert calls == 2
    assert sleeps == [1.0]


def test_send_text_retries_5xx_then_succeeds():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

    client = TelegramClient(
        token="t",
        chat_id="1",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        max_retries=2,
        retry_base=0.0,
    )
    assert client.send_text("hi").message_ids == ["9"]
    assert calls == 3


def test_send_text_5xx_exhausted_raises_retryable():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="unavailable")

    client = TelegramClient(
        token="t",
        chat_id="1",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        max_retries=1,
    )
    with pytest.raises(TelegramError) as exc_info:
        client.send_text("hi")
    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 503
    assert calls == 2


def test_send_text_4xx_does_not_retry_or_leak_token():
    calls = 0
    token = "super-secret-token"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})

    client = TelegramClient(
        token=token,
        chat_id="1",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        max_retries=3,
    )
    with pytest.raises(TelegramError) as exc_info:
        client.send_text("hi")
    assert calls == 1
    assert "chat not found" in str(exc_info.value)
    assert token not in str(exc_info.value)


def test_network_error_is_redacted():
    token = "network-secret-token"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connect failed: {request.url}", request=request)

    client = TelegramClient(
        token=token,
        chat_id="1",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        max_retries=0,
    )
    with pytest.raises(TelegramError) as exc_info:
        client.send_text("hi")
    assert token not in str(exc_info.value)
    assert "***" in str(exc_info.value)


def test_send_digest_disabled_and_not_configured(db, monkeypatch):
    monkeypatch.setattr(telegram_module, "get_settings", lambda: _settings(TELEGRAM_ENABLED=False))
    assert send_digest(db)["status"] == "disabled"

    monkeypatch.setattr(
        telegram_module,
        "get_settings",
        lambda: _settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID=""),
    )
    assert send_digest(db)["status"] == "not_configured"


def test_send_digest_empty(db, monkeypatch):
    monkeypatch.setattr(telegram_module, "get_settings", lambda: _settings())
    result = send_digest(db, now=NOW)
    assert result == {"status": "empty", "sent": False, "itemCount": 0}


def test_send_digest_sent_duplicate_and_force(db, monkeypatch):
    monkeypatch.setattr(telegram_module, "get_settings", lambda: _settings())
    _seed(db, "alpha")
    _seed(db, "beta")

    sender = FakeSender()
    result = send_digest(db, now=NOW, client=sender)
    assert result["status"] == "sent"
    assert result["sent"] is True
    assert result["itemCount"] == 2
    assert len(sender.parts[0]) >= 1
    assert "tg-test/alpha" in "\n".join(sender.parts[0])

    delivery = db.execute(select(TelegramDelivery)).scalars().one()
    assert delivery.status == "sent"
    assert delivery.item_count == 2
    assert delivery.chat_id == "123456789"

    duplicate = send_digest(db, now=NOW, client=FakeSender())
    assert duplicate["status"] == "duplicate"
    assert duplicate["sent"] is False

    forced = send_digest(db, now=NOW, force=True, client=FakeSender())
    assert forced["status"] == "sent"
    assert db.execute(select(TelegramDelivery)).scalars().all().__len__() == 2


def test_send_digest_only_recent_pushed(db, monkeypatch):
    monkeypatch.setattr(telegram_module, "get_settings", lambda: _settings())
    _seed(db, "old", created_at=NOW - timedelta(hours=48))
    _seed(db, "qualified", status="qualified")
    result = send_digest(db, now=NOW, client=FakeSender())
    assert result["status"] == "empty"


def test_send_digest_failure_records_delivery(db, monkeypatch):
    monkeypatch.setattr(telegram_module, "get_settings", lambda: _settings())
    _seed(db, "alpha")
    result = send_digest(db, now=NOW, client=FakeSender(error=TelegramError("boom")))
    assert result["status"] == "error"
    assert result["sent"] is False
    delivery = db.execute(select(TelegramDelivery)).scalars().one()
    assert delivery.status == "failed"
    assert "boom" in (delivery.error or "")


def test_send_test_message(db, monkeypatch):
    monkeypatch.setattr(telegram_module, "get_settings", lambda: _settings())
    sender = FakeSender()
    result = send_test_message(db, text="ping", client=sender)
    assert result["status"] == "sent"
    assert "ping" in sender.parts[0][0]
    delivery = db.execute(select(TelegramDelivery)).scalars().one()
    assert delivery.kind == "test"
    assert delivery.status == "sent"

    monkeypatch.setattr(
        telegram_module,
        "get_settings",
        lambda: _settings(TELEGRAM_BOT_TOKEN=""),
    )
    with pytest.raises(TelegramNotConfigured):
        send_test_message(db, client=FakeSender())


def test_status_api(db, monkeypatch):
    import app.api.notifications as notifications_api

    monkeypatch.setattr(
        notifications_api,
        "status_snapshot",
        lambda session: {
            "enabled": True,
            "configured": True,
            "chatIdMasked": "***6789",
            "apiBase": "https://api.telegram.org",
            "dailyLimit": 10,
            "digestWindowHours": 24,
            "lastDelivery": None,
        },
    )
    response = TestClient(app).get("/api/notifications/telegram/status")
    assert response.status_code == 200
    body = response.json()
    assert body["chatIdMasked"] == "***6789"
    assert body["lastDelivery"] is None
    assert "token" not in response.text.lower()


def test_test_api_success_and_not_configured(monkeypatch):
    import app.api.notifications as notifications_api

    monkeypatch.setattr(
        notifications_api,
        "send_test_message",
        lambda session, text=None: {
            "status": "sent",
            "sent": True,
            "deliveryId": "d1",
            "messageCount": 1,
            "messageIds": ["1"],
        },
    )
    response = TestClient(app).post("/api/notifications/telegram/test", json={"text": "ping"})
    assert response.status_code == 200
    assert response.json()["ok"] is True

    def _raise(session, text=None):
        raise TelegramNotConfigured("缺少 token")

    monkeypatch.setattr(notifications_api, "send_test_message", _raise)
    response = TestClient(app).post("/api/notifications/telegram/test")
    assert response.status_code == 409


def test_internal_token_guard(monkeypatch):
    import app.security as security_api

    monkeypatch.setattr(security_api, "get_settings", lambda: SimpleNamespace(INTERNAL_TOKEN="secret"))
    response = TestClient(app).get("/api/notifications/telegram/status")
    assert response.status_code == 401
    response = TestClient(app).get(
        "/api/notifications/telegram/status",
        headers={"X-Internal-Token": "secret"},
    )
    # 鉴权通过后进入真实状态查询（测试库无数据也应 200）
    assert response.status_code == 200


def test_task_calls_service(db, monkeypatch):
    monkeypatch.setattr(
        telegram_module,
        "send_digest",
        lambda session, user_id=None, limit=None, force=False: {
            "status": "sent",
            "sent": True,
            "itemCount": 1,
            "messageCount": 1,
        },
    )
    result = send_telegram_digest.apply(kwargs={"user_id": "tg-test-user"}).get()
    assert result["status"] == "sent"
    assert result["itemCount"] == 1
