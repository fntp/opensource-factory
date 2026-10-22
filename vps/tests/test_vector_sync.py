"""Vectorize 索引同步测试（不访问网络）。

覆盖：稳定 ID、增量筛选、批量切分、失败重试、单批失败隔离、对账修复、
孤儿清理、维度不一致跳过与 API 入队。
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.db import SessionLocal, init_db
from app.main import app
from app.services import vector_sync as vs
from app.services.vector_sync import (
    EdgeVectorClient,
    VectorIndexError,
    VectorIndexUnsupported,
    sync_vector_index,
    vector_id_for,
)


def _settings(**overrides) -> Settings:
    values = {
        "VECTORIZE_SYNC_ENABLED": True,
        "EDGE_BASE_URL": "https://edge.test",
        "INTERNAL_TOKEN": "test-token",
        "VECTORIZE_INDEX_NAME": "test-index",
        "VECTORIZE_INDEX_DIM": 4,
        "VECTORIZE_SYNC_BATCH_SIZE": 100,
        "VECTORIZE_SYNC_MAX_PER_RUN": 1000,
        "VECTORIZE_SYNC_MAX_RETRIES": 0,
        "VECTORIZE_SYNC_RETRY_BASE_MS": 0,
        "VECTORIZE_SYNC_DELETE_ORPHANS": False,
        "VECTORIZE_SYNC_MAX_ORPHANS": 100,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture()
def db(monkeypatch):
    init_db()
    session = SessionLocal()
    session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS repo_vectors ("
            "source TEXT NOT NULL, repo_id TEXT NOT NULL, model TEXT NOT NULL, "
            "backend TEXT NOT NULL, dim INTEGER NOT NULL, text_hash TEXT NOT NULL, "
            "vector TEXT NOT NULL, created_at DATETIME, updated_at DATETIME, "
            "PRIMARY KEY (source, repo_id))"
        )
    )
    session.execute(text("DELETE FROM vector_sync_state"))
    session.execute(text("DELETE FROM vector_sync_runs"))
    session.execute(text("DELETE FROM repo_vectors"))
    session.commit()
    monkeypatch.setattr(vs, "get_settings", lambda: _settings())
    yield session
    session.close()


def _insert(
    db,
    source: str,
    repo_id: str,
    *,
    text_hash: str = "hash-1",
    dim: int = 4,
    values: list[float] | None = None,
) -> None:
    vector = values or [0.1] * dim
    db.execute(
        text(
            "INSERT OR REPLACE INTO repo_vectors "
            "(source, repo_id, model, backend, dim, text_hash, vector, created_at, updated_at) "
            "VALUES (:source, :repo_id, :model, :backend, :dim, :text_hash, :vector, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "source": source,
            "repo_id": repo_id,
            "model": "BAAI/bge-m3",
            "backend": "hash",
            "dim": dim,
            "text_hash": text_hash,
            "vector": json.dumps(vector),
        },
    )
    db.commit()


class FakeClient:
    """内存版 edge 客户端：可注入失败次数与远端已有向量。"""

    def __init__(self, *, fail_batches: int = 0, remote: dict[str, dict] | None = None):
        self.fail_batches = fail_batches
        self.remote = dict(remote or {})
        self.upsert_calls: list[list[dict]] = []
        self.deleted: list[str] = []

    def upsert(self, items: list[dict]) -> dict:
        self.upsert_calls.append(items)
        if self.fail_batches > 0:
            self.fail_batches -= 1
            raise VectorIndexError("mock upsert failure")
        for item in items:
            self.remote[item["id"]] = dict(item.get("metadata") or {})
        return {"ok": True}

    def check(self, ids: list[str]) -> dict[str, dict]:
        return {vector_id: self.remote[vector_id] for vector_id in ids if vector_id in self.remote}

    def delete(self, ids: list[str]) -> dict:
        for vector_id in ids:
            self.remote.pop(vector_id, None)
            self.deleted.append(vector_id)
        return {"ok": True}

    def list_ids(self) -> list[str]:
        return list(self.remote)


def test_vector_id_is_stable_and_short() -> None:
    first = vector_id_for("my", "owner/repo")
    assert first == vector_id_for("my", "owner/repo")
    assert first.startswith("v1_")
    assert len(first) <= 64
    assert first != vector_id_for("trending", "owner/repo")


def test_incremental_sync_only_upserts_changed(db, monkeypatch) -> None:
    _insert(db, "my", "a/one", text_hash="h1")
    _insert(db, "my", "a/two", text_hash="h2")
    _insert(db, "trending", "a/three", text_hash="h3")
    # 第一条已同步且哈希一致 → 增量应跳过
    db.execute(
        text(
            "INSERT INTO vector_sync_state "
            "(source, repo_id, vector_id, text_hash, model, backend, dim, status, attempts, "
            "created_at, updated_at) "
            "VALUES ('my', 'a/one', :vector_id, 'h1', 'BAAI/bge-m3', 'hash', 4, 'synced', 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"vector_id": vector_id_for("my", "a/one")},
    )
    db.commit()

    client = FakeClient()
    result = sync_vector_index(kind="sync", scope="all", client=client, db=db)

    assert result["status"] == "completed"
    assert result["total"] == 2
    assert result["synced"] == 2
    assert len(client.upsert_calls) == 1
    assert {item["id"] for item in client.upsert_calls[0]} == {
        vector_id_for("my", "a/two"),
        vector_id_for("trending", "a/three"),
    }

    # 第二次运行：没有变化 → 0 条
    second = sync_vector_index(kind="sync", scope="all", client=FakeClient(), db=db)
    assert second["total"] == 0
    assert second["synced"] == 0


def test_batch_size_splits_upserts(db) -> None:
    for index in range(5):
        _insert(db, "my", f"a/repo-{index}", text_hash=f"h{index}")
    client = FakeClient()
    result = sync_vector_index(
        kind="sync", scope="my", force=True, batch_size=2, client=client, db=db
    )
    assert result["synced"] == 5
    assert [len(batch) for batch in client.upsert_calls] == [2, 2, 1]


def test_edge_client_retries_transient_errors() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"ok": True})

    client = EdgeVectorClient(
        "https://edge.test",
        "token",
        max_retries=3,
        retry_base_ms=0,
        transport=httpx.MockTransport(handler),
    )
    assert client.upsert([{"id": "v1_x", "values": [1.0]}])["ok"] is True
    assert attempts["count"] == 3


def test_edge_client_does_not_retry_4xx() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(400, text="bad request")

    client = EdgeVectorClient(
        "https://edge.test",
        "token",
        max_retries=3,
        retry_base_ms=0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(VectorIndexError):
        client.upsert([{"id": "v1_x", "values": [1.0]}])
    assert attempts["count"] == 1


def test_batch_failure_marks_failed_and_retries_next_run(db) -> None:
    for index in range(4):
        _insert(db, "my", f"a/repo-{index}", text_hash=f"h{index}")

    client = FakeClient(fail_batches=1)
    first = sync_vector_index(
        kind="sync", scope="my", force=True, batch_size=2, client=client, db=db
    )
    assert first["status"] == "partial"
    assert first["synced"] == 2
    assert first["failed"] == 2

    failed_states = db.execute(
        text("SELECT COUNT(*) FROM vector_sync_state WHERE status = 'failed'")
    ).scalar_one()
    assert failed_states == 2

    # 下一次增量运行应自动重试失败项
    second = sync_vector_index(kind="sync", scope="my", client=FakeClient(), db=db)
    assert second["synced"] == 2
    assert second["status"] == "completed"


def test_reconcile_repairs_missing_and_stale(db) -> None:
    _insert(db, "my", "a/one", text_hash="h1")
    _insert(db, "my", "a/two", text_hash="h2")
    _insert(db, "my", "a/three", text_hash="h3")
    remote = {
        vector_id_for("my", "a/one"): {"text_hash": "h1"},
        vector_id_for("my", "a/two"): {"text_hash": "old"},
    }
    client = FakeClient(remote=remote)

    result = sync_vector_index(kind="reconcile", scope="my", client=client, db=db)

    assert result["checked"] == 3
    assert result["missing"] == 1
    assert result["repaired"] == 1
    assert result["synced"] == 2
    assert result["skipped"] == 1
    assert {item["id"] for batch in client.upsert_calls for item in batch} == {
        vector_id_for("my", "a/two"),
        vector_id_for("my", "a/three"),
    }


def test_reconcile_deletes_orphans_when_enabled(db, monkeypatch) -> None:
    _insert(db, "my", "a/one", text_hash="h1")
    monkeypatch.setattr(
        vs, "get_settings", lambda: _settings(VECTORIZE_SYNC_DELETE_ORPHANS=True)
    )
    orphan = "v1_" + "f" * 32
    client = FakeClient(
        remote={
            vector_id_for("my", "a/one"): {"text_hash": "h1"},
            orphan: {"text_hash": "dead"},
        }
    )

    result = sync_vector_index(kind="reconcile", scope="my", client=client, db=db)

    assert result["deleted"] == 1
    assert orphan in client.deleted
    assert result["orphanScan"] == "done"


def test_reconcile_marks_orphan_scan_unsupported(db, monkeypatch) -> None:
    _insert(db, "my", "a/one", text_hash="h1")
    monkeypatch.setattr(
        vs, "get_settings", lambda: _settings(VECTORIZE_SYNC_DELETE_ORPHANS=True)
    )

    class NoListClient(FakeClient):
        def list_ids(self) -> list[str]:
            raise VectorIndexUnsupported("not supported")

    client = NoListClient(remote={vector_id_for("my", "a/one"): {"text_hash": "h1"}})
    result = sync_vector_index(kind="reconcile", scope="my", client=client, db=db)
    assert result["orphanScan"] == "unsupported"


def test_dimension_mismatch_is_skipped(db) -> None:
    _insert(db, "my", "a/one", text_hash="h1", dim=256)
    client = FakeClient()
    result = sync_vector_index(kind="sync", scope="my", force=True, client=client, db=db)

    assert result["synced"] == 0
    assert result["skipped"] == 1
    assert client.upsert_calls == []
    status = db.execute(
        text("SELECT status FROM vector_sync_state WHERE source='my' AND repo_id='a/one'")
    ).scalar_one()
    assert status == "dim_mismatch"


def test_api_enqueues_sync_and_reports_status(db) -> None:
    _insert(db, "my", "a/one", text_hash="h1")
    with TestClient(app) as client:
        response = client.post(
            "/api/vector-index/sync",
            json={"kind": "sync", "scope": "my", "force": True},
        )
        assert response.status_code == 202
        assert response.json().get("taskId")

        status_response = client.get("/api/vector-index/status")
        assert status_response.status_code == 200
        body = status_response.json()
        assert body["localVectors"] == 1
        assert body["indexName"] == "test-index"

        runs_response = client.get("/api/vector-index/runs")
        assert runs_response.status_code == 200
        assert isinstance(runs_response.json(), list)
