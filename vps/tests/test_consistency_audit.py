"""数据一致性巡检：归一化 / 对账 / 数据源 / CLI 测试（不访问外网）。"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.services.consistency import (
    TABLE_SPECS,
    AuditInputError,
    audit_table,
    fetch_edge_table,
    load_json_snapshot,
    load_sqlite_table,
    normalize_value,
    render_markdown,
    render_summary_text,
    run_audit,
)
from scripts.consistency_audit import main


def _repo_row(**overrides):
    row = {
        "id": "owner/repo",
        "platform": "github",
        "name": "repo",
        "description": "desc",
        "html_url": "https://github.com/owner/repo",
        "stars": 10,
        "language": "Python",
        "readme_summary": "摘要",
        "category_id": "cat-1",
        "created_at": "2026-10-22 04:00:00",
    }
    row.update(overrides)
    return row


def _create_db(path: Path, rows: list[dict], table: str = "my_repositories") -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            f"""CREATE TABLE {table} (
                id TEXT PRIMARY KEY,
                platform TEXT,
                name TEXT,
                description TEXT,
                html_url TEXT,
                stars INTEGER,
                language TEXT,
                readme_summary TEXT,
                category_id TEXT,
                created_at TEXT
            )"""
        )
        for row in rows:
            columns = ", ".join(row)
            placeholders = ", ".join("?" for _ in row)
            conn.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", list(row.values())
            )
        conn.commit()
    finally:
        conn.close()


# ── 归一化 ──────────────────────────────────────────────────────


def test_normalize_value_handles_types() -> None:
    assert normalize_value(None, "text") == ""
    assert normalize_value("  abc  ", "text") == "abc"
    assert normalize_value("12", "int") == 12
    assert normalize_value(None, "int", 0) == 0
    assert normalize_value("0.1234567", "float") == 0.123457
    assert normalize_value(None, "float", 0.0) == 0.0


def test_normalize_datetime_formats() -> None:
    assert normalize_value("2026-10-22 04:00:00", "datetime") == "2026-10-22T04:00:00"
    assert normalize_value("2026-10-22T04:00:00Z", "datetime") == "2026-10-22T04:00:00"
    assert normalize_value("2026-10-22", "datetime") == "2026-10-22T00:00:00"
    assert normalize_value(datetime(2026, 10, 22, 4, 0, 0), "datetime") == "2026-10-22T04:00:00"
    assert normalize_value("not-a-date", "datetime") == "not-a-date"


# ── 对账核心 ────────────────────────────────────────────────────


def test_audit_table_uses_column_intersection() -> None:
    d1 = [_repo_row(owner="owner", forks=3, updated_at="2026-10-22 04:00:00")]
    local = [_repo_row()]
    report = audit_table(
        TABLE_SPECS["my_repositories"],
        d1,
        local,
        d1_columns=list(d1[0]),
        local_columns=list(local[0]),
    )
    assert report["status"] == "consistent"
    assert report["mismatchCount"] == 0
    skipped = {item["field"]: item["reason"] for item in report["skippedFields"]}
    assert skipped["owner"] == "local_column_missing"
    assert "id" in report["comparedFields"]


def test_audit_table_detects_missing_and_mismatch() -> None:
    d1 = [_repo_row(id="a"), _repo_row(id="b", stars=20)]
    local = [_repo_row(id="b", stars=21), _repo_row(id="c")]
    report = audit_table(
        TABLE_SPECS["my_repositories"],
        d1,
        local,
        d1_columns=list(d1[0]),
        local_columns=list(local[0]),
    )
    assert report["missingInLocal"] == ["a"]
    assert report["missingInD1"] == ["c"]
    assert report["mismatchCount"] == 1
    assert report["mismatches"][0]["field"] == "stars"
    assert report["mismatchFields"] == {"stars": 1}
    assert report["status"] == "differences"


def test_audit_table_detects_duplicate_keys() -> None:
    d1 = [_repo_row(id="a", stars=1), _repo_row(id="a", stars=2)]
    local = [_repo_row(id="a", stars=1)]
    report = audit_table(
        TABLE_SPECS["my_repositories"],
        d1,
        local,
        d1_columns=list(d1[0]),
        local_columns=list(local[0]),
    )
    assert report["duplicateKeyCount"] == 1
    assert report["duplicateKeys"] == ["a"]
    assert report["status"] == "differences"


def test_audit_table_ignores_requested_fields() -> None:
    d1 = [_repo_row(synced_at="2026-10-22 04:00:00")]
    local = [_repo_row(synced_at="2026-10-21 04:00:00")]
    report = audit_table(
        TABLE_SPECS["my_repositories"],
        d1,
        local,
        d1_columns=list(d1[0]),
        local_columns=list(local[0]),
        ignore_fields=["my_repositories.synced_at"],
    )
    assert report["status"] == "consistent"
    assert {"field": "synced_at", "reason": "ignored"} in report["skippedFields"]


def test_users_login_maps_to_local_username() -> None:
    d1 = [{"id": "1", "login": "alice", "created_at": "2026-10-22 04:00:00"}]
    local = [{"id": "1", "username": "alice", "created_at": "2026-10-22 04:00:00"}]
    report = audit_table(
        TABLE_SPECS["users"],
        d1,
        local,
        d1_columns=list(d1[0]),
        local_columns=list(local[0]),
    )
    assert report["status"] == "consistent"
    assert report["comparedFields"] == ["id", "login", "created_at"]


def test_run_audit_summary_and_render() -> None:
    d1 = {"my_repositories": [_repo_row(id="a")]}
    local = {"my_repositories": [_repo_row(id="a")]}
    report = run_audit(
        d1,
        local,
        tables=["my_repositories"],
        d1_columns={"my_repositories": list(d1["my_repositories"][0])},
        local_columns={"my_repositories": list(local["my_repositories"][0])},
        source="test",
        local_db="local.db",
    )
    assert report["status"] == "consistent"
    assert report["summary"]["consistent"] == 1
    text = render_summary_text(report)
    assert "未发现差异" in text
    markdown = render_markdown(report)
    assert "# 数据一致性巡检报告" in markdown
    assert "未发现差异" in markdown


# ── 数据源 ──────────────────────────────────────────────────────


def test_load_sqlite_table_reads_columns_and_rows(tmp_path: Path) -> None:
    db = tmp_path / "local.db"
    _create_db(db, [_repo_row(id="a"), _repo_row(id="b")])
    columns, rows = load_sqlite_table(db, "my_repositories")
    assert "stars" in columns
    assert [row["id"] for row in rows] == ["a", "b"]


def test_load_sqlite_table_rejects_missing_table(tmp_path: Path) -> None:
    db = tmp_path / "local.db"
    sqlite3.connect(db).close()
    with pytest.raises(AuditInputError, match="表不存在"):
        load_sqlite_table(db, "my_repositories")


def test_load_json_snapshot_formats(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.json"
    bundle.write_text(
        json.dumps(
            {
                "tables": {"my_repositories": [_repo_row(id="a")]},
                "columns": {"my_repositories": ["id", "stars"]},
            }
        ),
        encoding="utf-8",
    )
    columns, rows = load_json_snapshot(bundle, "my_repositories")
    assert columns == ["id", "stars"]
    assert rows[0]["id"] == "a"

    single = tmp_path / "single.json"
    single.write_text(
        json.dumps({"table": "my_repositories", "rows": [_repo_row(id="b")]}),
        encoding="utf-8",
    )
    columns, rows = load_json_snapshot(single, "my_repositories")
    assert "stars" in columns
    assert rows[0]["id"] == "b"

    wrangler = tmp_path / "wrangler.json"
    wrangler.write_text(
        json.dumps([{"results": [_repo_row(id="c")], "success": True}]),
        encoding="utf-8",
    )
    _, rows = load_json_snapshot(wrangler, "my_repositories")
    assert rows[0]["id"] == "c"


def test_fetch_edge_table_paginates_and_sends_token() -> None:
    rows = [{"id": f"r{i}"} for i in range(3)]
    seen_tokens: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = parse_qs(urlparse(self.path).query)
            seen_tokens.append(self.headers.get("X-Internal-Token"))
            offset = int(query.get("offset", ["0"])[0])
            limit = int(query.get("limit", ["2"])[0])
            page = rows[offset : offset + limit]
            payload = {
                "table": "my_repositories",
                "columns": ["id"],
                "rows": page,
                "offset": offset,
                "limit": limit,
                "total": len(rows),
                "hasMore": offset + len(page) < len(rows),
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # noqa: D401 - 静默测试日志
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        columns, fetched = fetch_edge_table(
            f"http://127.0.0.1:{server.server_port}",
            "my_repositories",
            "secret-token",
            page_size=2,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert columns == ["id"]
    assert [row["id"] for row in fetched] == ["r0", "r1", "r2"]
    assert seen_tokens == ["secret-token", "secret-token"]


def test_fetch_edge_table_requires_token() -> None:
    with pytest.raises(AuditInputError, match="必须提供"):
        fetch_edge_table("http://127.0.0.1:1", "my_repositories", "")


# ── CLI 端到端 ──────────────────────────────────────────────────


def test_cli_reports_differences_and_writes_reports(tmp_path: Path) -> None:
    local_db = tmp_path / "local.db"
    d1_db = tmp_path / "d1.db"
    _create_db(local_db, [_repo_row(id="a", stars=10), _repo_row(id="b", stars=20)])
    _create_db(d1_db, [_repo_row(id="a", stars=10), _repo_row(id="c", stars=30)])
    report_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"

    exit_code = main(
        [
            "--d1-db",
            str(d1_db),
            "--local-db",
            str(local_db),
            "--tables",
            "my_repositories",
            "--report",
            str(report_path),
            "--json-out",
            str(json_path),
            "--quiet",
        ]
    )

    assert exit_code == 1
    assert "本机缺失" in report_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["status"] == "differences"
    assert payload["summary"]["missingInLocal"] == 1
    assert payload["summary"]["missingInD1"] == 1


def test_cli_returns_zero_when_consistent(tmp_path: Path) -> None:
    local_db = tmp_path / "local.db"
    d1_db = tmp_path / "d1.db"
    rows = [_repo_row(id="a", stars=10)]
    _create_db(local_db, rows)
    _create_db(d1_db, rows)
    assert (
        main(
            [
                "--d1-db",
                str(d1_db),
                "--local-db",
                str(local_db),
                "--tables",
                "my_repositories",
                "--quiet",
            ]
        )
        == 0
    )


def test_cli_returns_two_for_missing_local_db(tmp_path: Path) -> None:
    d1_db = tmp_path / "d1.db"
    _create_db(d1_db, [_repo_row(id="a")])
    assert (
        main(
            [
                "--d1-db",
                str(d1_db),
                "--local-db",
                str(tmp_path / "missing.db"),
                "--tables",
                "my_repositories",
                "--quiet",
            ]
        )
        == 2
    )
