"""推荐理由落库 / 回填 / API 契约测试（临时 SQLite + mock 向量，无网络）。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import Category, MyRepository, Recommendation, TrendingRepository
from app.tasks.jobs import generate_recommendations, regenerate_recommendation_reasons

USER_ID = "u-reason-test"
MY_REPO_ID = "my/reason-test"
TREND_REPO_ID = "trend/reason-test"


class FakeEmbedding:
    """固定二维向量：目标仓库与收藏仓库同向，其他为反向。"""

    model_name = "fake-embedding"
    backend = "hash"

    @staticmethod
    def _vec(text: str) -> list[float]:
        if MY_REPO_ID in text or TREND_REPO_ID in text:
            return [1.0, 0.0]
        return [0.0, 1.0]

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(text) for text in texts]

    def encode_one(self, text: str) -> list[float]:
        return self._vec(text)

    def normalize(self, vec: list[float]) -> list[float]:
        return vec


def _cleanup(db) -> None:
    db.execute(delete(Recommendation).where(Recommendation.user_id == USER_ID))
    db.execute(delete(TrendingRepository).where(TrendingRepository.id == TREND_REPO_ID))
    db.execute(delete(MyRepository).where(MyRepository.id == MY_REPO_ID))
    db.execute(delete(Category).where(Category.id == "cat-reason"))
    db.commit()


@pytest.fixture()
def seeded_db(monkeypatch):
    init_db()
    db = SessionLocal()
    try:
        _cleanup(db)
        db.add(Category(id="cat-reason", name="后端开发"))
        db.add(
            MyRepository(
                id=MY_REPO_ID,
                name=MY_REPO_ID,
                description="FastAPI 支付服务",
                html_url=f"https://github.com/{MY_REPO_ID}",
                language="Python",
                category_id="cat-reason",
            )
        )
        db.add(
            TrendingRepository(
                id=TREND_REPO_ID,
                name=TREND_REPO_ID,
                html_url=f"https://github.com/{TREND_REPO_ID}",
                stars_today=120,
                description="一个支付后端服务",
                tech_stack="Python, FastAPI, Redis",
            )
        )
        db.commit()
    finally:
        db.close()

    fake = FakeEmbedding()
    monkeypatch.setattr("app.services.embedding.get_embedding_service", lambda: fake)
    monkeypatch.setattr("app.api.recommend.get_embedding_service", lambda: fake)
    yield fake

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()


def test_generate_recommendations_persists_reason_and_based_on(seeded_db) -> None:
    result = generate_recommendations.run(user_id=USER_ID, top_k=1)

    assert result["status"] == "ok"
    db = SessionLocal()
    try:
        row = db.execute(
            select(Recommendation).where(
                Recommendation.user_id == USER_ID,
                Recommendation.repo_id == TREND_REPO_ID,
            )
        ).scalar_one()
        assert "高度相似" in (row.reason or "")
        assert "FastAPI" in (row.reason or "")
        assert "120 stars" in (row.reason or "")
        basis = json.loads(row.based_on or "[]")
        assert "相似度 100%" in basis
        assert "技术栈 FastAPI" in basis
    finally:
        db.close()


def test_regenerate_reasons_backfills_existing_rows(seeded_db) -> None:
    generate_recommendations.run(user_id=USER_ID, top_k=1)

    db = SessionLocal()
    try:
        row = db.execute(
            select(Recommendation).where(Recommendation.user_id == USER_ID)
        ).scalar_one()
        row.reason = ""
        row.based_on = None
        db.commit()
    finally:
        db.close()

    result = regenerate_recommendation_reasons.run(user_id=USER_ID, limit=10)

    assert result["status"] == "ok"
    assert result["updated"] == 1
    db = SessionLocal()
    try:
        row = db.execute(
            select(Recommendation).where(Recommendation.user_id == USER_ID)
        ).scalar_one()
        assert row.reason
        assert row.based_on
    finally:
        db.close()


def test_recommend_list_api_returns_based_on(seeded_db) -> None:
    generate_recommendations.run(user_id=USER_ID, top_k=1)

    with TestClient(app) as client:
        resp = client.get("/api/recommend/list", params={"user_id": USER_ID})

    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["reason"]
    assert isinstance(items[0]["based_on"], list)
    assert items[0]["based_on"]


def test_recommend_query_api_returns_based_on(seeded_db) -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/recommend/query",
            json={"query": "支付后端", "top_k": 5},
        )

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items
    assert items[0]["reason"]
    assert items[0]["based_on"]
    assert "相似度" in items[0]["based_on"][0]


def test_init_db_adds_based_on_column_to_old_sqlite(tmp_path, monkeypatch) -> None:
    import app.db as db_module

    url = f"sqlite:///{tmp_path / 'old.db'}"
    old_engine = create_engine(url)
    with old_engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE recommendations ("
            "id TEXT PRIMARY KEY, user_id TEXT, repo_id TEXT, score REAL, "
            "reason TEXT, status TEXT, created_at DATETIME)"
        )

    monkeypatch.setattr(db_module, "engine", old_engine)
    monkeypatch.setattr(db_module, "settings", SimpleNamespace(DATABASE_URL=url))
    db_module.init_db()

    with old_engine.begin() as conn:
        columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(recommendations)")
        }
    assert "based_on" in columns
