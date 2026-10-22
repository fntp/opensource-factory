"""向量化管线测试：批量 / 增量 / force / limit / 断点续跑 / API。

全部使用 `EmbeddingService(force_fallback=True)` 或 conftest 中的
`EMBEDDING_FORCE_FALLBACK=1`，不加载真实模型、不访问网络。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository, RepoVector, TrendingRepository, VectorizationRun
from app.services.embedding import FALLBACK_DIM, EmbeddingService
from app.services.vector_pipeline import (
    VectorRunError,
    create_run,
    run_vectorization,
    vectorize,
)


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    session.execute(delete(RepoVector))
    session.execute(delete(VectorizationRun))
    session.execute(delete(MyRepository).where(MyRepository.id.like("vec-test/%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like("vec-test/%")))
    session.commit()
    yield session
    session.close()


def _seed_my(db, suffix: str, *, description: str = "一个用于测试的开源项目") -> MyRepository:
    row = MyRepository(
        id=f"vec-test/{suffix}",
        platform="github",
        name=f"repo-{suffix}",
        description=description,
        html_url=f"https://example.com/vec-test/{suffix}",
        stars=10,
        language="Python",
        readme_summary=f"摘要 {suffix}",
    )
    db.add(row)
    db.commit()
    return row


def _seed_trending(db, suffix: str) -> TrendingRepository:
    row = TrendingRepository(
        id=f"vec-test/{suffix}",
        platform="github",
        name=f"trend-{suffix}",
        html_url=f"https://example.com/vec-test/{suffix}",
        stars_today=100,
        description="热榜测试项目",
        tech_stack="Python, FastAPI",
    )
    db.add(row)
    db.commit()
    return row


def _service() -> EmbeddingService:
    return EmbeddingService(force_fallback=True)


def test_batch_vectorize_my_and_trending(db) -> None:
    _seed_my(db, "a")
    _seed_my(db, "b")
    _seed_trending(db, "c")

    result = vectorize(scope="all", limit=10, batch_size=2, service=_service())

    assert result["status"] == "completed"
    assert result["total"] == 3
    assert result["processed"] == 3
    assert result["vectorized"] == 3
    assert result["skipped"] == 0
    assert result["failed"] == 0

    rows = db.execute(select(RepoVector)).scalars().all()
    assert len(rows) == 3
    assert {row.source for row in rows} == {"my", "trending"}
    for row in rows:
        assert row.backend == "hash"
        assert row.dim == FALLBACK_DIM
        assert len(row.text_hash) == 64
        assert len(json.loads(row.vector)) == FALLBACK_DIM


def test_incremental_skips_unchanged_and_revectorizes_changed(db) -> None:
    _seed_my(db, "inc", description="初始描述")

    first = vectorize(scope="my", service=_service())
    assert first["vectorized"] == 1
    assert first["skipped"] == 0

    second = vectorize(scope="my", service=_service())
    assert second["vectorized"] == 0
    assert second["skipped"] == 1

    row = db.get(MyRepository, "vec-test/inc")
    assert row is not None
    row.description = "变更后的描述"
    db.commit()

    third = vectorize(scope="my", service=_service())
    assert third["vectorized"] == 1
    assert third["skipped"] == 0


def test_force_revectorizes_all(db) -> None:
    _seed_my(db, "force")
    vectorize(scope="my", service=_service())

    result = vectorize(scope="my", force=True, service=_service())
    assert result["vectorized"] == 1
    assert result["skipped"] == 0


def test_limit_caps_run_and_next_run_continues(db) -> None:
    _seed_my(db, "l1")
    _seed_my(db, "l2")
    _seed_my(db, "l3")

    first = vectorize(scope="my", limit=2, batch_size=2, service=_service())
    assert first["total"] == 2
    assert first["processed"] == 2
    assert first["vectorized"] == 2

    # 即使 limit=1，也应跳过前面已是最新的 l1/l2，继续处理 l3（不占预算）。
    second = vectorize(scope="my", limit=1, batch_size=2, service=_service())
    # limit 只限制待处理条数：已向量化的 2 条只计入 skipped，不占预算。
    assert second["total"] == 1
    assert second["processed"] == 1
    assert second["vectorized"] == 1
    assert second["skipped"] == 2


def test_resume_from_cursor_after_failure(db) -> None:
    _seed_my(db, "r1")
    _seed_my(db, "r2")
    _seed_my(db, "r3")

    session = SessionLocal()
    try:
        run = create_run(session, scope="my", limit=10, batch_size=1)
        run_id = run.id
    finally:
        session.close()

    def interrupt(meta: dict) -> None:
        if meta["processed"] >= 1:
            raise RuntimeError("模拟 worker 中断")

    with pytest.raises(RuntimeError):
        run_vectorization(run_id, service=_service(), progress=interrupt)

    session = SessionLocal()
    try:
        failed = session.get(VectorizationRun, run_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.processed == 1
        assert failed.cursor_repo_id == "vec-test/r1"
        assert "模拟 worker 中断" in (failed.error or "")
    finally:
        session.close()

    resumed = run_vectorization(run_id, service=_service())
    assert resumed["status"] == "completed"
    assert resumed["processed"] == 3
    assert resumed["vectorized"] == 3
    assert resumed["skipped"] == 0


def test_resume_rejects_model_change(db) -> None:
    _seed_my(db, "model")
    session = SessionLocal()
    try:
        run = create_run(session, scope="my", limit=10, batch_size=1)
        run_id = run.id
    finally:
        session.close()

    def interrupt(meta: dict) -> None:
        if meta["processed"] >= 1:
            raise RuntimeError("中断")

    with pytest.raises(RuntimeError):
        run_vectorization(run_id, service=_service(), progress=interrupt)

    other = EmbeddingService(model_name="other-model", force_fallback=True)
    with pytest.raises(VectorRunError, match="模型已变更"):
        run_vectorization(run_id, service=other)


def test_vectorize_api_and_stats(db) -> None:
    _seed_my(db, "api")

    with TestClient(app) as client:
        resp = client.post("/api/tasks/vectorize", params={"scope": "my", "batch_size": 4})
        assert resp.status_code == 202
        body = resp.json()
        assert body.get("taskId")
        assert body.get("runId")

        run_resp = client.get(f"/api/vectors/runs/{body['runId']}")
        assert run_resp.status_code == 200
        run_body = run_resp.json()
        assert run_body["status"] == "completed"
        assert run_body["processed"] == 1
        assert run_body["vectorized"] == 1

        stats_resp = client.get("/api/vectors/stats")
        assert stats_resp.status_code == 200
        stats = stats_resp.json()
        assert stats["totalVectors"] >= 1
        assert stats["repositories"]["my"]["vectorized"] >= 1
        assert any(item["runId"] == body["runId"] for item in stats["latestRuns"])

        detail = client.get("/api/vectors/my/vec-test/api")
        assert detail.status_code == 200
        detail_body = detail.json()
        assert detail_body["dim"] == FALLBACK_DIM
        assert len(detail_body["vector"]) == FALLBACK_DIM

        missing = client.get("/api/vectors/my/vec-test/not-found")
        assert missing.status_code == 404
        unknown_run = client.get("/api/vectors/runs/not-exist")
        assert unknown_run.status_code == 404
