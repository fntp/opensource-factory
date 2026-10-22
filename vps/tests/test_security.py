"""M5-05 安全加固测试：双令牌 / 限流 / 状态接口（离线）。"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.middleware.rate_limit import SlidingWindowLimiter, client_ip
from app.security import (
    internal_token_status,
    token_fingerprint,
    verify_internal_token,
)


def _settings(token: str = "", previous: str = "") -> SimpleNamespace:
    return SimpleNamespace(INTERNAL_TOKEN=token, INTERNAL_TOKEN_PREVIOUS=previous)


def test_verify_internal_token_accepts_current_and_previous(monkeypatch) -> None:
    monkeypatch.setattr("app.security.get_settings", lambda: _settings("current", "previous"))
    assert verify_internal_token("current") is True
    assert verify_internal_token(" previous ") is True
    assert verify_internal_token("stale") is False
    assert verify_internal_token(None) is False


def test_verify_internal_token_disabled_when_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr("app.security.get_settings", lambda: _settings("", ""))
    assert verify_internal_token(None) is True
    assert verify_internal_token("anything") is True


def test_token_status_only_exposes_fingerprints(monkeypatch) -> None:
    monkeypatch.setattr("app.security.get_settings", lambda: _settings("current", "previous"))
    status = internal_token_status()
    assert status["configured"] is True
    assert status["previousConfigured"] is True
    assert status["rotationPending"] is True
    assert status["currentFingerprint"] == token_fingerprint("current")
    assert len(status["currentFingerprint"]) == 12
    assert "current" not in status["currentFingerprint"]


def test_sliding_window_limiter_allows_then_blocks() -> None:
    limiter = SlidingWindowLimiter(window_seconds=60, max_requests=2, heavy_max_requests=1)
    first = limiter.hit("ip:a:repos", 2, now=1000.0)
    second = limiter.hit("ip:a:repos", 2, now=1001.0)
    third = limiter.hit("ip:a:repos", 2, now=1002.0)
    assert first.allowed and first.remaining == 1
    assert second.allowed and second.remaining == 0
    assert third.allowed is False
    assert third.retry_after_seconds == 58

    # 窗口滑过后恢复
    after = limiter.hit("ip:a:repos", 2, now=1061.0)
    assert after.allowed is True


def test_sliding_window_limiter_heavy_limit() -> None:
    limiter = SlidingWindowLimiter(window_seconds=60, max_requests=100, heavy_max_requests=2)
    assert limiter.limit_for("/api/tasks/sync") == 2
    assert limiter.limit_for("/api/repos") == 100
    assert limiter.limit_for("/api/vector-index/sync") == 2


def test_sliding_window_limiter_reset_and_cleanup() -> None:
    limiter = SlidingWindowLimiter(window_seconds=1, max_requests=10, heavy_max_requests=10)
    for i in range(5):
        limiter.hit("ip:a:repos", 10, now=float(i))
    limiter.reset()
    assert limiter.hit("ip:a:repos", 10, now=10.0).remaining == 9


def test_client_ip_respects_proxy_flag() -> None:
    class RequestStub:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = SimpleNamespace(host="127.0.0.1")

    assert client_ip(RequestStub(), trust_proxy=True) == "203.0.113.7"
    assert client_ip(RequestStub(), trust_proxy=False) == "127.0.0.1"


def test_security_status_api_is_available() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/security/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "internalToken" in body
    assert "rateLimit" in body
    assert body["rateLimit"]["windowSeconds"] >= 1


def test_security_status_requires_token_when_configured(monkeypatch) -> None:
    monkeypatch.setattr("app.security.get_settings", lambda: _settings("secret", ""))
    with TestClient(app) as client:
        unauthorized = client.get("/api/security/status")
        authorized = client.get("/api/security/status", headers={"X-Internal-Token": "secret"})
    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
