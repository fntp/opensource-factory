"""Vectorize 索引同步服务测试（不访问网络）。

通过 monkeypatch `app.services.vector_index._edge_request` 模拟 edge Worker，
覆盖：批量 upsert、增量跳过、全量重传、失败重试、批次隔离、断点续跑、
维度校验、对账修复、孤儿清理与 HTTP 接口。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal, engine, init_db
from app.main import app
from app.models import VectorIndexRun, VectorIndexState
from app.services import vector_index
from app.services.vector_index import EdgeRequestError, sync_vectors, reconcile_vectors, vector_id


class FakeEdge:
    """可编程的 edge 内部接口替身。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.upsert_batches: list[list[dict]] = []
        self.deleted_batches: list[list[str]] = []
        self.fail_upsert_times = 0
        self.fail_upsert_calls: set[int] = set()
        self.fail_ids: set[str] = set()
        self.upsert_call_count = 0
        self.found_ids: set[str] | None = None
        self.stats_dimensions = 4

    def __call__(self, method: str, path: str, payload: dict | None = None):
        self.calls.append((method, path, payload))
        if path.endswith("/upsert"):
            self.upsert_call_count += 1
            items = list((payload or {}).get("items") or [])
            if self.upsert_call_count in self.fail_upsert_calls:
                raise EdgeRequestError("edge 503", status=503)
            if self.fail_upsert_times > 0:
                self.fail_upsert_times -= 1
                raise EdgeRequestError("edge 503", status=503)
            if any(item.get("id") in self.fail_ids for item in items):
                raise EdgeRequestError("edge 503", status=503)
            self.upsert_batches.append(items)
            return {"total": len(items), "upserted": len(items), "mutationId": "m-up"}
        if path.endswith("/check"):
            ids = list((payload or {}).get("ids") or [])
            found = ids if self.found_ids is None else [vid for vid in ids if vid in self.found_ids]
            return {"found": found, "missing": [vid for vid in ids if vid not in found]}
        if path.endswith("/delete"):
            ids = list((payload or {}).get("ids") or [])
            self.deleted_batches.append(ids)
            return {"total": len(ids), "deleted": len(ids), "mutationId": "m-del"}
        if path.endswith("/stats"):
            return {"vectorCount": 0, "dimensions": self.stats_dimensions}
        raise AssertionError(f"unexpected edge call: {method} {path}")


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    """每个用例使用干净的 repo_vectors / 同步状态，并注入可控配置。"""
    init_db()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS repo_vectors"))
        conn.execute(
            text(
                """
                CREATE TABLE repo_vectors (
                    source VARCHAR(16) NOT NULL,
                    repo_id VARCHAR(255) NOT NULL,
                    model VARCHAR(128) NOT NULL DEFAULT '',
                    backend VARCHAR(32) NOT NULL DEFAULT '',
                    dim INTEGER NOT NULL DEFAULT 0,
                    text_hash VARCHAR(64) NOT NULL DEFAULT '',
                    vector TEXT,
                    PRIMARY KEY (source, repo_id)
                )
                """
            )
        )
        conn.execute(text("DELETE FROM vector_index_state"))
        conn.execute(text("DELETE FROM vector_index_runs"))

    settings = get_settings()
    monkeypatch.setattr(settings, "EDGE_BASE_URL", "http://edge.test")
    monkeypatch.setattr(settings, "INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setattr(settings, "VECTORIZE_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "VECTORIZE_INDEX_DIM", 4)
    monkeypatch.setattr(settings, "VECTORIZE_SYNC_BATCH_SIZE", 100)
    monkeypatch.setattr(settings, "VECTORIZE_SYNC_MAX_PER_RUN", 1000)
    monkeypatch.setattr(settings, "VECTORIZE_SYNC_MAX_RETRIES", 3)
    monkeypatch.setattr(settings, "VECTORIZE_SYNC_RETRY_BASE_MS", 0)
    monkeypatch.setattr(settings, "VECTORIZE_SYNC_DELETE_ORPHANS", False)
    monkeypatch.setattr(settings, "VECTORIZE_SYNC_MAX_ORPHANS", 100)
    yield settings

    # 本模块用简化版 repo_vectors 表隔离 M3-02 依赖；用例结束后恢复完整模型表，
    # 避免后续模块（如 test_vector_pipeline）因缺列失败。
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS repo_vectors"))
    init_db()


