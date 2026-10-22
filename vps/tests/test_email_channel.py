"""Email 通道测试（M4-05）。

覆盖：收件人归一化 / 头注入防护 / 脱敏、摘要渲染、SMTP 发送（STARTTLS / 登录 /
重试 / 认证失败不重试）、每日摘要幂等与失败落库、测试邮件、状态接口与任务。
全部使用 fake SMTP / fake sender，不访问网络。
"""
from __future__ import annotations

import smtplib
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import Settings, get_settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import EmailDelivery, Recommendation, TrendingRepository
from app.services.email_channel import (
    EmailConfigError,
    EmailContent,
    EmailSendResult,
    SmtpSender,
    build_digest_items,
    digest_dedupe_key,
    format_percent,
    get_email_status,
    is_valid_email,
    mask_email,
    normalize_recipients,
    render_digest,
    sanitize_header,
    send_digest,
    send_test_email,
)
from app.tasks.jobs import send_email_digest

NOW = datetime(2026, 10, 22, 9, 10)


def make_settings(**overrides) -> Settings:
    """构造隔离的 Settings（不读取 .env）。"""
    values = {
        "EMAIL_ENABLED": True,
        "EMAIL_SMTP_HOST": "smtp.test.local",
        "EMAIL_SMTP_PORT": 587,
        "EMAIL_SMTP_USERNAME": "bot@test.local",
        "EMAIL_SMTP_PASSWORD": "super-secret",
        "EMAIL_FROM": "bot@test.local",
        "EMAIL_FROM_NAME": "OpenFactory",
        "EMAIL_TO": "reader@test.local",
        "EMAIL_STARTTLS": True,
        "EMAIL_SSL": False,
        "EMAIL_MAX_RETRIES": 0,
        "EMAIL_RETRY_BASE_SECONDS": 0.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class FakeSender:
    """可注入的发送器：记录调用并按预设返回。"""

    def __init__(self, results: list[EmailSendResult] | None = None) -> None:
        self.results = list(results or [EmailSendResult(ok=True, message_id="<fake@test>", attempts=1)])
        self.calls: list[tuple[EmailContent, list[str]]] = []

    def send(self, content: EmailContent, recipients) -> EmailSendResult:
        self.calls.append((content, list(recipients)))
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0]


