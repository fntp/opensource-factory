"""相似项目推荐测试（M6-02，不访问网络，使用确定性 hash 向量）。

覆盖：种子缺失 / 未向量化、排除自身、scope 过滤、excludeSaved、模型 / 维度过滤、
minScore / topK、水合理由、内部 API 与鉴权。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository, RepoVector, TrendingRepository
from app.services.embedding import EmbeddingService
from app.services.similar_recommendations import (
    SeedNotFound,
    SeedVectorMissing,
    SimilarError,
    find_similar,
    normalize_source,
    similar_repositories,
)
from app.services.vector_pipeline import build_repo_text


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    session.execute(delete(RepoVector).where(RepoVector.repo_id.like("similar-test/%")))
    session.execute(delete(MyRepository).where(MyRepository.id.like("similar-test/%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like("similar-test/%")))
    session.commit()
    yield session
    session.rollback()
    session.execute(delete(RepoVector).where(RepoVector.repo_id.like("similar-test/%")))
    session.execute(delete(MyRepository).where(MyRepository.id.like("similar-test/%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like("similar-test/%")))
    session.commit()
    session.close()


def _add_vector(db, source: str, repo_id: str, vector: list[float], *, model: str = "m", backend: str = "hash") -> None:
    db.add(
        RepoVector(
            source=source,
            repo_id=repo_id,
            model=model,
            backend=backend,
            dim=len(vector),
            text_hash=f"hash-{repo_id}",
            vector=json.dumps(vector),
        )
    )


def _seed_manual(db) -> None:
    """手工向量：x 轴为 TypeScript 方向，y 轴为 Python 方向。"""
    db.add_all(
        [
            MyRepository(
                id="similar-test/seed",
                platform="github",
                name="seed",
                description="TypeScript 管理后台",
                html_url="https://example.com/similar-test/seed",
                stars=100,
                language="TypeScript",
            ),
            MyRepository(
                id="similar-test/saved",
                platform="github",
                name="saved",
                description="另一个 TypeScript 后台",
                html_url="https://example.com/similar-test/saved",
                stars=50,
                language="TypeScript",
            ),
            TrendingRepository(
                id="similar-test/trend",
                platform="github",
                name="trend",
                description="React 管理界面",
                html_url="https://example.com/similar-test/trend",
                stars_today=30,
                tech_stack="React, TypeScript",
            ),
            TrendingRepository(
                id="similar-test/other",
                platform="github",
                name="other",
                description="Python 命令行工具",
                html_url="https://example.com/similar-test/other",
                stars_today=10,
                tech_stack="Python",
            ),
            TrendingRepository(
                id="similar-test/model-mismatch",
                platform="github",
                name="model-mismatch",
                description="同维度但不同模型",
                html_url="https://example.com/similar-test/model-mismatch",
                stars_today=5,
                tech_stack="TypeScript",
            ),
            TrendingRepository(
                id="similar-test/trend-no-vector",
                platform="github",
                name="trend-no-vector",
                description="尚未向量化",
                html_url="https://example.com/similar-test/trend-no-vector",
                stars_today=1,
                tech_stack="TypeScript",
            ),
        ]
    )
    _add_vector(db, "my", "similar-test/seed", [1.0, 0.0, 0.0])
    _add_vector(db, "my", "similar-test/saved", [0.9, 0.1, 0.0])
    _add_vector(db, "trending", "similar-test/trend", [0.8, 0.2, 0.0])
    _add_vector(db, "trending", "similar-test/other", [0.0, 1.0, 0.0])
    # 同维度但不同模型：不得参与比较
    _add_vector(
        db,
        "trending",
        "similar-test/model-mismatch",
        [1.0, 0.0, 0.0],
        model="other-model",
    )
    db.commit()


def _seed_hash(db) -> dict[str, str]:
    """使用真实 hash 编码，验证与生产一致的向量空间。"""
    service = EmbeddingService(force_fallback=True)
    rows = [
        (
            "my",
            MyRepository(
                id="similar-test/hash-seed",
                platform="github",
                name="hash-seed",
                description="多租户 NestJS 管理后台",
                html_url="https://example.com/similar-test/hash-seed",
                stars=120,
                language="TypeScript",
                readme_summary="多租户 SaaS 后台脚手架",
            ),
        ),
        (
            "my",
            MyRepository(
                id="similar-test/hash-similar",
                platform="github",
                name="hash-similar",
                description="NestJS 多租户后台模板",
                html_url="https://example.com/similar-test/hash-similar",
                stars=80,
                language="TypeScript",
                readme_summary="多租户 SaaS 管理后台",
            ),
        ),
        (
            "trending",
            TrendingRepository(
                id="similar-test/hash-trend",
                platform="github",
                name="hash-trend",
                description="React 组件库",
                html_url="https://example.com/similar-test/hash-trend",
                stars_today=88,
                tech_stack="React, TypeScript",
            ),
        ),
    ]
    for source, row in rows:
        db.add(row)
    db.commit()
    for source, row in rows:
        vector = service.encode_one(build_repo_text(source, row))
        _add_vector(
            db,
            source,
            row.id,
            vector,
            model=service.model_name,
            backend=service.backend,
        )
    db.commit()
    return {
        "seed": "similar-test/hash-seed",
        "similar": "similar-test/hash-similar",
        "trend": "similar-test/hash-trend",
    }


def test_normalize_source() -> None:
    assert normalize_source(" MY ") == "my"
    assert normalize_source("trending") == "trending"
    with pytest.raises(SimilarError):
        normalize_source("all")


def test_find_similar_ranks_and_excludes_seed(db) -> None:
    _seed_manual(db)
    result = find_similar(db, "my", "similar-test/seed", top_k=10, scope="all")
    ids = [item["repoId"] for item in result["items"]]
    assert "similar-test/seed" not in ids
    assert ids[0] == "similar-test/saved"
    assert ids == ["similar-test/saved", "similar-test/trend", "similar-test/other"]
    scores = [item["score"] for item in result["items"]]
    assert scores == sorted(scores, reverse=True)
    assert result["seed"]["name"] == "seed"
    assert result["model"] == "m"
    assert result["dim"] == 3
    assert result["count"] == 3


def test_find_similar_scope_and_exclude_saved(db) -> None:
    _seed_manual(db)
    trending_only = find_similar(db, "my", "similar-test/seed", scope="trending")
    assert all(item["source"] == "trending" for item in trending_only["items"])

    my_only = find_similar(db, "my", "similar-test/seed", scope="my")
    assert [item["repoId"] for item in my_only["items"]] == ["similar-test/saved"]

    excluded = find_similar(db, "my", "similar-test/seed", scope="all", exclude_saved=True)
    assert all(item["source"] != "my" for item in excluded["items"])
    assert excluded["excludeSaved"] is True


def test_find_similar_skips_model_mismatch_and_min_score(db) -> None:
    _seed_manual(db)
    result = find_similar(db, "my", "similar-test/seed", min_score=0.5)
    assert [item["repoId"] for item in result["items"]] == [
        "similar-test/saved",
        "similar-test/trend",
    ]

    none = find_similar(db, "my", "similar-test/seed", min_score=0.999)
    assert none["count"] == 0


def test_find_similar_seed_errors(db) -> None:
    _seed_manual(db)
    with pytest.raises(SeedNotFound):
        find_similar(db, "my", "similar-test/missing")
    with pytest.raises(SeedNotFound):
        find_similar(db, "trending", "similar-test/seed")  # 该 id 只在 my 中

    db.add(
        MyRepository(
            id="similar-test/no-vector",
            platform="github",
            name="no-vector",
            html_url="https://example.com/similar-test/no-vector",
        )
    )
    db.commit()
    with pytest.raises(SeedVectorMissing):
        find_similar(db, "my", "similar-test/no-vector")
    with pytest.raises(SeedVectorMissing):
        find_similar(db, "trending", "similar-test/trend-no-vector")


def test_similar_repositories_hydrates_with_seed_reason(db) -> None:
    _seed_hash(db)
    result = similar_repositories(db, "my", "similar-test/hash-seed", top_k=3)
    assert result["count"] >= 1
    first = result["items"][0]
    assert first["id"] == "similar-test/hash-similar"
    assert "hash-seed" in first["reason"]
    assert "相似度" in first["reason"]
    assert first["url"].startswith("https://example.com/")


def test_similar_api(db) -> None:
    _seed_manual(db)
    with TestClient(app) as client:
        ok = client.post(
            "/api/search/similar",
            json={"source": "my", "repoId": "similar-test/seed", "topK": 2},
        )
        assert ok.status_code == 200
        body = ok.json()
        assert body["count"] == 2
        assert body["seed"]["name"] == "seed"
        assert body["items"][0]["repoId"] == "similar-test/saved"

        missing = client.post(
            "/api/search/similar",
            json={"source": "my", "repoId": "similar-test/missing"},
        )
        assert missing.status_code == 404

        no_vector = client.post(
            "/api/search/similar",
            json={"source": "trending", "repoId": "similar-test/trend-no-vector"},
        )
        assert no_vector.status_code == 409

        bad_source = client.post(
            "/api/search/similar",
            json={"source": "all", "repoId": "similar-test/seed"},
        )
        assert bad_source.status_code == 422