def _insert_vector(
    source: str = "my",
    repo_id: str = "repo-1",
    *,
    vector: list[float] | None = None,
    dim: int = 4,
    text_hash: str = "hash-1",
    model: str = "bge-m3",
    backend: str = "local",
) -> str:
    values = vector if vector is not None else [0.1, 0.2, 0.3, 0.4]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO repo_vectors (source, repo_id, model, backend, dim, text_hash, vector)
                VALUES (:source, :repo_id, :model, :backend, :dim, :text_hash, :vector)
                """
            ),
            {
                "source": source,
                "repo_id": repo_id,
                "model": model,
                "backend": backend,
                "dim": dim,
                "text_hash": text_hash,
                "vector": json.dumps(values),
            },
        )
    return vector_id(source, repo_id)


def _state(source: str, repo_id: str) -> VectorIndexState | None:
    db = SessionLocal()
    try:
        return db.get(VectorIndexState, (source, repo_id))
    finally:
        db.close()


def test_sync_batch_upsert_and_incremental_skip(_isolated_db, monkeypatch):
    edge = FakeEdge()
    monkeypatch.setattr(vector_index, "_edge_request", edge)
    _insert_vector("my", "repo-1", text_hash="h1")
    _insert_vector("trending", "repo-2", text_hash="h2")

    first = sync_vectors(mode="incremental", scope="all")
    assert first["status"] == "completed"
    assert first["total"] == 2
    assert first["processed"] == 2
    assert first["upserted"] == 2
    assert first["failed"] == 0
    assert first["batches"] == 1
    assert len(edge.upsert_batches) == 1
    payload = edge.upsert_batches[0]
    assert {item["id"] for item in payload} == {
        vector_id("my", "repo-1"),
        vector_id("trending", "repo-2"),
    }
    assert payload[0]["metadata"]["source"] in ("my", "trending")
    assert payload[0]["metadata"]["text_hash"] in ("h1", "h2")

    second = sync_vectors(mode="incremental", scope="all")
    assert second["upserted"] == 0
    assert second["skipped"] == 2
    assert second["status"] == "completed"
    assert len(edge.upsert_batches) == 1  # 未产生新的 upsert


def test_full_mode_reuploads_even_if_unchanged(_isolated_db, monkeypatch):
    edge = FakeEdge()
    monkeypatch.setattr(vector_index, "_edge_request", edge)
    _insert_vector("my", "repo-1")

    assert sync_vectors(mode="incremental")["upserted"] == 1
    full = sync_vectors(mode="full")
    assert full["upserted"] == 1
    assert full["skipped"] == 0
    assert len(edge.upsert_batches) == 2


def test_retry_with_backoff_then_success(_isolated_db, monkeypatch):
    edge = FakeEdge()
    edge.fail_upsert_times = 2  # 前两次 503，第三次成功
    monkeypatch.setattr(vector_index, "_edge_request", edge)
    _insert_vector("my", "repo-1")

    result = sync_vectors()
    assert result["status"] == "completed"
    assert result["upserted"] == 1
    assert result["failed"] == 0
    assert edge.upsert_call_count == 3


def test_batch_failure_isolated_and_marked_for_retry(_isolated_db, monkeypatch):
    edge = FakeEdge()
    edge.fail_ids = {vector_id("my", "repo-1")}  # 仅含 repo-1 的批次持续失败
    monkeypatch.setattr(vector_index, "_edge_request", edge)
    _insert_vector("my", "repo-1")
    _insert_vector("my", "repo-2")

    result = sync_vectors(batch_size=1)
    assert result["status"] == "completed"
    assert result["processed"] == 2
    assert result["upserted"] == 1
    assert result["failed"] == 1
    assert "批次失败" in (result["error"] or "")

    states = {state.repo_id: state for state in _all_states()}
    assert states["repo-1"].status == "failed"
    assert states["repo-1"].attempts == 1
    assert states["repo-2"].status == "synced"


def test_resume_from_persisted_cursor(_isolated_db, monkeypatch):
    edge = FakeEdge()
    monkeypatch.setattr(vector_index, "_edge_request", edge)
    _insert_vector("my", "repo-1")
    _insert_vector("my", "repo-2")

    run_id = vector_index.create_run("incremental", "all")
    db = SessionLocal()
    try:
        run = db.get(VectorIndexRun, run_id)
        run.cursor_source = "my"
        run.cursor_repo_id = "repo-1"
        db.commit()
    finally:
        db.close()

    result = sync_vectors(run_id=run_id, mode="incremental")
    assert result["status"] == "completed"
    assert result["processed"] == 1
    assert len(edge.upsert_batches) == 1
    assert [item["id"] for item in edge.upsert_batches[0]] == [vector_id("my", "repo-2")]


def test_dimension_mismatch_is_skipped(_isolated_db, monkeypatch):
    edge = FakeEdge()
    monkeypatch.setattr(vector_index, "_edge_request", edge)
    monkeypatch.setattr(_isolated_db, "VECTORIZE_INDEX_DIM", 8)
    _insert_vector("my", "repo-1", dim=4)

    result = sync_vectors()
    assert result["dimSkipped"] == 1
    assert result["upserted"] == 0
    assert result["status"] == "completed"
    assert edge.upsert_batches == []
    assert _state("my", "repo-1").status == "failed"


def test_disabled_when_edge_not_configured(_isolated_db, monkeypatch):
    edge = FakeEdge()
    monkeypatch.setattr(vector_index, "_edge_request", edge)
    monkeypatch.setattr(_isolated_db, "EDGE_BASE_URL", "")

    result = sync_vectors()
    assert result["status"] == "disabled"
    assert "EDGE_BASE_URL" in (result["error"] or "")
    assert edge.calls == []


def test_reconcile_reports_missing_and_repairs(_isolated_db, monkeypatch):
    edge = FakeEdge()
    monkeypatch.setattr(vector_index, "_edge_request", edge)
    first_id = _insert_vector("my", "repo-1")
    _insert_vector("my", "repo-2")
    sync_vectors()

    edge.found_ids = {first_id}  # 第二条在索引中丢失
    result = reconcile_vectors(repair=True)
    assert result["status"] == "completed"
    assert result["checked"] == 2
    assert result["missing"] == 1
    assert result["repaired"] == 1
    assert len(edge.upsert_batches) == 2
    repaired_ids = [item["id"] for item in edge.upsert_batches[-1]]
    assert repaired_ids == [vector_id("my", "repo-2")]


def test_reconcile_reports_stale_and_repairs(_isolated_db, monkeypatch):
    edge = FakeEdge()
    monkeypatch.setattr(vector_index, "_edge_request", edge)
    _insert_vector("my", "repo-1", text_hash="old-hash")
    sync_vectors()

    # 本地向量已更新（hash 变化），但索引里仍是旧版本
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE repo_vectors SET text_hash = 'new-hash' WHERE source = 'my' AND repo_id = 'repo-1'")
        )
    result = reconcile_vectors(repair=True)
    assert result["checked"] == 1
    assert result["missing"] == 0
    assert result["stale"] == 1
    assert result["repaired"] == 1
    assert edge.upsert_batches[-1][0]["metadata"]["text_hash"] == "new-hash"


def test_reconcile_deletes_orphans_when_enabled(_isolated_db, monkeypatch):
    edge = FakeEdge()
    monkeypatch.setattr(vector_index, "_edge_request", edge)
    monkeypatch.setattr(_isolated_db, "VECTORIZE_SYNC_DELETE_ORPHANS", True)
    _insert_vector("my", "repo-1")
    sync_vectors()

    db = SessionLocal()
    try:
        db.add(
            VectorIndexState(
                source="my",
                repo_id="deleted-repo",
                vector_id=vector_id("my", "deleted-repo"),
                text_hash="old",
                status="synced",
            )
        )
        db.commit()
    finally:
        db.close()

    result = reconcile_vectors()
    assert result["deleted"] == 1
    assert edge.deleted_batches == [[vector_id("my", "deleted-repo")]]
    assert _state("my", "deleted-repo") is None


def test_api_sync_status_and_run_detail(_isolated_db, monkeypatch):
    edge = FakeEdge()
    monkeypatch.setattr(vector_index, "_edge_request", edge)
    _insert_vector("my", "repo-1")

    with TestClient(app) as client:
        enqueued = client.post(
            "/api/vector-index/sync",
            json={"mode": "incremental", "scope": "all"},
            headers={"X-Internal-Token": "test-internal-token"},
        )
        assert enqueued.status_code == 202
        body = enqueued.json()
        assert body["taskId"]
        assert body["runId"]

        auth = {"X-Internal-Token": "test-internal-token"}
        detail = client.get(f"/api/vector-index/runs/{body['runId']}", headers=auth)
        assert detail.status_code == 200
        assert detail.json()["status"] == "completed"
        assert detail.json()["upserted"] == 1

        status_resp = client.get("/api/vector-index/status", headers=auth)
        assert status_resp.status_code == 200
        assert status_resp.json()["repoVectors"] == 1
        assert status_resp.json()["lastRun"]["id"] == body["runId"]

        runs = client.get("/api/vector-index/runs", headers=auth)
        assert runs.status_code == 200
        assert len(runs.json()["items"]) >= 1


def _all_states() -> list[VectorIndexState]:
    db = SessionLocal()
    try:
        return list(db.query(VectorIndexState).all())
    finally:
        db.close()
