"""语义搜索测试（不访问网络，使用确定性 hash 向量）。

覆盖：查询归一化 / scope 校验 / 余弦排序 / 维度不一致跳过 / minScore 过滤 /
本地检索与 scope 过滤 / 结果水合 / 状态统计 / 内部 API 与鉴权。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import Settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository, RepoVector, TrendingRepository, VectorizationRun
from app.services.embedding import FALLBACK_DIM, EmbeddingService
from app.services.semantic_search import (
    SearchError,
    SearchHit,
    get_status,
    hydrate_hits,
    normalize_query,
    normalize_scope,
    search_local,
    search_semantic,
    search_vectors,
)
from app.services.vector_pipeline import build_repo_text


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    session.execute(delete(RepoVector))
    session.execute(delete(VectorizationRun))
    session.execute(delete(MyRepository).where(MyRepository.id.like("search-test/%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like("search-test/%")))
    session.commit()
    yield session
    session.close()


def _seed(db) -> dict[str, str]:
    my_admin = MyRepository(
        id="search-test/tenant-admin",
        platform="github",
        name="tenant-admin",
        description="支持多租户的 NestJS 管理后台模板",
        html_url="https://example.com/search-test/tenant-admin",
        stars=120,
        language="TypeScript",
        readme_summary="多租户 SaaS 后台脚手架",
    )
    my_tool = MyRepository(
        id="search-test/python-tool",
        platform="github",
        name="python-tool",
        description="Python 命令行小工具",
        html_url="https://example.com/search-test/python-tool",
        stars=8,
        language="Python",
    )
    trend_ui = TrendingRepository(
        id="search-test/trend-ui",
        platform="github",
        name="trend-ui",
        description="现代 React 组件库",
        html_url="https://example.com/search-test/trend-ui",
        stars_today=88,
        tech_stack="React, TypeScript",
    )
    db.add_all([my_admin, my_tool, trend_ui])
    db.commit()

    service = EmbeddingService(force_fallback=True)
    for source, row in (("my", my_admin), ("my", my_tool), ("trending", trend_ui)):
        text = build_repo_text(source, row)
        vector = service.encode_one(text)
        db.add(
            RepoVector(
                source=source,
                repo_id=row.id,
                model=service.model_name,
                backend=service.backend,
                dim=len(vector),
                text_hash=f"hash-{row.id}",
                vector=json.dumps(vector),
            )
        )
    db.commit()
    return {
        "my_admin": my_admin.id,
        "my_tool": my_tool.id,
        "trend_ui": trend_ui.id,
    }


def test_normalize_scope_and_query() -> None:
    assert normalize_scope(" ALL ") == "all"
    assert normalize_scope("my") == "my"
    with pytest.raises(SearchError):
        normalize_scope("unknown")
    assert normalize_query("  多租户   NestJS  ") == "多租户 NestJS"
    with pytest.raises(SearchError):
        normalize_query("   ")


def test_search_vectors_orders_and_skips_dim_mismatch() -> None:
    rows = [
        RepoVector(source="my", repo_id="a/close", model="m", backend="hash", dim=3,
                   text_hash="h1", vector=json.dumps([1.0, 0.0, 0.0])),
        RepoVector(source="my", repo_id="a/far", model="m", backend="hash", dim=3,
                   text_hash="h2", vector=json.dumps([0.0, 1.0, 0.0])),
        RepoVector(source="my", repo_id="a/bad", model="m", backend="hash", dim=2,
                   text_hash="h3", vector=json.dumps([1.0, 0.0])),
        RepoVector(source="my", repo_id="a/invalid", model="m", backend="hash", dim=3,
                   text_hash="h4", vector="not-json"),
    ]
    hits = search_vectors([1.0, 0.0, 0.0], rows, top_k=10)
    assert [hit.repo_id for hit in hits] == ["a/close", "a/far"]
    assert hits[0].score == pytest.approx(1.0)
    assert search_vectors([1.0, 0.0, 0.0], rows, top_k=1, min_score=0.5) == [
        SearchHit(source="my", repo_id="a/close", score=1.0)
    ]


def test_search_local_ranks_and_respects_scope(db) -> None:
    ids = _seed(db)

    result = search_local(db, "多租户 NestJS 管理后台", top_k=5, scope="all")
    assert result["count"] >= 1
    assert result["items"][0]["source"] == "my"
    assert result["items"][0]["repoId"] == ids["my_admin"]
    assert result["dim"] == FALLBACK_DIM
    assert result["backend"] == "hash"

    my_only = search_local(db, "React 组件库", scope="my")
    assert all(item["source"] == "my" for item in my_only["items"])
    trending_only = search_local(db, "React 组件库", scope="trending")
    assert [item["source"] for item in trending_only["items"]] == ["trending"]
    assert trending_only["items"][0]["repoId"] == ids["trend_ui"]


def test_search_local_min_score_filters_everything(db) -> None:
    _seed(db)
    result = search_local(db, "多租户 NestJS 管理后台", min_score=0.99)
    assert result["count"] == 0
    assert result["items"] == []


def test_hydrate_and_semantic_search_return_repo_details(db) -> None:
    ids = _seed(db)
    result = search_semantic(db, "多租户 NestJS 管理后台", top_k=3)
    assert result["count"] == len(result["items"])
    first = result["items"][0]
    assert first["id"] == ids["my_admin"]
    assert first["fullName"] == ids["my_admin"]
    assert first["url"].startswith("https://example.com/")
    assert "相似度" in first["reason"]

    # 不存在的仓库行被水合时跳过
    assert hydrate_hits(db, [SearchHit(source="my", repo_id="missing/repo", score=0.5)]) == []


def test_get_status_reports_distribution(db) -> None:
    _seed(db)
    status = get_status(db)
    assert status["totalVectors"] == 3
    assert status["bySource"] == {"my": 2, "trending": 1}
    assert status["dimensions"] == [FALLBACK_DIM]
    assert status["byModel"][0]["backend"] == "hash"
    assert status["latestRuns"] == []


def test_search_api_endpoints(db) -> None:
    _seed(db)
    with TestClient(app) as client:
        embed = client.post("/api/search/embed", json={"query": "多租户后台"})
        assert embed.status_code == 200
        body = embed.json()
        assert body["dim"] == len(body["vector"]) == FALLBACK_DIM

        query = client.post("/api/search/query", json={"query": "多租户后台", "topK": 2})
        assert query.status_code == 200
        assert query.json()["count"] <= 2

        semantic = client.post("/api/search/semantic", json={"query": "多租户后台"})
        assert semantic.status_code == 200
        assert semantic.json()["items"][0]["fullName"] == "search-test/tenant-admin"

        status_response = client.get("/api/search/status")
        assert status_response.status_code == 200
        assert status_response.json()["totalVectors"] == 3

        invalid = client.post("/api/search/query", json={"query": "  "})
        assert invalid.status_code == 400  # 去空白后为空 → SearchError

        bad_scope = client.post(
            "/api/search/query", json={"query": "x", "scope": "unknown"}
        )
        assert bad_scope.status_code == 422


def test_search_local_returns_query_understanding(db) -> None:
    _seed(db)
    result = search_local(db, "k8s 组件库", top_k=5)
    understanding = result["understanding"]
    assert understanding["expanded"] is True
    assert "Kubernetes" in understanding["techStack"]
    assert "组件库" in understanding["concepts"]
    assert understanding["rewritten"].startswith("k8s 组件库")
    assert "Kubernetes" in understanding["rewritten"]


def test_search_local_can_disable_expansion(db) -> None:
    _seed(db)
    result = search_local(db, "k8s 组件库", expand=False)
    assert result["understanding"]["expanded"] is False
    assert result["understanding"]["rewritten"] == "k8s 组件库"


def test_search_api_understand_and_expansion_flags(db) -> None:
    _seed(db)
    with TestClient(app) as client:
        understood = client.post("/api/search/understand", json={"query": "k8s 部署"})
        assert understood.status_code == 200
        body = understood.json()
        assert body["expanded"] is True
        assert "Kubernetes" in body["techStack"]
        assert body["rewritten"].startswith("k8s 部署")

        embed = client.post("/api/search/embed", json={"query": "k8s 部署"})
        assert embed.status_code == 200
        assert embed.json()["understanding"]["expanded"] is True
        assert "Kubernetes" in embed.json()["understanding"]["techStack"]

        disabled = client.post(
            "/api/search/embed", json={"query": "k8s 部署", "expand": False}
        )
        assert disabled.status_code == 200
        assert disabled.json()["understanding"]["expanded"] is False
        assert disabled.json()["understanding"]["rewritten"] == "k8s 部署"

        semantic = client.post("/api/search/semantic", json={"query": "k8s 部署"})
        assert semantic.status_code == 200
        assert semantic.json()["understanding"]["expanded"] is True

        empty = client.post("/api/search/understand", json={"query": "  "})
        assert empty.status_code == 400  # 去空白后为空 → QueryUnderstandingError


def test_search_status_reports_vocabulary(db) -> None:
    _seed(db)
    status = get_status(db)
    assert status["vocabulary"]["techEntries"] >= 60
    assert status["vocabulary"]["conceptEntries"] >= 50


def test_search_api_requires_internal_token_when_configured(db, monkeypatch) -> None:
    import app.api.tasks as tasks_module

    monkeypatch.setattr(
        tasks_module,
        "get_settings",
        lambda: Settings(INTERNAL_TOKEN="test-secret"),
    )
    with TestClient(app) as client:
        denied = client.post("/api/search/embed", json={"query": "x"})
        assert denied.status_code == 401

        allowed = client.post(
            "/api/search/embed",
            json={"query": "x"},
            headers={"X-Internal-Token": "test-secret"},
        )
        assert allowed.status_code == 200
