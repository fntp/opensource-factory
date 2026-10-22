"""REQ-202610-0914 热榜页 API：日期 / 语言筛选与趋势字段（无网络）。"""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.main import app
from app.models import TrendingRepository, TrendingSnapshot
from app.services.trending_snapshot import save_trending_snapshots

DAY1 = date(2030, 1, 1)
DAY2 = date(2030, 1, 2)
REPO_IDS = ["req0914/page-alpha", "req0914/page-beta", "req0914/page-gamma"]


def _item(repo_id: str, stars_today: int, language: str, stars: int) -> dict:
    owner, name = repo_id.split("/", 1)
    return {
        "id": repo_id,
        "platform": "github",
        "owner": owner,
        "name": name,
        "html_url": f"https://github.com/{repo_id}",
        "description": f"{name} description",
        "language": language,
        "stars": stars,
        "stars_today": stars_today,
        "trending_pages": ["all"],
    }


def _cleanup() -> None:
    db = SessionLocal()
    try:
        db.execute(delete(TrendingSnapshot).where(TrendingSnapshot.repo_id.in_(REPO_IDS)))
        db.execute(delete(TrendingRepository).where(TrendingRepository.id.in_(REPO_IDS)))
        db.commit()
    finally:
        db.close()


def test_trending_list_filters_and_exposes_trend_fields() -> None:
    init_db()
    _cleanup()
    db = SessionLocal()
    try:
        save_trending_snapshots(
            db,
            [
                _item(REPO_IDS[0], 100, "Python", 1000),
                _item(REPO_IDS[1], 50, "Go", 500),
            ],
            snapshot_date=DAY1,
        )
        save_trending_snapshots(
            db,
            [
                _item(REPO_IDS[1], 200, "Go", 800),
                _item(REPO_IDS[0], 80, "Python", 900),
                _item(REPO_IDS[2], 10, "Rust", 100),
            ],
            snapshot_date=DAY2,
        )
    finally:
        db.close()

    try:
        with TestClient(app) as client:
            resp = client.get(
                "/api/trending",
                params={"date": DAY2.isoformat(), "platform": "all", "limit": 100},
            )
            assert resp.status_code == 200
            ours = [row for row in resp.json() if row["id"] in REPO_IDS]
            assert [row["id"] for row in ours] == [
                REPO_IDS[1],
                REPO_IDS[0],
                REPO_IDS[2],
            ]
            assert ours[0]["rank"] == 1
            assert ours[0]["rank_change"] == 1
            assert ours[0]["trend"] == "up"
            assert ours[1]["rank_change"] == -1
            assert ours[1]["trend"] == "down"
            assert ours[2]["rank_change"] is None
            assert ours[2]["trend"] == "new"
            assert ours[0]["snapshot_date"] == DAY2.isoformat()

            filtered = client.get(
                "/api/trending",
                params={"date": DAY2.isoformat(), "platform": "all", "language": "go"},
            )
            assert filtered.status_code == 200
            assert [row["id"] for row in filtered.json() if row["id"] in REPO_IDS] == [
                REPO_IDS[1]
            ]

            languages = client.get(
                "/api/trending/languages", params={"date": DAY2.isoformat()}
            )
            assert languages.status_code == 200
            counts = {
                row["language"]: row["count"]
                for row in languages.json()["languages"]
            }
            assert counts.get("Go", 0) >= 1
            assert counts.get("Python", 0) >= 1
            assert counts.get("Rust", 0) >= 1

            dates = client.get("/api/trending/dates")
            assert dates.status_code == 200
            values = {row["date"] for row in dates.json()}
            assert DAY1.isoformat() in values
            assert DAY2.isoformat() in values
    finally:
        _cleanup()