class FakeSMTP:
    """最小 SMTP 客户端替身，支持上下文管理与失败注入。"""

    instances: list["FakeSMTP"] = []
    fail_send_times = 0
    raise_on_send: BaseException | None = None

    def __init__(self, host, port, timeout=None, context=None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.ehlo_calls = 0
        self.starttls_calls = 0
        self.login_calls: list[tuple[str, str]] = []
        self.messages = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def ehlo(self):
        self.ehlo_calls += 1

    def starttls(self, context=None):
        self.starttls_calls += 1
        self.context = context

    def login(self, username, password):
        self.login_calls.append((username, password))

    def send_message(self, message, from_addr=None, to_addrs=None):
        if FakeSMTP.raise_on_send is not None:
            raise FakeSMTP.raise_on_send
        if FakeSMTP.fail_send_times > 0:
            FakeSMTP.fail_send_times -= 1
            raise OSError("connection reset by peer")
        self.messages.append((message, from_addr, to_addrs))


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    _cleanup(session)
    yield session
    _cleanup(session)
    session.close()


def _cleanup(session) -> None:
    session.execute(delete(EmailDelivery))
    session.execute(delete(Recommendation).where(Recommendation.user_id.like("email-test%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like("email-test/%")))
    session.commit()


def _seed_recommendation(
    db,
    suffix: str,
    *,
    status: str = "pushed",
    created_at: datetime | None = None,
    quality_score: float = 0.8,
    match_score: float = 0.75,
) -> Recommendation:
    repo_id = f"email-test/{suffix}"
    db.add(
        TrendingRepository(
            id=repo_id,
            platform="github",
            name=f"demo-{suffix}",
            html_url=f"https://github.com/{repo_id}",
            stars_today=321,
            description=f"<b>项目 {suffix}</b> 的简介",
            tech_stack="Python / FastAPI",
        )
    )
    row = Recommendation(
        id=f"email-test-rec-{suffix}",
        user_id="email-test-user",
        repo_id=repo_id,
        score=match_score,
        match_score=match_score,
        quality_score=quality_score,
        reason=f"推荐关注 demo-{suffix}：与你的技术栈高度匹配。",
        status=status,
        created_at=created_at or NOW,
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def test_normalize_recipients_dedupes_and_validates() -> None:
    assert normalize_recipients(" A@Example.com, b@test.dev; a@example.com ") == [
        "A@Example.com",
        "b@test.dev",
    ]
    assert normalize_recipients(None) == []
    assert is_valid_email("a@b.co") is True
    assert is_valid_email("bad") is False
    with pytest.raises(EmailConfigError):
        normalize_recipients("not-an-email")
    with pytest.raises(EmailConfigError):
        normalize_recipients(",".join(f"u{i}@test.dev" for i in range(21)))


def test_sanitize_header_blocks_crlf_injection() -> None:
    assert sanitize_header("hello\r\nBcc: evil@test.dev") == "hello Bcc: evil@test.dev"
    assert sanitize_header("  hi\x00there  ") == "hithere"
    assert len(sanitize_header("x" * 500)) <= 160


def test_mask_email_and_percent() -> None:
    assert mask_email("alice@example.com") == "a***@example.com"
    assert mask_email("alice@example.com, bob@test.dev") == "a***@example.com, b***@test.dev"
    assert mask_email("invalid") == "***"
    assert format_percent(0.756) == "76%"
    assert format_percent(None) == "0%"


def test_digest_dedupe_key_is_stable() -> None:
    first = digest_dedupe_key(["B@test.dev", "a@test.dev"], NOW)
    second = digest_dedupe_key(["a@test.dev", "B@test.dev"], NOW)
    assert first == second == "email:digest:2026-10-22:a@test.dev,b@test.dev"


def test_render_digest_contains_items_and_escapes_html(db) -> None:
    _seed_recommendation(db, "render")
    rows = (
        db.execute(
            select(Recommendation).where(Recommendation.user_id == "email-test-user")
        )
        .scalars()
        .all()
    )
    repositories = {
        row.id: row
        for row in db.execute(
            select(TrendingRepository).where(TrendingRepository.id.like("email-test/%"))
        ).scalars()
    }
    items = build_digest_items(rows, repositories)
    content = render_digest(items, NOW)

    assert "OpenFactory 每日精选" in content.subject
    assert "demo-render" in content.text
    assert "推荐关注 demo-render" in content.text
    assert "<b>项目 render</b>" in content.text
    assert "&lt;b&gt;项目 render&lt;/b&gt;" in content.html
    assert "<b>项目 render</b>" not in content.html
    assert "https://github.com/email-test/render" in content.html


# ---------------------------------------------------------------------------
# SMTP 发送器
# ---------------------------------------------------------------------------


def test_smtp_sender_starttls_login_and_message(monkeypatch) -> None:
    FakeSMTP.instances = []
    FakeSMTP.fail_send_times = 0
    FakeSMTP.raise_on_send = None
    sender = SmtpSender(make_settings(), smtp_factory=FakeSMTP)
    content = EmailContent(subject="测试主题", text="纯文本", html="<p>HTML</p>")

    result = sender.send(content, ["reader@test.local"])

    assert result.ok is True
    assert result.message_id
    client = FakeSMTP.instances[0]
    assert client.host == "smtp.test.local" and client.port == 587
    assert client.starttls_calls == 1
    assert client.login_calls == [("bot@test.local", "super-secret")]
    message, from_addr, to_addrs = client.messages[0]
    assert from_addr == "bot@test.local"
    assert to_addrs == ["reader@test.local"]
    assert message["Subject"] == "测试主题"
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "纯文本"


def test_smtp_sender_retries_transient_errors() -> None:
    FakeSMTP.instances = []
    FakeSMTP.fail_send_times = 1
    FakeSMTP.raise_on_send = None
    sleeps: list[float] = []
    sender = SmtpSender(
        make_settings(EMAIL_MAX_RETRIES=1, EMAIL_RETRY_BASE_SECONDS=0.5),
        smtp_factory=FakeSMTP,
        sleep=sleeps.append,
    )

    result = sender.send(EmailContent("主题", "text", "<p>html</p>"), ["reader@test.local"])

    assert result.ok is True
    assert result.attempts == 2
    assert sleeps == [0.5]
    assert len(FakeSMTP.instances) == 2


def test_smtp_sender_does_not_retry_auth_error_and_redacts_password() -> None:
    FakeSMTP.instances = []
    FakeSMTP.fail_send_times = 0
    FakeSMTP.raise_on_send = smtplib.SMTPAuthenticationError(
        535, b"auth failed for super-secret"
    )
    sleeps: list[float] = []
    sender = SmtpSender(
        make_settings(EMAIL_MAX_RETRIES=3),
        smtp_factory=FakeSMTP,
        sleep=sleeps.append,
    )

    result = sender.send(EmailContent("主题", "text", "<p>html</p>"), ["reader@test.local"])

    assert result.ok is False
    assert result.attempts == 1
    assert sleeps == []
    assert "super-secret" not in (result.error or "")
    assert "***" in (result.error or "")


def test_smtp_sender_rejects_incomplete_config() -> None:
    sender = SmtpSender(make_settings(EMAIL_SMTP_HOST=""), smtp_factory=FakeSMTP)
    result = sender.send(EmailContent("主题", "text", "<p>html</p>"), ["reader@test.local"])
    assert result.ok is False
    assert "EMAIL_SMTP_HOST" in (result.error or "")
    assert result.attempts == 0


# ---------------------------------------------------------------------------
# 服务层
# ---------------------------------------------------------------------------


def test_send_digest_disabled_and_not_configured(db) -> None:
    disabled = send_digest(db, settings=make_settings(EMAIL_ENABLED=False), now=NOW)
    assert disabled["status"] == "disabled"

    missing = send_digest(db, settings=make_settings(EMAIL_SMTP_HOST=""), now=NOW)
    assert missing["status"] == "not_configured"
    assert "EMAIL_SMTP_HOST" in missing["error"]


def test_send_digest_empty(db) -> None:
    result = send_digest(db, settings=make_settings(), now=NOW)
    assert result["status"] == "empty"
    assert result["itemCount"] == 0


def test_send_digest_sent_idempotent_and_force(db) -> None:
    _seed_recommendation(db, "idem")
    sender = FakeSender()
    settings = make_settings()

    first = send_digest(db, settings=settings, sender=sender, now=NOW)
    assert first["status"] == "sent"
    assert first["itemCount"] == 1
    assert first["messageId"] == "<fake@test>"
    assert len(sender.calls) == 1
    assert sender.calls[0][1] == ["reader@test.local"]

    second = send_digest(db, settings=settings, sender=sender, now=NOW)
    assert second["status"] == "skipped"
    assert second["reason"] == "already_sent"
    assert len(sender.calls) == 1

    forced = send_digest(db, settings=settings, sender=sender, now=NOW, force=True)
    assert forced["status"] == "sent"
    assert len(sender.calls) == 2

    rows = db.execute(select(EmailDelivery).order_by(EmailDelivery.created_at)).scalars().all()
    assert len(rows) == 2
    assert all(row.kind == "digest" and row.status == "sent" for row in rows)


def test_send_digest_records_failure(db) -> None:
    _seed_recommendation(db, "fail")
    sender = FakeSender([EmailSendResult(ok=False, error="smtp down", attempts=1)])

    result = send_digest(db, settings=make_settings(), sender=sender, now=NOW)

    assert result["status"] == "failed"
    assert result["ok"] is False
    row = db.execute(select(EmailDelivery)).scalars().one()
    assert row.status == "failed"
    assert row.error == "smtp down"


def test_send_digest_respects_window_and_limit(db) -> None:
    _seed_recommendation(db, "old", created_at=NOW - timedelta(hours=48))
    _seed_recommendation(db, "new-1", quality_score=0.9)
    _seed_recommendation(db, "new-2", quality_score=0.8)
    sender = FakeSender()

    result = send_digest(
        db, settings=make_settings(EMAIL_DAILY_LIMIT=1), sender=sender, now=NOW
    )

    assert result["itemCount"] == 1
    assert "demo-new-1" in sender.calls[0][0].text
    assert "demo-old" not in sender.calls[0][0].text


def test_send_test_email_records_kind_test(db) -> None:
    sender = FakeSender()

    result = send_test_email(
        db,
        to="reader@test.local",
        subject="连通性",
        body="hello",
        settings=make_settings(),
        sender=sender,
    )

    assert result["status"] == "sent"
    row = db.execute(select(EmailDelivery)).scalars().one()
    assert row.kind == "test"
    assert row.item_count == 0
    assert row.subject == "连通性"
    assert sender.calls[0][0].text == "hello"


def test_send_test_email_requires_recipient(db) -> None:
    with pytest.raises(EmailConfigError):
        send_test_email(db, settings=make_settings(EMAIL_TO=""), sender=FakeSender())


def test_get_email_status_masks_credentials(db) -> None:
    sender = FakeSender()
    send_test_email(db, settings=make_settings(), sender=sender)
    status = get_email_status(db, make_settings())

    assert status["enabled"] is True
    assert status["configured"] is True
    assert status["fromMasked"] == "b***@test.local"
    assert status["toMasked"] == "r***@test.local"
    assert "super-secret" not in str(status)
    assert status["lastDelivery"] is not None


# ---------------------------------------------------------------------------
# API 与任务
# ---------------------------------------------------------------------------


@pytest.fixture()
def email_api(monkeypatch):
    """把全局 Settings 临时改为已启用的 Email 配置。"""
    settings = get_settings()
    for key, value in {
        "EMAIL_ENABLED": True,
        "EMAIL_SMTP_HOST": "smtp.test.local",
        "EMAIL_SMTP_PORT": 587,
        "EMAIL_SMTP_USERNAME": "bot@test.local",
        "EMAIL_SMTP_PASSWORD": "super-secret",
        "EMAIL_FROM": "bot@test.local",
        "EMAIL_FROM_NAME": "OpenFactory",
        "EMAIL_TO": "reader@test.local",
        "EMAIL_STARTTLS": True,
        "EMAIL_SSL": False,
        "EMAIL_MAX_RETRIES": 0,
        "INTERNAL_TOKEN": "",
    }.items():
        monkeypatch.setattr(settings, key, value)
    return settings


def test_api_email_status_and_test(db, email_api, monkeypatch) -> None:
    import app.services.email_channel as email_mod

    monkeypatch.setattr(email_mod, "SmtpSender", lambda cfg: FakeSender())
    with TestClient(app) as client:
        status_response = client.get("/api/notifications/email/status")
        assert status_response.status_code == 200
        payload = status_response.json()
        assert payload["enabled"] is True
        assert payload["configured"] is True
        assert payload["fromMasked"] == "b***@test.local"
        assert "super-secret" not in status_response.text

        test_response = client.post(
            "/api/notifications/email/test",
            json={"to": "reader@test.local", "subject": "测试", "body": "hello"},
        )
        assert test_response.status_code == 200
        assert test_response.json()["status"] == "sent"


def test_api_email_test_returns_409_when_disabled(email_api, monkeypatch) -> None:
    monkeypatch.setattr(email_api, "EMAIL_ENABLED", False)
    with TestClient(app) as client:
        response = client.post("/api/notifications/email/test", json={})
    assert response.status_code == 409
    assert "EMAIL_ENABLED" in response.json()["detail"]


def test_api_email_status_requires_internal_token(email_api, monkeypatch) -> None:
    monkeypatch.setattr(email_api, "INTERNAL_TOKEN", "secret-token")
    with TestClient(app) as client:
        response = client.get("/api/notifications/email/status")
    assert response.status_code == 401


def test_api_enqueue_send_email_digest(email_api) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/tasks/send-email-digest",
            params={"user_id": "email-test-user", "limit": 5},
        )
    assert response.status_code == 202
    assert response.json().get("taskId")


def test_task_send_email_digest(db, email_api, monkeypatch) -> None:
    import app.services.email_channel as email_mod

    _seed_recommendation(db, "task")
    monkeypatch.setattr(email_mod, "SmtpSender", lambda cfg: FakeSender())

    result = send_email_digest(user_id="email-test-user")

    assert result["status"] == "sent"
    assert result["itemCount"] == 1
