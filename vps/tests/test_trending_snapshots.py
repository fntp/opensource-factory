"""热榜按日快照（M2-05）：去重、排名、趋势字段、幂等入库与接口。"""
from __future__ import annotations

from datetime import date, timedelta

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import TrendingRepository, TrendingSnapshot
from app.services.trending_snapshot import (
    build_snapshot_rows,
    push_trending_snapshots,
    save_trending_snapshots,
)
from app.tasks import jobs

SNAPSHOT_DATE = date(2026, 10, 22)


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
        "stars_today": 10,
        "stars": 100,
        "trending_pages": ["all"],
    }
    item.update(overrides)
    return item


def _cleanup(repo_ids: list[str]) -> None:
    db = SessionLocal()
    try:
        db.execute(delete(TrendingSnapshot).where(TrendingSnapshot.repo_id.in_(repo_ids)))
        db.execute(delete(TrendingRepository).where(TrendingRepository.id.in_(repo_ids)))
        db.commit()
    finally:
        db.close()


def test_build_snapshot_rows_dedupes_and_ranks() -> None:
    items = [
        _item("req0913/alpha", stars_today=10, stars=100, trending_pages=["all"]),
        _item("req0913/alpha", stars_today=30, stars=120, trending_pages=["python"]),
        _item("req0913/beta", stars_today=50, stars=200, language="Go"),
        _item("req0913/gamma", stars_today=20, stars=50, language="Go"),
    ]

    rows = build_snapshot_rows(items, SNAPSHOT_DATE, {})

    assert [row["repo_id"] for row in rows] == [
        "req0913/beta",
        "req0913/alpha",
        "req0913/gamma",
    ]
    alpha = rows[1]
    assert alpha["stars"] == 120
    assert alpha["stars_today"] == 30
    assert alpha["language"] == "Python"
    assert alpha["rank"] == 2
    assert alpha["language_rank"] == 1
    assert alpha["trending_pages"] == '["all", "python"]'
    # 同一语言内按综合排名依次编号
    assert rows[0]["language_rank"] == 1  # Go: beta
    assert rows[2]["language_rank"] == 2  # Go: gamma


def test_build_snapshot_rows_computes_trend_fields() -> None:
    previous = {
        "req0913/alpha": {
            "snapshot_date": SNAPSHOT_DATE - timedelta(days=1),
            "stars": 100,
            "rank": 1,
            "appearances": 2,
        },
        "req0913/beta": {
            "snapshot_date": SNAPSHOT_DATE - timedelta(days=1),
            "stars": 190,
            "rank": 10,
            "appearances": 1,
        },
    }
    items = [
        _item("req0913/beta", stars_today=50, stars=200, language="Go"),
        _item("req0913/alpha", stars_today=30, stars=130),
        _item("req0913/gamma", stars_today=20, stars=50, language="Go"),
    ]

    rows = {row["repo_id"]: row for row in build_snapshot_rows(items, SNAPSHOT_DATE, previous)}

    beta = rows["req0913/beta"]
    assert beta["rank"] == 1
    assert beta["star_delta"] == 10
    assert beta["rank_delta"] == 9
    assert beta["appearances"] == 2
    assert beta["is_new"] == 0
    assert beta["trend"] == "up"

    alpha = rows["req0913/alpha"]
    assert alpha["rank"] == 2
    assert alpha["star_delta"] == 30
    assert alpha["rank_delta"] == -1
    assert alpha["appearances"] == 3
    assert alpha["trend"] == "steady"

    gamma = rows["req0913/gamma"]
    assert gamma["is_new"] == 1
    assert gamma["appearances"] == 1
    assert gamma["star_delta"] == 0
    assert gamma["trend"] == "new"


def test_build_snapshot_rows_resets_appearances_after_gap() -> None:
    previous = {
        "req0913/alpha": {
            "snapshot_date": SNAPSHOT_DATE - timedelta(days=3),
            "stars": 100,
            "rank": 1,
            "appearances": 5,
        }
    }
    rows = build_snapshot_rows([_item("req0913/alpha")], SNAPSHOT_DATE, previous)
    assert rows[0]["appearances"] == 1
    assert rows[0]["is_new"] == 0
    assert rows[0]["star_delta"] == 0


def test_save_trending_snapshots_is_idempotent() -> None:
    init_db()
    repo_ids = ["req0913/idem-a", "req0913/idem-b"]
    _cleanup(repo_ids)
    db = SessionLocal()
    try:
        first = save_trending_snapshots(
            db,
            [_item(repo_ids[0], stars=100), _item(repo_ids[1], stars=50, stars_today=5)],
            snapshot_date=SNAPSHOT_DATE,
        )
        assert first["created"] == 2
        assert first["updated"] == 0

        second = save_trending_snapshots(
            db,
            [_item(repo_ids[0], stars=130), _item(repo_ids[1], stars=60, stars_today=5)],
            snapshot_date=SNAPSHOT_DATE,
        )
        assert second["created"] == 0
        assert second["updated"] == 2

        count = db.execute(
            select(func.count()).select_from(TrendingSnapshot).where(
                TrendingSnapshot.snapshot_date == SNAPSHOT_DATE,
                TrendingSnapshot.repo_id.in_(repo_ids),
            )
        ).scalar_one()
        assert count == 2
        alpha = db.get(TrendingSnapshot, (SNAPSHOT_DATE, repo_ids[0]))
        assert alpha is not None and alpha.stars == 130
    finally:
        db.close()
        _cleanup(repo_ids)


