"""Rerank 精排测试（REQ-202610-0966 / M7-07）。

覆盖：六路信号、权重归一化、MMR 多样性、精排指标、每日生成落库与
预览 / 应用 API。全部使用本地 SQLite 与 hash 兜底向量，不访问网络。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository, Recommendation, TrendingRepository
from app.services.embedding import EmbeddingService
from app.services.recommendation_service import generate_for_user
from app.services.rerank import (
    RerankCandidate,
    RerankWeights,
    affinity_score,
    build_interest_terms,
    freshness_score,
    health_score,
    rerank_candidates,
    weighted_score,
)
from app.services.rerank_service import rerank_for_user

USER = "rerank-test-user"


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    _cleanup(session)
    yield session
    _cleanup(session)
    session.close()


def _cleanup(session) -> None:
    session.execute(delete(Recommendation).where(Recommendation.user_id.like("rerank-test%")))
    session.execute(delete(MyRepository).where(MyRepository.id.like("rerank-test/%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like("rerank-test/%")))
    session.commit()


def _seed_repo(db, suffix: str, **kwargs) -> TrendingRepository:
    row = TrendingRepository(
        id=f"rerank-test/{suffix}",
        platform="github",
        name=kwargs.pop("name", suffix),
        html_url=f"https://example.com/rerank-test/{suffix}",
        **kwargs,
    )
    db.add(row)
    db.commit()
    return row


def _seed_rec(db, suffix: str, **kwargs) -> Recommendation:
    row = Recommendation(
        id=f"rerank-test-rec-{suffix}",
        user_id=kwargs.pop("user_id", USER),
        repo_id=f"rerank-test/{suffix}",
        score=kwargs.pop("score", 0.7),
        base_score=kwargs.pop("base_score", 0.7),
        match_score=kwargs.pop("match_score", 0.7),
        reason="测试推荐",
        status=kwargs.pop("status", "new"),
        **kwargs,
    )
    db.add(row)
    db.commit()
    return row


def test_weight_normalization_and_score() -> None:
    weights = RerankWeights(relevance=1, affinity=0, freshness=0, momentum=0, popularity=0, health=0)
    assert weights.normalized()["relevance"] == 1.0
    assert weighted_score({"relevance": 0.8}, weights) == pytest.approx(0.8)

    zero = RerankWeights(relevance=0, affinity=0, freshness=0, momentum=0, popularity=0, health=0)
    assert zero.normalized()["relevance"] == 1.0


def test_affinity_matches_language_and_tech_stack() -> None:
    terms = build_interest_terms(["Python"], ["FastAPI", "SQLAlchemy"])
    candidate = RerankCandidate(
        repo_id="a/b", base_score=0.5, language="python", tech_stack=("FastAPI", "Redis")
    )
    assert affinity_score(candidate, terms) > 0.5
    unrelated = RerankCandidate(repo_id="c/d", base_score=0.5, language="Rust")
    assert affinity_score(unrelated, terms) == 0.0
    assert affinity_score(candidate, set()) == 0.0


def test_freshness_decays_and_defaults_neutral() -> None:
    now = datetime(2026, 10, 22)
    assert freshness_score(now, now) == pytest.approx(1.0)
    assert freshness_score(now - timedelta(days=180), now) == pytest.approx(0.5, abs=0.01)
    assert freshness_score(None, now) == 0.5


def test_health_prefers_measured_score_and_penalizes_archived() -> None:
    measured = RerankCandidate(repo_id="a/b", base_score=0.5, health_score=80)
    assert health_score(measured) == pytest.approx(0.8)
    archived = RerankCandidate(repo_id="a/b", base_score=0.5, archived=True, health_score=100)
    assert health_score(archived) == 0.0
    sparse = RerankCandidate(repo_id="a/b", base_score=0.5)
    assert health_score(sparse) == 0.0
    rich = RerankCandidate(
        repo_id="a/b",
        base_score=0.5,
        description="x",
        readme_summary="y",
        license_spdx="MIT",
        language="Python",
        tech_stack=("FastAPI",),
    )
    assert health_score(rich) == pytest.approx(1.0)


def test_rerank_promotes_affinity_and_health() -> None:
    candidates = [
        RerankCandidate(repo_id="a/high-base", base_score=0.90, language="Go"),
        RerankCandidate(
            repo_id="b/fit",
            base_score=0.85,
            language="Python",
            tech_stack=("FastAPI",),
            description="web framework",
            readme_summary="summary",
            license_spdx="MIT",
            health_score=90,
        ),
    ]
    result = rerank_candidates(
        candidates,
        weights=RerankWeights(
            relevance=0.2, affinity=0.4, freshness=0.0, momentum=0.0, popularity=0.0, health=0.4
        ),
        top_k=2,
        mmr_lambda=1.0,
        interest_terms={"python", "fastapi"},
    )
    assert [item.repo_id for item in result.items] == ["b/fit", "a/high-base"]
    assert result.items[0].rank_before == 2
    assert result.items[0].rank_after == 1
    assert result.items[0].reasons
    assert result.metrics["movedUp"] == 1


def test_mmr_penalizes_near_duplicates() -> None:
    candidates = [
        RerankCandidate(repo_id="a", base_score=0.90, vector=(1.0, 0.0), language="Python"),
        RerankCandidate(repo_id="b", base_score=0.88, vector=(1.0, 0.01), language="Python"),
        RerankCandidate(repo_id="c", base_score=0.80, vector=(0.0, 1.0), language="Rust"),
    ]
    result = rerank_candidates(
        candidates,
        weights=RerankWeights(
            relevance=1, affinity=0, freshness=0, momentum=0, popularity=0, health=0
        ),
        top_k=2,
        mmr_lambda=0.5,
    )
    assert [item.repo_id for item in result.items] == ["a", "c"]
    assert result.metrics["diversityAfter"] > 0
    assert "多样性" in result.items[1].reasons[-1] or result.items[1].diversity_penalty >= 0


def test_rerank_empty_and_deterministic() -> None:
    assert rerank_candidates([], top_k=5).items == ()
    candidates = [
        RerankCandidate(repo_id="b", base_score=0.5),
        RerankCandidate(repo_id="a", base_score=0.5),
    ]
    first = rerank_candidates(candidates, top_k=2, mmr_lambda=1.0)
    second = rerank_candidates(list(reversed(candidates)), top_k=2, mmr_lambda=1.0)
    assert [item.repo_id for item in first.items] == ["a", "b"]
    assert [item.repo_id for item in second.items] == ["a", "b"]


def test_generate_persists_rerank_fields(db) -> None:
    db.add(
        MyRepository(
            id="rerank-test/my",
            platform="github",
            name="fastapi",
            description="python web framework",
            html_url="https://example.com/rerank-test/my",
            stars=10,
            language="Python",
        )
    )
    db.commit()
    _seed_repo(
        db,
        "fit",
        name="fastapi-demo",
        description="python web framework",
        tech_stack="Python / FastAPI",
        stars_today=100,
        language="Python",
    )
    _seed_repo(
        db,
        "other",
        name="rust-game",
        description="rust game engine",
        tech_stack="Rust",
        stars_today=50,
        language="Rust",
    )

    result = generate_for_user(
        db, "rerank-test-gen", service=EmbeddingService(force_fallback=True), min_score=0.0
    )
    assert result["status"] == "ok"
    assert result["rerank"]["enabled"] is True
    assert result["rerank"]["metrics"]["selected"] == result["selected"]

    db.expire_all()
    rows = db.execute(
        select(Recommendation).where(Recommendation.user_id == "rerank-test-gen")
    ).scalars().all()
    assert rows
    for row in rows:
        assert row.base_score > 0
        assert row.rerank_score > 0
        assert row.rerank_rank is not None
        assert row.reranked_at is not None
        detail = json.loads(row.rerank_detail or "{}")
        assert {"repoId", "baseScore", "rerankScore", "rankBefore", "rankAfter"} <= set(detail)
        assert detail["signals"].keys() >= {
            "relevance",
            "affinity",
            "freshness",
            "momentum",
            "popularity",
            "health",
        }


def test_rerank_for_user_preview_and_apply(db) -> None:
    _seed_repo(
        db,
        "fit",
        name="fastapi-demo",
        description="python web framework",
        tech_stack="Python / FastAPI",
        stars_today=100,
        language="Python",
        stars=500,
    )
    _seed_repo(
        db,
        "other",
        name="rust-game",
        description="rust game engine",
        tech_stack="Rust",
        stars_today=50,
        language="Rust",
        stars=200,
    )
    db.add(
        MyRepository(
            id="rerank-test/my",
            platform="github",
            name="fastapi",
            description="python web framework",
            html_url="https://example.com/rerank-test/my",
            stars=10,
            language="Python",
        )
    )
    db.commit()
    _seed_rec(db, "fit", base_score=0.80, score=0.80)
    _seed_rec(db, "other", base_score=0.90, score=0.90)

    preview = rerank_for_user(db, USER, top_k=2, pool_size=10, mmr_lambda=1.0)
    assert preview["status"] == "ok"
    assert preview["applied"] is False
    assert len(preview["items"]) == 2
    assert preview["metrics"]["total"] == 2

    applied = rerank_for_user(db, USER, top_k=2, pool_size=10, mmr_lambda=1.0, apply=True)
    assert applied["applied"] is True
    db.expire_all()
    rows = {
        row.repo_id: row
        for row in db.execute(
            select(Recommendation).where(Recommendation.user_id == USER)
        ).scalars().all()
    }
    assert rows["rerank-test/fit"].rerank_rank == 1
    assert rows["rerank-test/fit"].rerank_score > rows["rerank-test/other"].rerank_score


def test_api_preview_and_apply(db) -> None:
    _seed_repo(
        db,
        "api",
        name="api-demo",
        description="python web framework",
        tech_stack="Python",
        stars_today=10,
        language="Python",
    )
    _seed_rec(db, "api", base_score=0.7, score=0.7)

    with TestClient(app) as client:
        preview = client.post(
            "/api/recommend/rerank/preview",
            json={"userId": USER, "topK": 5, "poolSize": 10},
        )
        assert preview.status_code == 200
        payload = preview.json()
        assert payload["status"] == "ok"
        assert payload["items"][0]["repoId"] == "rerank-test/api"
        assert payload["items"][0]["signals"]["relevance"] == pytest.approx(0.7, abs=1e-3)

        applied = client.post(
            "/api/recommend/rerank/apply",
            json={"userId": USER, "topK": 5, "poolSize": 10},
        )
        assert applied.status_code == 200
        assert applied.json()["applied"] is True

    db.expire_all()
    row = db.execute(
        select(Recommendation).where(Recommendation.user_id == USER)
    ).scalars().first()
    assert row is not None and row.rerank_rank == 1


def test_sqlite_backfill_adds_rerank_columns(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from sqlalchemy import create_engine, inspect, text

    import app.db as db_module

    legacy = create_engine(f"sqlite:///{tmp_path / 'legacy-rerank.db'}")
    with legacy.begin() as connection:
        connection.execute(text("CREATE TABLE recommendations (id TEXT PRIMARY KEY)"))

    monkeypatch.setattr(db_module, "engine", legacy)
    monkeypatch.setattr(
        db_module, "settings", SimpleNamespace(DATABASE_URL="sqlite:///legacy-rerank.db")
    )
    db_module._ensure_sqlite_columns()

    columns = {column["name"] for column in inspect(legacy).get_columns("recommendations")}
    assert {"base_score", "rerank_score", "rerank_rank", "rerank_detail", "reranked_at"} <= columns
