"""热榜数据保留策略（M2-08）：归档、窗口清理、dry-run、失败保护与 edge 清理。"""
from __future__ import annotations

import gzip
import json
import os
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import TrendingSnapshot
from app.services import trending_retention
from app.services.trending_retention import (
    cleanup_edge_trending_snapshots,
    cleanup_trending_snapshots,
    prune_archives,
    retention_status,
)

TODAY = date(2026, 10, 22)
PREFIX = "req0916/"


def _snapshot(repo_id: str, snapshot_date: date, **overrides) -> TrendingSnapshot:
    owner, name = repo_id.split("/", 1)
    values = {
        "snapshot_date": snapshot_date,
        "repo_id": repo_id,
        "platform": "github",
        "owner": owner,
        "name": name,
        "html_url": f"https://github.com/{repo_id}",
        "description": f"{name} description",
        "language": "Python",
        "tech_stack": "Python",
        "stars": 100,
        "stars_today": 10,
        "rank": 1,
        "language_rank": 1,
        "star_delta": 5,
        "rank_delta": 1,
        "appearances": 2,
        "is_new": 0,
        "trend": "up",
        "trending_pages": '["all"]',
    }
    values.update(overrides)
    return TrendingSnapshot(**values)


def _cleanup_rows() -> None:
    db = SessionLocal()
    try:
        db.execute(delete(TrendingSnapshot).where(TrendingSnapshot.repo_id.like(f"{PREFIX}%")))
        db.commit()
    finally:
        db.close()


def _read_archive(path: str) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_archive_and_cleanup_window(tmp_path) -> None:
    init_db()
    _cleanup_rows()
    db = SessionLocal()
    try:
        db.add_all(
            [
                _snapshot(f"{PREFIX}old-a", TODAY - timedelta(days=120)),
                _snapshot(f"{PREFIX}old-b", TODAY - timedelta(days=91)),
                _snapshot(f"{PREFIX}boundary", TODAY - timedelta(days=90)),
                _snapshot(f"{PREFIX}recent", TODAY - timedelta(days=30)),
            ]
        )
        db.commit()

        result = cleanup_trending_snapshots(
            db,
            today=TODAY,
            retention_days=90,
            archive=True,
            archive_dir=tmp_path,
            archive_keep_days=365,
        )

        assert result["status"] == "ok"
        assert result["cutoff"] == "2026-07-24"
        assert result["expired"] == 2
        assert result["archived"] == 2
        assert result["deleted"] == 2
        assert result["archiveFile"]
        assert os.path.exists(result["archiveFile"])

        records = _read_archive(result["archiveFile"])
        assert records[0]["format"] == "openfactory.trending_snapshots"
        assert records[0]["rowCount"] == 2
        archived_ids = {row["repo_id"] for row in records[1:]}
        assert archived_ids == {f"{PREFIX}old-a", f"{PREFIX}old-b"}

        remaining = {
            row.repo_id
            for row in db.execute(
                select(TrendingSnapshot).where(TrendingSnapshot.repo_id.like(f"{PREFIX}%"))
            )
            .scalars()
            .all()
        }
        assert remaining == {f"{PREFIX}boundary", f"{PREFIX}recent"}
    finally:
        db.close()
        _cleanup_rows()


def test_cleanup_dry_run_keeps_data(tmp_path) -> None:
    init_db()
    _cleanup_rows()
    db = SessionLocal()
    try:
        db.add(_snapshot(f"{PREFIX}dry", TODAY - timedelta(days=200)))
        db.commit()

        result = cleanup_trending_snapshots(
            db,
            today=TODAY,
            retention_days=90,
            archive=True,
            archive_dir=tmp_path,
            dry_run=True,
        )

        assert result["status"] == "dry_run"
        assert result["expired"] == 1
        assert result["deleted"] == 0
        assert result["archived"] == 0
        assert not list(tmp_path.glob("trending-snapshots-*.jsonl.gz"))
        assert db.get(TrendingSnapshot, (TODAY - timedelta(days=200), f"{PREFIX}dry")) is not None
    finally:
        db.close()
        _cleanup_rows()