def test_crawl_trending_persists_daily_snapshots(monkeypatch) -> None:
    init_db()
    repo_ids = ["req0913/job-a", "req0913/job-b"]
    _cleanup(repo_ids)

    async def fake_pages(languages=None, since="daily", **kwargs):
        return {
            "items": [
                _item(repo_ids[0], stars_today=80, stars=800),
                _item(repo_ids[1], stars_today=20, stars=200, language="Go"),
            ],
            "pages": [{"language": "all", "count": 2, "ok": True, "error": None}],
            "failedPages": [],
        }

    monkeypatch.setattr("app.services.trending_crawler.crawl_github_trending_pages", fake_pages)
    try:
        result = jobs.crawl_trending.run(platform="github", languages="python")
        assert result["status"] == "ok"
        snapshots = result["snapshots"]
        assert snapshots["date"] == date.today().isoformat()
        assert snapshots["total"] == 2
        assert snapshots["skipped"] is True  # 未配置 EDGE_BASE_URL

        db = SessionLocal()
        try:
            rows = db.execute(
                select(TrendingSnapshot)
                .where(
                    TrendingSnapshot.snapshot_date == date.today(),
                    TrendingSnapshot.repo_id.in_(repo_ids),
                )
                .order_by(TrendingSnapshot.rank.asc())
            ).scalars().all()
            assert len(rows) == 2
            assert rows[0].repo_id == repo_ids[0]
            assert rows[0].rank == 1
            assert rows[1].trend == "new"
        finally:
            db.close()
    finally:
        _cleanup(repo_ids)


def test_snapshot_api_filters_by_date_and_language() -> None:
    init_db()
    repo_ids = ["req0913/api-py", "req0913/api-go"]
    _cleanup(repo_ids)
    db = SessionLocal()
    try:
        save_trending_snapshots(
            db,
            [
                _item(repo_ids[0], stars_today=30, stars=300, language="Python"),
                _item(repo_ids[1], stars_today=20, stars=200, language="Go"),
            ],
            snapshot_date=SNAPSHOT_DATE,
        )
    finally:
        db.close()

    try:
        with TestClient(app) as client:
            resp = client.get("/api/trending/snapshots", params={"date": SNAPSHOT_DATE.isoformat()})
            assert resp.status_code == 200
            body = resp.json()
            returned = [row["repo_id"] for row in body]
            # 同一测试库可能有其他用例写入的同日快照，只校验本次数据存在且顺序正确
            assert set(repo_ids) <= set(returned)
            assert returned.index(repo_ids[0]) < returned.index(repo_ids[1])
            ours = [row for row in body if row["repo_id"] in repo_ids]
            assert ours[0]["rank"] < ours[1]["rank"]

            resp = client.get(
                "/api/trending/snapshots",
                params={"date": SNAPSHOT_DATE.isoformat(), "language": "go"},
            )
            assert resp.status_code == 200
            go_rows = resp.json()
            assert repo_ids[1] in [row["repo_id"] for row in go_rows]
            assert all((row["language"] or "").lower() == "go" for row in go_rows)

            resp = client.get("/api/trending/dates")
            assert resp.status_code == 200
            dates = {row["date"]: row["count"] for row in resp.json()}
            assert dates.get(SNAPSHOT_DATE.isoformat(), 0) >= 2

            resp = client.get("/api/trending/history", params={"repoId": repo_ids[0], "days": 7})
            assert resp.status_code == 200
            assert len(resp.json()) == 1
    finally:
        _cleanup(repo_ids)


def test_push_trending_snapshots_posts_camel_case_batches() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Internal-Token") == "test-token"
        captured.append(request.read().decode())
        return httpx.Response(200, json={"upserted": 1})

    rows = build_snapshot_rows([_item("req0913/push")], SNAPSHOT_DATE, {})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = push_trending_snapshots(
            rows,
            SNAPSHOT_DATE,
            base_url="https://edge.example",
            token="test-token",
            client=client,
        )
    finally:
        client.close()

    assert result == {"skipped": False, "pushed": 1, "failed": 0, "batches": 1}
    assert '"repoId":"req0913/push"' in captured[0]
    assert '"snapshotDate":"2026-10-22"' in captured[0]


def test_push_trending_snapshots_skips_without_configuration() -> None:
    rows = build_snapshot_rows([_item("req0913/skip")], SNAPSHOT_DATE, {})
    result = push_trending_snapshots(rows, SNAPSHOT_DATE, base_url="", token="")
    assert result["skipped"] is True
    assert result["pushed"] == 0
