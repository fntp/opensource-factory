"""热榜 Celery 任务测试：抓取器打桩，验证多语言参数、落库字段与降级状态。"""
from __future__ import annotations

from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.models import TrendingRepository
from app.tasks import jobs


def _item(repo_id: str, **overrides) -> dict:
    owner, name = repo_id.split("/", 1)
    item = {
        "id": repo_id,
        "platform": "github",
        "owner": owner,
        "name": name,
        "html_url": f"https://github.com/{repo_id}",
        "description": f"{name} description",
        "language": "Python",
        "stars_today": 120,
        "stars": 900,
        "trending_pages": ["all", "python"],
    }
    item.update(overrides)
    return item


def _cleanup(repo_ids: list[str]) -> None:
    db = SessionLocal()
    try:
        db.execute(delete(TrendingRepository).where(TrendingRepository.id.in_(repo_ids)))
        db.commit()
    finally:
        db.close()


def test_crawl_trending_persists_multi_language_fields(monkeypatch) -> None:
    init_db()
    calls: dict = {}

    async def fake_pages(languages=None, since="daily", **kwargs):
        calls["languages"] = languages
        calls["since"] = since
        return {
            "items": [
                _item("req0909/alpha"),
                _item(
                    "req0909/beta",
                    language="",
                    stars_today=0,
                    stars=0,
                    description="",
                ),
            ],
            "pages": [{"language": "all", "count": 2, "ok": True, "error": None}],
            "failedPages": [],
        }

    monkeypatch.setattr("app.services.trending_crawler.crawl_github_trending_pages", fake_pages)
    try:
        result = jobs.crawl_trending.run(
            platform="github", languages="python,rust", since="daily"
        )
        assert result["status"] == "ok"
        assert result["total"] == 2
        assert result["created"] == 2
        assert result["failedPages"] == []
        assert calls == {"languages": "python,rust", "since": "daily"}

        db = SessionLocal()
        try:
            alpha = db.get(TrendingRepository, "req0909/alpha")
            assert alpha is not None
            assert alpha.owner == "req0909"
            assert alpha.language == "Python"
            assert alpha.stars == 900
            assert alpha.stars_today == 120
            assert alpha.tech_stack
            beta = db.get(TrendingRepository, "req0909/beta")
            assert beta is not None
            assert beta.language is None
            assert beta.stars == 0
        finally:
            db.close()
    finally:
        _cleanup(["req0909/alpha", "req0909/beta"])


def test_crawl_trending_returns_partial_when_some_pages_fail(monkeypatch) -> None:
    init_db()

    async def fake_pages(languages=None, since="daily", **kwargs):
        return {
            "items": [_item("req0909/partial")],
            "pages": [
                {"language": "all", "count": 1, "ok": True, "error": None},
                {"language": "rust", "count": 0, "ok": False, "error": "HTTP 500"},
            ],
            "failedPages": [
                {"language": "rust", "count": 0, "ok": False, "error": "HTTP 500"}
            ],
        }

    monkeypatch.setattr("app.services.trending_crawler.crawl_github_trending_pages", fake_pages)
    try:
        result = jobs.crawl_trending.run(platform="github", languages=["python", "rust"])
        assert result["status"] == "partial"
        assert result["total"] == 1
        assert result["failedPages"][0]["language"] == "rust"
    finally:
        _cleanup(["req0909/partial"])


def test_crawl_trending_returns_error_when_all_pages_fail(monkeypatch) -> None:
    async def fake_pages(languages=None, since="daily", **kwargs):
        failed = {"language": "all", "count": 0, "ok": False, "error": "HTTP 503"}
        return {"items": [], "pages": [failed], "failedPages": [failed]}

    monkeypatch.setattr("app.services.trending_crawler.crawl_github_trending_pages", fake_pages)
    result = jobs.crawl_trending.run(platform="github")
    assert result["status"] == "error"
    assert result["total"] == 0
    assert result["failedPages"][0]["error"] == "HTTP 503"


def test_crawl_trending_single_language_uses_single_page(monkeypatch) -> None:
    init_db()
    calls: dict = {}

    async def fake_pages(languages=None, since="daily", include_global=True, **kwargs):
        calls["languages"] = languages
        calls["since"] = since
        calls["include_global"] = include_global
        return {
            "items": [_item("req0909/single")],
            "pages": [{"language": "go", "count": 1, "ok": True, "error": None}],
            "failedPages": [],
        }

    monkeypatch.setattr("app.services.trending_crawler.crawl_github_trending_pages", fake_pages)
    try:
        result = jobs.crawl_trending.run(platform="github", language="Go", since="weekly")
        assert result["status"] == "ok"
        assert calls == {"languages": ["Go"], "since": "weekly", "include_global": False}
        assert result["pages"] == [
            {"language": "go", "count": 1, "ok": True, "error": None}
        ]
    finally:
        _cleanup(["req0909/single"])
