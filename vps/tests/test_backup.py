"""备份与恢复测试（REQ-202610-0942 / M5-04）。

覆盖：SQLite 快照 / 校验 / 损坏检测 / 保留清理 / 恢复 / 演练 /
D1 导出校验 / 状态汇总 / CLI / 内部 API 鉴权与路径越界。
"""
from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import backup
from app.config import get_settings


@pytest.fixture()
def sample_db(tmp_path: Path) -> Path:
    path = tmp_path / "source.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE repos (id INTEGER PRIMARY KEY, owner_id INTEGER, name TEXT);
        INSERT INTO users (name) VALUES ('alice'), ('bob');
        INSERT INTO repos (owner_id, name) VALUES (1, 'alpha'), (2, 'beta'), (1, 'gamma');
        """
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def backup_dir(tmp_path: Path) -> Path:
    return tmp_path / "backups"


def _stamp(index: int) -> datetime:
    return datetime(2026, 1, 1, 3, 50, tzinfo=timezone.utc) + timedelta(minutes=index)


def test_snapshot_verify_and_manifest(sample_db: Path, backup_dir: Path) -> None:
    entry = backup.create_sqlite_snapshot(sample_db, backup_dir, label="unit test")
    assert entry.path.is_file()
    assert entry.path.name.startswith("sqlite-")
    assert entry.path.name.endswith(".sqlite3.gz")
    manifest = json.loads(Path(str(entry.path) + ".json").read_text(encoding="utf-8"))
    assert manifest["tableCounts"] == {"repos": 3, "users": 2}
    assert manifest["integrity"] == "ok"
    assert manifest["label"] == "unit-test"

    report = backup.verify_sqlite_snapshot(entry.path)
    assert report["ok"], report
    assert report["tableCounts"] == {"repos": 3, "users": 2}
    assert all(check["ok"] for check in report["checks"])


def test_verify_detects_corrupted_snapshot(sample_db: Path, backup_dir: Path) -> None:
    entry = backup.create_sqlite_snapshot(sample_db, backup_dir)
    data = bytearray(entry.path.read_bytes())
    data[-8] ^= 0xFF
    entry.path.write_bytes(data)
    report = backup.verify_sqlite_snapshot(entry.path)
    assert not report["ok"]
    assert report["error"]


def test_verify_detects_manifest_sha_mismatch(sample_db: Path, backup_dir: Path) -> None:
    entry = backup.create_sqlite_snapshot(sample_db, backup_dir)
    manifest_path = Path(str(entry.path) + ".json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = backup.verify_sqlite_snapshot(entry.path)
    assert not report["ok"]
    assert any(check["name"] == "sha256" and not check["ok"] for check in report["checks"])


def test_retention_keeps_latest_n(sample_db: Path, backup_dir: Path) -> None:
    entries = [
        backup.create_sqlite_snapshot(sample_db, backup_dir, label=f"run{index}", keep=3, now=_stamp(index))
        for index in range(5)
    ]
    remaining = backup.list_backups(backup_dir, "sqlite")
    assert len(remaining) == 3
    assert [item.name for item in remaining] == [item.name for item in reversed(entries[-3:])]


def test_prune_respects_total_budget(sample_db: Path, backup_dir: Path) -> None:
    entries = [
        backup.create_sqlite_snapshot(sample_db, backup_dir, label=f"budget{index}", keep=10, now=_stamp(index))
        for index in range(3)
    ]
    budget = entries[-1].size_bytes + entries[-2].size_bytes
    deleted = backup.prune_backups(backup_dir, keep=10, max_total_bytes=budget)
    assert deleted == [entries[0].name]
    remaining = backup.list_backups(backup_dir, "sqlite")
    assert len(remaining) == 2


def test_restore_requires_force_and_creates_safety_snapshot(sample_db: Path, backup_dir: Path, tmp_path: Path) -> None:
    entry = backup.create_sqlite_snapshot(sample_db, backup_dir)
    target = tmp_path / "target.sqlite3"
    target.write_bytes(sample_db.read_bytes())

    with pytest.raises(backup.BackupError):
        backup.restore_sqlite_snapshot(entry.path, target)

    report = backup.restore_sqlite_snapshot(entry.path, target, force=True)
    assert report["ok"]
    assert report["safetySnapshot"].startswith("sqlite-")
    assert (tmp_path / "pre-restore" / "sqlite").is_dir()
    conn = sqlite3.connect(target)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    conn.close()


def test_restore_drill(sample_db: Path, backup_dir: Path) -> None:
    entry = backup.create_sqlite_snapshot(sample_db, backup_dir)
    report = backup.run_restore_drill(backup_dir, name=entry.name)
    assert report["ok"], report
    assert report["snapshot"] == entry.name
    assert report["tableCounts"] == {"repos": 3, "users": 2}
    assert any(check["name"] == "restore" and check["ok"] for check in report["checks"])


def test_status_summary(sample_db: Path, backup_dir: Path) -> None:
    entry = backup.create_sqlite_snapshot(sample_db, backup_dir)
    status = backup.backup_status(backup_dir, retention=7, max_total_mb=3072)
    assert status["counts"]["sqlite"] == 1
    assert status["counts"]["d1"] == 0
    assert status["latest"]["name"] == entry.name
    assert status["totalBytes"] == entry.size_bytes
    assert status["withinBudget"]


def test_verify_and_finalize_d1_dump(backup_dir: Path, tmp_path: Path) -> None:
    raw = tmp_path / "d1.sql"
    raw.write_text(
        """
        PRAGMA foreign_keys=OFF;
        BEGIN TRANSACTION;
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE repos (id INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO users (name) VALUES ('alice');
        INSERT INTO repos (name) VALUES ('alpha');
        COMMIT;
        """,
        encoding="utf-8",
    )
    report = backup.verify_d1_dump(raw, expected_tables=["users", "repos"])
    assert report["ok"], report
    assert report["tableCounts"] == {"repos": 1, "users": 1}

    missing = backup.verify_d1_dump(raw, expected_tables=["users", "missing_table"])
    assert not missing["ok"]

    entry = backup.finalize_d1_export(
        raw,
        backup_dir,
        label="nightly",
        expected_tables=["users", "repos"],
        database_name="openfactory",
    )
    assert entry.path.is_file()
    assert entry.path.name.endswith(".sql.gz")
    assert not raw.exists()
    archived = backup.verify_d1_dump(entry.path)
    assert archived["ok"], archived


def test_cli_status_and_create(sample_db: Path, backup_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert backup.main(["create", "--database", str(sample_db), "--backup-dir", str(backup_dir)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["name"].startswith("sqlite-")

    assert backup.main(["status", "--backup-dir", str(backup_dir), "--max-total-mb", "3072"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["counts"]["sqlite"] == 1

    assert backup.main(["verify", "--backup-dir", str(backup_dir)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"]


def test_api_requires_internal_token_and_handles_traversal(
    sample_db: Path, backup_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import backup as backup_api
    from app.main import app

    settings = get_settings()
    monkeypatch.setattr(settings, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{sample_db}")
    monkeypatch.setattr(settings, "INTERNAL_TOKEN", "test-internal-token")

    client = TestClient(app)
    assert client.get("/api/backup/status").status_code == 401

    headers = {"X-Internal-Token": "test-internal-token"}
    response = client.get("/api/backup/status", headers=headers)
    assert response.status_code == 200
    assert response.json()["counts"]["sqlite"] == 0

    response = client.post("/api/backup/sqlite", headers=headers, json={"label": "api"})
    assert response.status_code == 200, response.text
    name = response.json()["name"]

    response = client.post("/api/backup/sqlite/verify", headers=headers, json={"name": name})
    assert response.status_code == 200
    assert response.json()["ok"]

    response = client.post(
        "/api/backup/sqlite/verify",
        headers=headers,
        json={"name": "../etc/passwd"},
    )
    assert response.status_code == 400

    response = client.get("/api/backup/files?kind=sqlite", headers=headers)
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert backup_api is not None


def test_api_drill_and_d1_verify(sample_db: Path, backup_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app

    settings = get_settings()
    monkeypatch.setattr(settings, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{sample_db}")
    monkeypatch.setattr(settings, "INTERNAL_TOKEN", "")
    entry = backup.create_sqlite_snapshot(sample_db, backup_dir)
    client = TestClient(app)

    response = client.post("/api/backup/sqlite/drill", json={"name": entry.name})
    assert response.status_code == 200, response.text
    assert response.json()["ok"]

    raw = tmp_path / "d1.sql"
    raw.write_text("CREATE TABLE users (id INTEGER); INSERT INTO users VALUES (1);", encoding="utf-8")
    backup.finalize_d1_export(raw, backup_dir, expected_tables=["users"])
    response = client.post("/api/backup/d1/verify", json={})
    assert response.status_code == 200, response.text
    assert response.json()["ok"]


def test_gzip_fixture_is_readable(sample_db: Path, backup_dir: Path) -> None:
    entry = backup.create_sqlite_snapshot(sample_db, backup_dir)
    with gzip.open(entry.path, "rb") as handle:
        assert handle.read(16) == b"SQLite format 3\x00"