def test_archive_failure_blocks_delete(monkeypatch, tmp_path) -> None:
    init_db()
    _cleanup_rows()
    db = SessionLocal()
    try:
        old_date = TODAY - timedelta(days=200)
        db.add(_snapshot(f"{PREFIX}fail", old_date))
        db.commit()

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(trending_retention, "archive_snapshots", _boom)
        result = cleanup_trending_snapshots(
            db,
            today=TODAY,
            retention_days=90,
            archive=True,
            archive_dir=tmp_path,
        )

        assert result["status"] == "error"
        assert "归档失败" in result["error"]
        assert result["deleted"] == 0
        assert db.get(TrendingSnapshot, (old_date, f"{PREFIX}fail")) is not None
    finally:
        db.close()
        _cleanup_rows()


def test_retention_disabled_keeps_everything() -> None:
    init_db()
    _cleanup_rows()
    db = SessionLocal()
    try:
        old_date = TODAY - timedelta(days=500)
        db.add(_snapshot(f"{PREFIX}disabled", old_date))
        db.commit()

        result = cleanup_trending_snapshots(db, today=TODAY, retention_days=0)

        assert result["status"] == "disabled"
        assert result["cutoff"] is None
        assert result["deleted"] == 0
        assert db.get(TrendingSnapshot, (old_date, f"{PREFIX}disabled")) is not None
    finally:
        db.close()
        _cleanup_rows()


def test_prune_archives_removes_only_expired(tmp_path) -> None:
    old_file = tmp_path / "trending-snapshots-2025-01-01_2025-01-02.jsonl.gz"
    new_file = tmp_path / "trending-snapshots-2026-09-01_2026-09-02.jsonl.gz"
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    old_ts = (now - timedelta(days=60)).timestamp()
    new_ts = (now - timedelta(days=1)).timestamp()
    os.utime(old_file, (old_ts, old_ts))
    os.utime(new_file, (new_ts, new_ts))

    result = prune_archives(tmp_path, keep_days=30, now=now)

    assert result["deleted"] == 1
    assert result["bytes"] == 3
    assert not old_file.exists()
    assert new_file.exists()


def test_retention_status_reports_window_and_usage(tmp_path) -> None:
    init_db()
    _cleanup_rows()
    db = SessionLocal()
    try:
        db.add_all(
            [
                _snapshot(f"{PREFIX}status-old", TODAY - timedelta(days=120)),
                _snapshot(f"{PREFIX}status-new", TODAY - timedelta(days=2)),
            ]
        )
        db.commit()

        status = retention_status(
            db,
            today=TODAY,
            retention_days=90,
            archive_dir=tmp_path,
            archive_keep_days=365,
        )

        assert status["enabled"] is True
        assert status["retentionDays"] == 90
        assert status["cutoff"] == "2026-07-24"
        assert status["totalSnapshots"] >= 2
        assert status["expiredSnapshots"] >= 1
        assert status["oldestDate"] <= (TODAY - timedelta(days=120)).isoformat()
        assert status["archiveDir"] == str(tmp_path)
        assert status["databaseBytes"] > 0
    finally:
        db.close()
        _cleanup_rows()


def test_cleanup_edge_trending_snapshots_posts_request() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["token"] = request.headers.get("X-Internal-Token")
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"deleted": 5})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = cleanup_edge_trending_snapshots(
            date(2026, 7, 24),
            dry_run=True,
            base_url="https://edge.example",
            token="internal-token",
            client=client,
        )
    finally:
        client.close()

    assert result == {"skipped": False, "deleted": 5, "error": None}
    assert str(seen["url"]).endswith("/api/internal/trending/retention/cleanup")
    assert seen["token"] == "internal-token"
    assert seen["body"] == {"beforeDate": "2026-07-24", "dryRun": True}


def test_retention_api_status_and_dry_run_task() -> None:
    init_db()
    client = TestClient(app)

    status_response = client.get("/api/trending/retention")
    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["retentionDays"] >= 0
    assert "expiredSnapshots" in payload
    assert "archiveDir" in payload

    cleanup_response = client.post(
        "/api/trending/retention/cleanup",
        params={"dryRun": "true", "retentionDays": 90},
    )
    assert cleanup_response.status_code == 202
    assert cleanup_response.json()["taskId"]
