"""API 集成测试（TestClient，celery 急切模式，无网络）。

环境变量在 tests/conftest.py 中统一设置：
- CELERY_TASK_ALWAYS_EAGER=1（任务同步执行）；
- GITHUB_TOKEN 为空（同步任务直接跳过，不发起网络请求）。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_healthz_returns_200() -> None:
    with TestClient(app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "opensource-factory-vps"


def test_tasks_sync_eager_returns_202_with_task_id() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/tasks/sync")
    assert resp.status_code == 202
    body = resp.json()
    assert body.get("taskId")


def test_tasks_summarize_eager_returns_202_with_task_id() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/tasks/summarize")
    assert resp.status_code == 202
    assert resp.json().get("taskId")


def test_tasks_summarize_accepts_source_param() -> None:
    with TestClient(app) as client:
        for source in ("my", "trending", "all"):
            resp = client.post("/api/tasks/summarize", params={"source": source})
            assert resp.status_code == 202
            assert resp.json().get("taskId")
        invalid = client.post("/api/tasks/summarize", params={"source": "unknown"})
    assert invalid.status_code == 422


def test_trending_summarize_endpoint_returns_202() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/trending/summarize", params={"limit": 10})
    assert resp.status_code == 202
    assert resp.json().get("taskId")


def test_repos_list_returns_200() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/repos")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_trending_list_returns_200() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/trending", params={"platform": "github", "limit": 20})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_generate_recommendations_accepts_min_score() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/tasks/generate-recommendations",
            params={"top_k": 5, "min_score": 0.5},
        )
    assert resp.status_code == 202
    assert resp.json().get("taskId")


def test_generate_recommendations_rejects_invalid_min_score() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/tasks/generate-recommendations",
            params={"min_score": 1.5},
        )
    assert resp.status_code == 422


def test_internal_token_enforced_when_configured(monkeypatch) -> None:
    import app.security as security_api

    class _FakeSettings:
        INTERNAL_TOKEN = "secret-token"

    monkeypatch.setattr(security_api, "get_settings", lambda: _FakeSettings())
    with TestClient(app) as client:
        unauthorized = client.post("/api/tasks/sync")
        authorized = client.post("/api/tasks/sync", headers={"X-Internal-Token": "secret-token"})
    assert unauthorized.status_code == 401
    assert authorized.status_code == 202
