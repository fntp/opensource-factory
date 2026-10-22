"""项目健康度（M6-05）测试：评分 / 元数据标准化 / 刷新 / API。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository
from app.services.github_service import normalize_repo
from app.services.repo_health import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_ATTENTION,
    STATUS_STALE,
    STATUS_UNKNOWN,
    evaluate_health,
    refresh_repositories,
    summarize_health,
)

NOW = datetime(2026, 10, 22, 10, 0, 0)


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    session.execute(delete(MyRepository).where(MyRepository.id.like("health-test/%")))
    session.commit()
    yield session
    session.rollback()
    session.execute(delete(MyRepository).where(MyRepository.id.like("health-test/%")))
    session.commit()
    session.close()


def _repo(db, repo_id: str, **kwargs) -> MyRepository:
    row = MyRepository(
        id=repo_id,
        platform="github",
        name=repo_id.split("/")[-1],
        description="",
        html_url=f"https://github.com/{repo_id}",
        stars=kwargs.pop("stars", 100),
        language="Python",
        **kwargs,
    )
    db.add(row)
    db.commit()
    return row


def test_evaluate_active_attention_stale_and_unknown() -> None:
    active = evaluate_health(pushed_at=NOW - timedelta(days=10), stars=100, now=NOW)
    assert active.status == STATUS_ACTIVE
    assert active.score == 100
    assert active.days_since_push == 10
    assert "最后提交于 10 天前" in active.reasons

    attention = evaluate_health(pushed_at=NOW - timedelta(days=120), stars=100, now=NOW)
    assert attention.status == STATUS_ATTENTION
    assert attention.score == 75

    stale = evaluate_health(pushed_at=NOW - timedelta(days=400), stars=100, now=NOW)
    assert stale.status == STATUS_STALE
    assert stale.score == 25
    assert any("建议评估" in reason for reason in stale.reasons)

    unknown = evaluate_health(pushed_at=None, now=NOW)
    assert unknown.status == STATUS_UNKNOWN
    assert unknown.score == 0


def test_evaluate_archived_and_disabled_priority() -> None:
    archived = evaluate_health(
        pushed_at=NOW - timedelta(days=1), stars=100, archived=True, now=NOW
    )
    assert archived.status == STATUS_ARCHIVED
    assert archived.score == 0
    assert archived.reasons == ("仓库已归档，不再接收更新",)

    disabled = evaluate_health(
        pushed_at=NOW - timedelta(days=1), stars=100, disabled=True, now=NOW
    )
    assert disabled.status == STATUS_STALE
    assert disabled.score <= 30
    assert any("禁用" in reason for reason in disabled.reasons)


def test_issue_pressure_lowers_score_but_not_active_status() -> None:
    snapshot = evaluate_health(
        pushed_at=NOW - timedelta(days=5),
        open_issues_count=60,
        stars=100,
        now=NOW,
    )
    assert snapshot.status == STATUS_ACTIVE
    assert snapshot.score == 80
    assert any("未关闭 issue" in reason for reason in snapshot.reasons)


def test_summarize_health_counts() -> None:
    summary = summarize_health(
        [
            {"status": "active", "score": 100},
            {"status": "attention", "score": 70},
            {"status": "stale", "score": 30},
            {"status": "archived", "score": 0},
            {"status": "unknown", "score": 0},
            {"status": "bogus", "score": 10},
        ]
    )
    assert summary["total"] == 6
    assert summary["active"] == 1
    assert summary["attention"] == 1
    assert summary["stale"] == 1
    assert summary["archived"] == 1
    assert summary["unknown"] == 2
    assert summary["averageScore"] == 35.0


def test_normalize_repo_includes_health_fields() -> None:
    meta = normalize_repo(
        {
            "full_name": "health-test/repo",
            "name": "repo",
            "html_url": "https://github.com/health-test/repo",
            "stargazers_count": 42,
            "language": "Python",
            "forks_count": 3,
            "pushed_at": "2026-10-01T12:00:00Z",
            "updated_at": "2026-10-02T08:30:00Z",
            "open_issues_count": 7,
            "archived": True,
            "disabled": False,
            "default_branch": "main",
        }
    )
    assert meta["pushed_at"] == datetime(2026, 10, 1, 12, 0, 0)
    assert meta["updated_at"] == datetime(2026, 10, 2, 8, 30, 0)
    assert meta["open_issues_count"] == 7
    assert meta["archived"] is True
    assert meta["disabled"] is False
    assert meta["default_branch"] == "main"


def test_refresh_repositories_updates_metadata_and_health(db) -> None:
    _repo(db, "health-test/active", stars=200)
    _repo(db, "health-test/archived", stars=50)

    async def fetcher(repo_id: str):
        if repo_id == "health-test/active":
            return {
                "id": repo_id,
                "name": "active",
                "html_url": f"https://github.com/{repo_id}",
                "description": "活跃项目",
                "stars": 210,
                "language": "Python",
                "pushed_at": NOW - timedelta(days=3),
                "updated_at": NOW - timedelta(days=1),
                "open_issues_count": 4,
                "archived": False,
                "disabled": False,
            }
        return {
            "id": repo_id,
            "name": "archived",
            "html_url": f"https://github.com/{repo_id}",
            "description": "已归档",
            "stars": 50,
            "language": "Go",
            "pushed_at": NOW - timedelta(days=2),
            "open_issues_count": 0,
            "archived": True,
            "disabled": False,
        }

    result = asyncio.run(
        refresh_repositories(
            db,
            ["health-test/active", "health-test/archived", "health-test/missing"],
            fetcher=fetcher,
            now=NOW,
        )
    )
    assert result["checked"] == 2
    assert result["skipped"] == 0
    assert result["missing"] == ["health-test/missing"]
    assert {item["status"] for item in result["items"]} == {STATUS_ACTIVE, STATUS_ARCHIVED}

    active = db.get(MyRepository, "health-test/active")
    assert active is not None
    assert active.stars == 210
    assert active.open_issues_count == 4
    assert active.health_status == STATUS_ACTIVE
    assert active.health_checked_at == NOW

    archived = db.get(MyRepository, "health-test/archived")
    assert archived is not None
    assert archived.archived is True
    assert archived.health_status == STATUS_ARCHIVED


def test_health_api_list_and_detail(db) -> None:
    _repo(
        db,
        "health-test/api-active",
        pushed_at=NOW - timedelta(days=2),
        open_issues_count=1,
        health_status=STATUS_ACTIVE,
        health_score=100,
        health_checked_at=NOW,
    )
    _repo(
        db,
        "health-test/api-stale",
        pushed_at=NOW - timedelta(days=400),
        open_issues_count=0,
        health_status=STATUS_STALE,
        health_score=25,
        health_checked_at=NOW,
    )

    with TestClient(app) as client:
        resp = client.get("/api/repos/health", params={"status": "active", "limit": 10})
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"]["total"] >= 2
        assert all(item["status"] == "active" for item in body["items"])

        detail = client.get("/api/repos/health-test/api-stale/health")
        assert detail.status_code == 200
        assert detail.json()["status"] == "stale"
        assert detail.json()["repoId"] == "health-test/api-stale"

        missing = client.get("/api/repos/health-test/nope/health")
        assert missing.status_code == 404

        refresh = client.post(
            "/api/repos/health/refresh",
            json={"repoIds": ["health-test/api-active"], "limit": 10},
        )
        assert refresh.status_code == 202
        assert refresh.json().get("taskId")


def test_health_api_requires_internal_token(monkeypatch) -> None:
    from app import security

    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: SimpleNamespace(INTERNAL_TOKEN="secret-token"),
    )
    with TestClient(app) as client:
        assert client.get("/api/repos/health").status_code == 401
        assert (
            client.get(
                "/api/repos/health", headers={"X-Internal-Token": "secret-token"}
            ).status_code
            == 200
        )
