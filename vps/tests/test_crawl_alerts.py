"""抓取告警 API 测试（TestClient，本地 SQLite，无网络）。"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.models import CrawlAlert


def _create_alert() -> str:
    init_db()
    alert_id = uuid4().hex
    db = SessionLocal()
    try:
        db.add(
            CrawlAlert(
                id=alert_id,
                platform="github",
                page="python",
                kind="structure_change",
                severity="error",
                message="页面 python 未找到任何候选行，疑似页面结构变更",
                details='{"rows": 0}',
                dedupe_key=f"github:python:structure_change:{alert_id}",
                status="open",
                occurrences=1,
            )
        )
        db.commit()
    finally:
        db.close()
    return alert_id


def test_alerts_list_and_acknowledge() -> None:
    alert_id = _create_alert()
    with TestClient(app) as client:
        listed = client.get("/api/trending/alerts", params={"status": "open", "limit": 200})
        assert listed.status_code == 200
        ids = [item["id"] for item in listed.json()]
        assert alert_id in ids

        acked = client.post(f"/api/trending/alerts/{alert_id}/ack")
        assert acked.status_code == 200
        body = acked.json()
        assert body["status"] == "acknowledged"
        assert body["acknowledged_at"]

        # 幂等：重复确认仍返回 200
        again = client.post(f"/api/trending/alerts/{alert_id}/ack")
        assert again.status_code == 200
        assert again.json()["status"] == "acknowledged"


def test_alerts_acknowledge_missing_returns_404() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/trending/alerts/not-exists/ack")
    assert resp.status_code == 404
