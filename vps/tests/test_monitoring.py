"""监控与告警（M5-03）：采集、阈值、告警去重 / 恢复、日志清理与 API。"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import MonitoringAlert, MonitoringCheckRun
from app.services import monitoring

PREFIX = "req0941:"
NOW = datetime(2026, 10, 22, 12, 0, 0)


def _settings(**overrides):
    values = {
        "MONITOR_HOME": "",
        "MONITOR_MEMORY_BUDGET_MB": 4096,
        "MONITOR_MEMORY_WARN_MB": 3584,
        "MONITOR_MEMORY_CRITICAL_MB": 4096,
        "MONITOR_DISK_BUDGET_MB": 15360,
        "MONITOR_DISK_WARN_MB": 13312,
        "MONITOR_DISK_CRITICAL_MB": 15360,
        "MONITOR_LOG_BUDGET_MB": 1024,
        "MONITOR_LOG_RETENTION_DAYS": 14,
        "MONITOR_HISTORY_RETENTION_DAYS": 30,
        "MONITOR_ALERT_COOLDOWN_MINUTES": 60,
        "MONITOR_ALERT_WEBHOOK_URL": "",
        "MONITOR_EDGE_TIMEOUT_SECONDS": 3.0,
        "MONITOR_REDIS_TIMEOUT_SECONDS": 2.0,
        "MONITOR_PROCESS_PATTERNS": "uvicorn+app.main:app,redis-server",
        "MONITOR_ENABLED": True,
        "LOG_DIR": "",
        "REDIS_URL": "",
        "EDGE_BASE_URL": "",
        "EMBEDDING_MODEL": "BAAI/bge-m3",
        "OLLAMA_MODEL": "qwen2.5:1.5b-instruct-q4_K_M",
        "EMBEDDING_QUANTIZATION": "int8",
        "MODEL_BUDGET_MB": 2048,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _cleanup() -> None:
    db = SessionLocal()
    try:
        db.execute(delete(MonitoringAlert).where(MonitoringAlert.dedupe_key.like(f"{PREFIX}%")))
        db.commit()
    finally:
        db.close()


def _resources(*, memory_mb: float = 100.0, disk_mb: float = 200.0, log_mb: float = 10.0) -> dict:
    return {
        "memory": {
            "usedMb": memory_mb,
            "budgetMb": 4096,
            "warnMb": 3584,
            "criticalMb": 4096,
            "percent": round(memory_mb / 4096 * 100, 1),
            "source": "process",
        },
        "disk": {
            "usedMb": disk_mb,
            "budgetMb": 15360,
            "warnMb": 13312,
            "criticalMb": 15360,
            "percent": round(disk_mb / 15360 * 100, 1),
            "path": "/opt/openfactory",
        },
        "load": {"one": 0.5, "five": 0.4, "fifteen": 0.3, "running": 2, "total": 8},
        "logs": {
            "path": "/opt/openfactory/logs",
            "exists": True,
            "files": 2,
            "totalMb": log_mb,
            "budgetMb": 1024,
            "retentionDays": 14,
            "oldFiles": 0,
            "items": [],
        },
        "collectedAt": NOW.isoformat(),
    }


def test_parse_meminfo_and_loadavg() -> None:
    meminfo = monitoring.parse_meminfo(
        "MemTotal:        4194304 kB\nMemFree:          512000 kB\nMemAvailable:    2097152 kB\n"
    )
    assert meminfo["MemTotal"] == 4194304
    assert meminfo["MemAvailable"] == 2097152

    load = monitoring.parse_loadavg("0.52 0.40 0.31 2/345 12345\n")
    assert load == {"one": 0.52, "five": 0.4, "fifteen": 0.31, "running": 2, "total": 345}
    assert monitoring.parse_loadavg("")["one"] == 0.0


def test_collect_process_memory_matches_all_keywords(tmp_path) -> None:
    proc = tmp_path / "proc"
    for pid, cmdline, rss_kb in (
        ("101", "uvicorn app.main:app --port 8000", 100 * 1024),
        ("102", "redis-server 127.0.0.1:6379", 50 * 1024),
        ("103", "python -m celery worker", 999 * 1024),
    ):
        pid_dir = proc / pid
        pid_dir.mkdir(parents=True)
        (pid_dir / "cmdline").write_bytes(cmdline.replace(" ", "\x00").encode() + b"\x00")
        (pid_dir / "status").write_text(f"Name:\ttest\nVmRSS:\t{rss_kb} kB\n", encoding="utf-8")

    result = monitoring.collect_process_memory(
        "uvicorn+app.main:app,redis-server", proc_root=proc
    )
    assert result["matchedPids"] == 2
    assert result["usedMb"] == 150.0
    assert [item["count"] for item in result["processes"]] == [1, 1]


def test_directory_size_and_log_cleanup(tmp_path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.log").write_bytes(b"x" * 1024)
    (tmp_path / "sub" / "b.log").write_bytes(b"y" * 2048)
    assert monitoring.directory_size_bytes(tmp_path) == 3072

    old = tmp_path / "old.log"
    new = tmp_path / "new.log"
    old.write_bytes(b"o" * 512)
    new.write_bytes(b"n" * 256)
    old_ts = (NOW - timedelta(days=30)).timestamp()
    new_ts = (NOW - timedelta(days=1)).timestamp()
    os.utime(old, (old_ts, old_ts))
    os.utime(new, (new_ts, new_ts))

    stats = monitoring.collect_log_stats(tmp_path, budget_mb=1, retention_days=14, now=NOW)
    assert stats["files"] == 4
    assert stats["oldFiles"] == 1

    dry = monitoring.cleanup_log_files(tmp_path, retention_days=14, now=NOW, dry_run=True)
    assert dry["deleted"] == 1 and old.exists()

    result = monitoring.cleanup_log_files(tmp_path, retention_days=14, now=NOW)
    assert result["deleted"] == 1
    assert result["kept"] == 3
    assert not old.exists() and new.exists()


def test_evaluate_findings_thresholds() -> None:
    warn = monitoring.evaluate_findings(
        _resources(memory_mb=3600), [], _settings()
    )
    assert [(item["kind"], item["severity"]) for item in warn] == [("memory", "warning")]

    critical = monitoring.evaluate_findings(
        _resources(memory_mb=4100, disk_mb=15400, log_mb=1100), [], _settings()
    )
    kinds = {item["kind"]: item["severity"] for item in critical}
    assert kinds == {"memory": "critical", "disk": "critical", "logs": "warning"}

    healthy = monitoring.evaluate_findings(_resources(), [], _settings())
    assert healthy == []


def test_record_alert_dedup_and_resolve() -> None:
    init_db()
    _cleanup()
    db = SessionLocal()
    try:
        finding = {
            "kind": "memory",
            "scope": "project",
            "severity": "warning",
            "message": "内存超过预警线",
            "details": {"usedMb": 3600},
            "dedupeKey": f"{PREFIX}memory",
        }
        first, created_first = monitoring.record_alert(db, finding, cooldown_minutes=60, now=NOW)
        db.commit()
        second, created_second = monitoring.record_alert(
            db, finding, cooldown_minutes=60, now=NOW + timedelta(minutes=5)
        )
        db.commit()

        assert created_first is True
        assert created_second is False
        assert first.id == second.id
        assert second.occurrences == 2

        resolved = monitoring.resolve_stale_alerts(db, [], now=NOW + timedelta(minutes=10))
        db.commit()
        assert resolved == 1
        assert db.get(MonitoringAlert, first.id).status == "resolved"
    finally:
        db.close()
        _cleanup()


def test_run_monitoring_check_persists_history(monkeypatch) -> None:
    init_db()
    _cleanup()
    monkeypatch.setattr(monitoring, "collect_resources", lambda cfg, home: _resources(memory_mb=3600))
    monkeypatch.setattr(
        monitoring,
        "run_health_checks",
        lambda db, cfg, home: [{"name": "database", "ok": True, "detail": "ok", "severity": "info"}],
    )

    db = SessionLocal()
    try:
        result = monitoring.run_monitoring_check(db, _settings(), now=NOW)
        assert result["status"] == "warning"
        assert result["alerts"]["created"] == 1
        run = db.get(MonitoringCheckRun, result["id"])
        assert run is not None
        assert run.status == "warning"
    finally:
        db.close()
        _cleanup()


def test_monitoring_api_status_check_and_ack(monkeypatch) -> None:
    init_db()
    _cleanup()
    monkeypatch.setattr(monitoring, "collect_resources", lambda cfg, home: _resources())
    monkeypatch.setattr(
        monitoring,
        "run_health_checks",
        lambda db, cfg, home: [{"name": "database", "ok": True, "detail": "ok", "severity": "info"}],
    )
    client = TestClient(app)

    status_response = client.get("/api/monitoring/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "ok"

    check_response = client.post("/api/monitoring/check")
    assert check_response.status_code == 200
    assert check_response.json()["run"]["id"]

    history_response = client.get("/api/monitoring/history", params={"limit": 5})
    assert history_response.status_code == 200
    assert history_response.json()["count"] >= 1

    db = SessionLocal()
    try:
        alert = MonitoringAlert(
            id="req0941-ack",
            kind="memory",
            severity="warning",
            message="test",
            details="{}",
            dedupe_key=f"{PREFIX}ack",
            status="open",
            occurrences=1,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        db.merge(alert)
        db.commit()
    finally:
        db.close()

    ack_response = client.post("/api/monitoring/alerts/req0941-ack/ack")
    assert ack_response.status_code == 200
    assert ack_response.json()["status"] == "acknowledged"
    assert client.post("/api/monitoring/alerts/missing/ack").status_code == 404

    _cleanup()


def test_internal_token_enforced(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.tasks.get_settings",
        lambda: SimpleNamespace(INTERNAL_TOKEN="secret-token"),
    )
    client = TestClient(app)
    assert client.get("/api/monitoring/status").status_code == 401
    assert (
        client.get(
            "/api/monitoring/status", headers={"X-Internal-Token": "secret-token"}
        ).status_code
        == 200
    )


def test_ready_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/healthz/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert {item["name"] for item in payload["checks"]} == {"database", "runtime_home"}
