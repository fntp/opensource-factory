"""本机一体化只读 API / 静态托管测试（REQ-202610-0940 / M5-02）。

不访问网络：全部使用临时 SQLite 与本地静态文件。
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.models import Category, MyRepository, Recommendation, TrendingRepository


@pytest.fixture()
def db():
    """每个用例前清空本机镜像表，避免用例间串数据。"""
    init_db()
    session = SessionLocal()
    try:
        for model in (Recommendation, TrendingRepository, MyRepository, Category):
            session.query(model).delete()
        session.commit()
        yield session
    finally:
        session.rollback()
        session.close()


def _seed_repos(db) -> None:
    db.add_all(
        [
            MyRepository(
                id="acme/pay",
                name="pay",
                description="支付网关",
                html_url="https://github.com/acme/pay",
                stars=120,
                language="Python",
                category_id="cat-pay",
            ),
            MyRepository(
                id="acme/web",
                name="web",
                description="前端脚手架",
                html_url="https://github.com/acme/web",
                stars=30,
                language="TypeScript",
                category_id="cat-web",
            ),
        ]
    )
    db.add_all(
        [
            Category(id="cat-pay", name="支付系统"),
            Category(id="cat-web", name="前端开发"),
        ]
    )
    db.commit()


def test_local_status_and_auth_me(db) -> None:
    with TestClient(app) as client:
        status_resp = client.get("/local/api/local/status")
        me_resp = client.get("/local/api/auth/me")

    assert status_resp.status_code == 200
    status = status_resp.json()
    assert status["mode"] == "local"
    assert status["readOnly"] is True
    assert status["userId"] == "local-test"
    assert status["database"] == "sqlite"

    assert me_resp.status_code == 200
    assert me_resp.json() == {
        "id": "local-test",
        "login": "local-test",
        "name": "本机测试用户",
        "email": None,
        "avatarUrl": None,
    }


def test_repos_contract_and_filters(db) -> None:
    _seed_repos(db)

    with TestClient(app) as client:
        all_resp = client.get("/local/api/repos")
        q_resp = client.get("/local/api/repos", params={"q": "支付"})
        cat_resp = client.get("/local/api/repos", params={"categoryId": "cat-web"})

    assert all_resp.status_code == 200
    rows = all_resp.json()
    assert [row["id"] for row in rows] == ["acme/pay", "acme/web"]
    first = rows[0]
    assert first["fullName"] == "acme/pay"
    assert first["category"] == "支付系统"
    assert first["stars"] == 120
    assert first["forks"] == 0
    assert first["tags"] == []
    assert first["url"] == "https://github.com/acme/pay"
    assert first["updatedAt"]

    assert [row["id"] for row in q_resp.json()] == ["acme/pay"]
    assert [row["id"] for row in cat_resp.json()] == ["acme/web"]


def test_trending_and_recommendations_contract(db) -> None:
    _seed_repos(db)
    db.add(
        TrendingRepository(
            id="hot/project",
            name="project",
            html_url="https://github.com/hot/project",
            stars_today=88,
            stars=900,
            description="今日热门",
            owner="hot",
            language="Go",
            crawled_at=date.today(),
        )
    )
    db.add(
        Recommendation(
            id="rec-1",
            user_id="local-test",
            repo_id="acme/pay",
            score=0.91,
            reason="与支付技术栈匹配",
            based_on='["stars", "language"]',
            status="new",
        )
    )
    db.commit()

    with TestClient(app) as client:
        trending = client.get("/local/api/trending", params={"limit": 10}).json()
        recommendations = client.get("/local/api/recommendations").json()

    assert trending[0]["id"] == "hot/project"
    assert trending[0]["owner"] == "hot"
    assert trending[0]["starsToday"] == 88
    assert trending[0]["stars"] == 900
    assert trending[0]["language"] == "Go"

    assert len(recommendations) == 1
    rec = recommendations[0]
    assert rec["id"] == "rec-1"
    assert rec["owner"] == "acme"
    assert rec["name"] == "pay"
    assert rec["description"] == "支付网关"
    assert rec["stars"] == 120
    assert rec["score"] == pytest.approx(0.91)
    assert rec["basedOn"] == ["stars", "language"]
    assert rec["url"] == "https://github.com/acme/pay"


def test_categories_and_dashboard_stats(db) -> None:
    _seed_repos(db)

    with TestClient(app) as client:
        categories = client.get("/local/api/categories").json()
        stats = client.get("/local/api/dashboard/stats").json()

    assert [item["name"] for item in categories["categories"]] == ["前端开发", "支付系统"]
    assert {item["id"]: item["count"] for item in categories["categories"]} == {
        "cat-pay": 1,
        "cat-web": 1,
    }
    assert categories["tags"] == []

    assert stats == {
        "totalRepos": 2,
        "trendingToday": 0,
        "pendingRecommendations": 0,
        "categoryCount": 2,
    }


def test_local_mode_disabled_returns_404(monkeypatch) -> None:
    import app.api.local as local_api

    class _Disabled:
        LOCAL_MODE = False

    monkeypatch.setattr(local_api, "get_settings", lambda: _Disabled())
    with TestClient(app) as client:
        resp = client.get("/local/api/local/status")
    assert resp.status_code == 404


def test_admin_static_and_spa_fallback(db) -> None:
    admin_dir = Path(os.environ["LOCAL_ADMIN_DIR"])
    admin_dir.mkdir(parents=True, exist_ok=True)
    (admin_dir / "index.html").write_text("<!doctype html><title>OpenFactory</title>", encoding="utf-8")
    (admin_dir / "assets").mkdir(exist_ok=True)
    (admin_dir / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")

    try:
        with TestClient(app) as client:
            root = client.get("/")
            asset = client.get("/assets/app.js")
            spa = client.get("/repos/acme/pay")
            traversal = client.get("/%2e%2e/%2e%2e/etc/passwd")

        assert root.status_code == 200
        assert "OpenFactory" in root.text
        assert asset.status_code == 200
        assert "console.log" in asset.text
        assert spa.status_code == 200
        assert "OpenFactory" in spa.text
        assert traversal.status_code == 404
    finally:
        for path in sorted(admin_dir.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        admin_dir.rmdir()
