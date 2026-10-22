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


def test_task_status_exposes_progress_snapshot(monkeypatch) -> None:
    import app.api.tasks as tasks_api

    class _FakeResult:
        state = "PROGRESS"
        info = {
            "phase": "fetch",
            "page": 2,
            "pagesTotal": 5,
            "fetched": 200,
            "total": None,
            "percent": 40,
            "done": False,
        }
        result = None

        def successful(self) -> bool:
            return False

        def failed(self) -> bool:
            return False

    monkeypatch.setattr(tasks_api.celery_app, "AsyncResult", lambda task_id: _FakeResult())
    with TestClient(app) as client:
        resp = client.get("/api/tasks/fake-task-id")
    assert resp.status_code == 200
    body = resp.json()
    assert body["taskId"] == "fake-task-id"
    assert body["status"] == "progress"
    assert body["progress"]["percent"] == 40
    assert body["progress"]["pagesTotal"] == 5


def test_internal_token_enforced_when_configured(monkeypatch) -> None:
    import app.api.tasks as tasks_api

    class _FakeSettings:
        INTERNAL_TOKEN = "secret-token"

    monkeypatch.setattr(tasks_api, "get_settings", lambda: _FakeSettings())
    with TestClient(app) as client:
        unauthorized = client.post("/api/tasks/sync")
        authorized = client.post("/api/tasks/sync", headers={"X-Internal-Token": "secret-token"})
    assert unauthorized.status_code == 401
    assert authorized.status_code == 202
