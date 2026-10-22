"""同步任务与接口的过滤策略测试（不访问网络）。"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.github_service import RepoCollection, normalize_repo


def _repo(full_name: str, *, owner_type: str = "Organization", stars: int = 7) -> dict[str, Any]:
    owner, name = full_name.split("/", 1)
    return {
        "full_name": full_name,
        "name": name,
        "description": "测试仓库",
        "html_url": f"https://github.com/{full_name}",
        "stargazers_count": stars,
        "forks_count": 3,
        "language": "TypeScript",
        "owner": {"login": owner, "type": owner_type},
        "fork": False,
        "archived": False,
        "private": False,
        "updated_at": "2026-10-21T10:00:00Z",
        "pushed_at": "2026-10-20T10:00:00Z",
    }


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        GITHUB_TOKEN="test-token",
        GITHUB_SYNC_INCLUDE_OWN=True,
        GITHUB_SYNC_INCLUDE_ORGS=True,
        GITHUB_SYNC_INCLUDE_FORKS=False,
        GITHUB_SYNC_INCLUDE_ARCHIVED=False,
        GITHUB_SYNC_ORG_ALLOWLIST="",
    )


def test_sync_repositories_persists_metadata_and_returns_filter_stats(monkeypatch) -> None:
    from app.db import SessionLocal, init_db
    from app.models import MyRepository
    from app.tasks import jobs

    init_db()
    collection = RepoCollection(
        repos=[normalize_repo(_repo("acme/req0898-widgets"))],
        fetched=3,
        own=0,
        org=1,
        starred=0,
    )
    collection.excluded.update({"fork": 1, "archived": 1})
    captured: dict[str, Any] = {}

    async def fake_collect(token: str, include_starred: bool = True, *, policy=None, **_: Any):
        captured["token"] = token
        captured["include_starred"] = include_starred
        captured["policy"] = policy
        return collection

    monkeypatch.setattr("app.services.github_service.collect_user_repos", fake_collect)
    monkeypatch.setattr(jobs, "get_settings", _settings)

    result = jobs.sync_repositories(include_starred=False, include_forks=True)

    assert result["status"] == "ok"
    assert result["total"] == 1
    assert result["created"] == 1
    assert result["filtered"] == 2
    assert result["excluded"]["fork"] == 1
    assert result["excluded"]["archived"] == 1
    assert result["org"] == 1
    assert captured["token"] == "test-token"
    assert captured["include_starred"] is False
    assert captured["policy"].include_forks is True

    db = SessionLocal()
    try:
        row = db.get(MyRepository, "acme/req0898-widgets")
        assert row is not None
        assert row.owner == "acme"
        assert row.forks == 3
        assert row.updated_at == "2026-10-21T10:00:00Z"
        assert row.synced_at is not None

        # 二次同步走更新路径，不重复插入
        collection.repos[0]["stars"] = 99
        result2 = jobs.sync_repositories(include_starred=False)
        assert result2["created"] == 0
        assert result2["updated"] == 1
        db.expire_all()
        assert db.get(MyRepository, "acme/req0898-widgets").stars == 99
    finally:
        db.close()


@pytest.mark.parametrize("path", ["/api/repos/sync", "/api/tasks/sync"])
def test_sync_api_forwards_policy_overrides(monkeypatch, path: str) -> None:
    from app.api import repos as repos_api
    from app.api import tasks as tasks_api

    captured: dict[str, Any] = {}

    class _FakeTask:
        id = "task-0898"

    class _FakeSync:
        @staticmethod
        def delay(**kwargs: Any) -> _FakeTask:
            captured.update(kwargs)
            return _FakeTask()

    monkeypatch.setattr(repos_api, "sync_repositories", _FakeSync)
    monkeypatch.setattr(tasks_api, "sync_repositories", _FakeSync)

    with TestClient(app) as client:
        resp = client.post(
            path,
            params={
                "include_starred": "false",
                "include_forks": "true",
                "include_archived": "false",
            },
        )

    assert resp.status_code == 202
    assert resp.json()["taskId"] == "task-0898"
    assert captured["include_starred"] is False
    assert captured["include_forks"] is True
    assert captured["include_archived"] is False
    assert captured["include_own"] is None
    assert captured["include_orgs"] is None
