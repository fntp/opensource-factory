"""推荐反馈回流（M3-07）测试：不访问网络。"""
from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import delete, select

from app.config import Settings
from app.db import SessionLocal, init_db
from app.models import MyRepository, Recommendation, TrendingRepository, User
from app.services.recommendation_feedback import (
    EdgeRecommendationClient,
    FeedbackSnapshot,
    build_push_items,
    fetch_feedback,
    merge_exclusions,
    push_recommendations,
)
from app.tasks import jobs


def _settings(**overrides) -> Settings:
    values = {
        "RECOMMEND_FEEDBACK_SYNC": True,
        "EDGE_BASE_URL": "https://edge.test",
        "INTERNAL_TOKEN": "test-token",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    for model in (Recommendation, MyRepository, TrendingRepository, User):
        session.execute(delete(model))
    session.commit()
    yield session
    session.rollback()
    for model in (Recommendation, MyRepository, TrendingRepository, User):
        session.execute(delete(model))
    session.commit()
    session.close()


def test_merge_exclusions_dedupes_and_ignores_blank() -> None:
    assert merge_exclusions(["a/b", " ", "a/b"], ["c/d"]) == {"a/b", "c/d"}
    assert merge_exclusions() == set()


def test_edge_client_fetch_feedback_parses_and_sends_token() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["user"] = request.url.params.get("userId")
        seen["token"] = request.headers.get("X-Internal-Token")
        return httpx.Response(
            200,
            json={
                "savedRepoIds": ["a/one", "a/one"],
                "dismissedRepoIds": ["b/two"],
                "clickedRepoIds": ["c/three"],
            },
        )

    client = EdgeRecommendationClient(
        "https://edge.test", "test-token", transport=httpx.MockTransport(handler)
    )
    snapshot = client.fetch_feedback("u1")
    assert seen == {
        "path": "/api/internal/recommendations/feedback",
        "user": "u1",
        "token": "test-token",
    }
    assert snapshot.source == "edge"
    assert snapshot.saved_repo_ids == ["a/one"]
    assert snapshot.excluded_repo_ids == {"a/one", "b/two"}
    assert snapshot.clicked_repo_ids == ["c/three"]


def test_fetch_feedback_merges_local_status(db) -> None:
    db.add_all(
        [
            Recommendation(
                id="r-saved", user_id="u1", repo_id="local/saved", score=0.5, status="saved"
            ),
            Recommendation(
                id="r-dismissed",
                user_id="u1",
                repo_id="local/dismissed",
                score=0.4,
                status="dismissed",
            ),
        ]
    )
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"savedRepoIds": ["edge/saved"], "dismissedRepoIds": [], "clickedRepoIds": []},
        )

    client = EdgeRecommendationClient(
        "https://edge.test", "test-token", transport=httpx.MockTransport(handler)
    )
    snapshot = fetch_feedback(db, "u1", settings=_settings(), client=client)
    assert snapshot.source == "edge"
    assert set(snapshot.saved_repo_ids) == {"edge/saved", "local/saved"}
    assert snapshot.excluded_repo_ids == {"edge/saved", "local/saved", "local/dismissed"}


def test_fetch_feedback_falls_back_to_local_on_error(db) -> None:
    db.add(
        Recommendation(
            id="r1", user_id="u1", repo_id="local/dismissed", score=0.4, status="dismissed"
        )
    )
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    client = EdgeRecommendationClient(
        "https://edge.test", "test-token", transport=httpx.MockTransport(handler)
    )
    snapshot = fetch_feedback(db, "u1", settings=_settings(), client=client)
    assert snapshot.source == "local"
    assert snapshot.dismissed_repo_ids == ["local/dismissed"]


def test_fetch_feedback_disabled_uses_local(db) -> None:
    db.add(
        Recommendation(
            id="r1", user_id="u1", repo_id="local/saved", score=0.4, status="saved"
        )
    )
    db.commit()
    snapshot = fetch_feedback(db, "u1", settings=_settings(RECOMMEND_FEEDBACK_SYNC=False))
    assert snapshot.source == "local"
    assert snapshot.saved_repo_ids == ["local/saved"]


def test_build_push_items_and_push(db) -> None:
    db.add_all(
        [
            TrendingRepository(
                id="owner/repo",
                name="repo",
                description="desc",
                tech_stack="Python",
                html_url="https://github.com/owner/repo",
            ),
            Recommendation(
                id="r1", user_id="u1", repo_id="owner/repo", score=0.88, status="new", reason="why"
            ),
        ]
    )
    db.commit()

    items = build_push_items(db, "u1")
    assert len(items) == 1
    assert items[0]["repoId"] == "owner/repo"
    assert items[0]["owner"] == "owner"
    assert items[0]["name"] == "repo"
    assert items[0]["status"] == "new"

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True, "count": 1})

    client = EdgeRecommendationClient(
        "https://edge.test", "test-token", transport=httpx.MockTransport(handler)
    )
    assert push_recommendations(db, "u1", settings=_settings(), client=client) == 1
    assert captured["path"] == "/api/internal/recommendations/upsert"
    body = json.loads(str(captured["body"]))
    assert body["userId"] == "u1"
    assert body["items"][0]["repoId"] == "owner/repo"


def test_push_failure_returns_zero(db) -> None:
    db.add(
        Recommendation(
            id="r1", user_id="u1", repo_id="owner/repo", score=0.88, status="new", reason="why"
        )
    )
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = EdgeRecommendationClient(
        "https://edge.test", "test-token", transport=httpx.MockTransport(handler)
    )
    assert push_recommendations(db, "u1", settings=_settings(), client=client) == 0


def test_generate_recommendations_excludes_dismissed(db, monkeypatch) -> None:
    db.add_all(
        [
            User(id="u1", username="u1"),
            MyRepository(
                id="me/base",
                name="base",
                description="python machine learning",
                language="Python",
                html_url="https://github.com/me/base",
            ),
            TrendingRepository(
                id="owner/keep",
                name="keep",
                description="python machine learning toolkit",
                tech_stack="Python",
                html_url="https://github.com/owner/keep",
            ),
            TrendingRepository(
                id="owner/drop",
                name="drop",
                description="python machine learning toolkit",
                tech_stack="Python",
                html_url="https://github.com/owner/drop",
            ),
            Recommendation(
                id="old-drop",
                user_id="u1",
                repo_id="owner/drop",
                score=0.9,
                status="dismissed",
                reason="不感兴趣",
            ),
        ]
    )
    db.commit()

    monkeypatch.setattr(jobs, "SessionLocal", lambda: db)
    result = jobs.generate_recommendations.run("u1", 10)

    assert result["status"] == "ok"
    assert result["feedbackExcluded"]["u1"] >= 1
    rows = list(
        db.execute(select(Recommendation).where(Recommendation.user_id == "u1")).scalars().all()
    )
    statuses = {row.repo_id: row.status for row in rows}
    assert statuses["owner/drop"] == "dismissed"
    assert "owner/keep" in statuses


def test_feedback_snapshot_excluded_ids() -> None:
    snapshot = FeedbackSnapshot(
        user_id="u1", saved_repo_ids=["a/b"], dismissed_repo_ids=["c/d", "a/b"]
    )
    assert snapshot.excluded_repo_ids == {"a/b", "c/d"}
