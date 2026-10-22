"""重复 / 相似项目检测测试（M6-03，不访问网络）。

覆盖：地址归一化、名称 / 中文 token 相似、exact / name / semantic 聚类、
跨来源、myRepoIds 权限过滤、scope、阈值、合并字段建议、簇 key 与 API 契约。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository, RepoVector, TrendingRepository
from app.services.duplicates import (
    DuplicateError,
    cluster_key,
    detect_duplicates,
    name_similarity,
    normalize_repo_key,
    text_tokens,
    token_jaccard,
)

PREFIX = "dup-test-"


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    _cleanup(session)
    yield session
    session.rollback()
    _cleanup(session)
    session.close()


def _cleanup(session) -> None:
    session.execute(delete(RepoVector).where(RepoVector.repo_id.like(f"{PREFIX}%")))
    session.execute(delete(MyRepository).where(MyRepository.id.like(f"{PREFIX}%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like(f"{PREFIX}%")))
    session.commit()


def _my(
    repo_id: str,
    name: str,
    description: str = "",
    *,
    stars: int = 0,
    language: str = "",
    summary: str = "",
    category: str = "",
    url: str = "",
    platform: str = "github",
) -> MyRepository:
    return MyRepository(
        id=f"{PREFIX}{repo_id}",
        platform=platform,
        name=name,
        description=description,
        html_url=url or f"https://github.com/{PREFIX}{repo_id}",
        stars=stars,
        language=language,
        readme_summary=summary,
        category_id=category,
    )


def _trending(
    repo_id: str,
    name: str,
    description: str = "",
    *,
    stars: int = 0,
    language: str = "",
    tech: str = "",
    url: str = "",
    platform: str = "github",
) -> TrendingRepository:
    return TrendingRepository(
        id=f"{PREFIX}{repo_id}",
        platform=platform,
        name=name,
        description=description,
        html_url=url or f"https://github.com/{PREFIX}{repo_id}",
        stars=stars,
        language=language,
        tech_stack=tech,
    )


def _add_vector(db, source: str, repo_id: str, vector: list[float], model: str = "test-model") -> None:
    db.add(
        RepoVector(
            source=source,
            repo_id=f"{PREFIX}{repo_id}",
            model=model,
            backend="hash",
            dim=len(vector),
            text_hash=f"hash-{source}-{repo_id}",
            vector=json.dumps(vector),
        )
    )


def _ids(*repo_ids: str) -> list[str]:
    return [f"{PREFIX}{repo_id}" for repo_id in repo_ids]


def test_normalize_repo_key_variants() -> None:
    assert normalize_repo_key("github", "Acme/Awesome-Tool") == "github:acme/awesome-tool"
    assert (
        normalize_repo_key("github", "Acme/Awesome-Tool", "https://github.com/Acme/Awesome-Tool.git")
        == "github:acme/awesome-tool"
    )
    assert (
        normalize_repo_key("", "acme/awesome-tool", "http://www.github.com/acme/awesome-tool/")
        == "github:acme/awesome-tool"
    )
    assert (
        normalize_repo_key("", "acme/awesome-tool", "https://gitee.com/Acme/Awesome-Tool")
        == "gitee:acme/awesome-tool"
    )


def test_name_similarity_handles_separators_and_camel_case() -> None:
    assert name_similarity("tenant-admin", "tenant_admin") == 1.0
    assert name_similarity("tenantAdmin", "tenant-admin") == 1.0
    assert name_similarity("react-admin", "react-admin-pro") > 0.8
    assert name_similarity("langchain", "numpy") < 0.4


def test_text_tokens_chinese_bigram_and_jaccard() -> None:
    left = text_tokens("多租户 SaaS 计费与订阅管理平台")
    right = text_tokens("多租户 SaaS 订阅计费管理平台")
    assert "多租" in left and "租户" in left
    assert token_jaccard(left, right) > 0.5
    assert token_jaccard(text_tokens("Python 命令行工具"), text_tokens("React 组件库")) == 0.0


def test_exact_duplicate_across_sources(db) -> None:
    db.add_all(
        [
            _my("acme/awesome-tool", "awesome-tool", "Acme 的工具集", stars=120, language="TypeScript"),
            _trending("Acme/Awesome-Tool", "Awesome Tool", "Acme 的工具集", stars=130, tech="TypeScript"),
        ]
    )
    db.commit()

    result = detect_duplicates(
        db,
        "all",
        my_repo_ids=_ids("acme/awesome-tool"),
        max_repos=5000,
    )
    assert result["scanned"] >= 2
    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert cluster["kind"] == "exact"
    assert cluster["confidence"] == 1.0
    assert len(cluster["members"]) == 2
    assert cluster["suggestion"]["keep"] == {
        "source": "my",
        "repoId": f"{PREFIX}acme/awesome-tool",
    }
    assert {member["role"] for member in cluster["members"]} == {"canonical", "merge"}


def test_name_duplicate_same_owner(db) -> None:
    db.add_all(
        [
            _my("acme/tenant-admin", "tenant-admin", "多租户后台", stars=10, language="TypeScript"),
            _my("acme/tenant_admin", "tenant_admin", "多租户后台模板", stars=8, language="TypeScript"),
        ]
    )
    db.commit()

    result = detect_duplicates(
        db,
        "my",
        my_repo_ids=_ids("acme/tenant-admin", "acme/tenant_admin"),
        max_repos=5000,
    )
    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert cluster["kind"] == "name"
    assert cluster["confidence"] >= 0.7
    assert any("仓库名相似度" in reason for reason in cluster["reasons"])


def test_semantic_duplicate_with_vector_review(db) -> None:
    db.add_all(
        [
            _my(
                "billing-kit",
                "billing-kit",
                "多租户 SaaS 计费与订阅管理平台",
                stars=30,
                language="TypeScript",
            ),
            _trending(
                "subscription-engine",
                "subscription-engine",
                "多租户 SaaS 订阅计费管理平台",
                stars=90,
                language="TypeScript",
                tech="React, TypeScript",
            ),
        ]
    )
    _add_vector(db, "my", "billing-kit", [1.0, 0.0, 0.0])
    _add_vector(db, "trending", "subscription-engine", [1.0, 0.0, 0.0])
    db.commit()

    result = detect_duplicates(
        db,
        "all",
        my_repo_ids=_ids("billing-kit"),
        max_repos=5000,
    )
    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert cluster["kind"] == "semantic"
    assert cluster["confidence"] >= 0.7
    assert any("向量余弦相似度" in reason for reason in cluster["reasons"])
    assert cluster["members"][0]["signals"]["vectorSimilarity"] == 1.0


def test_unrelated_repos_not_clustered(db) -> None:
    db.add_all(
        [
            _my("acme/payments", "payments", "支付网关 SDK", stars=20, language="Go"),
            _my("acme/charts", "charts", "React 图表组件库", stars=15, language="TypeScript"),
        ]
    )
    db.commit()
    result = detect_duplicates(db, "my", my_repo_ids=_ids("acme/payments", "acme/charts"), max_repos=5000)
    assert result["clusters"] == []


def test_my_repo_ids_filter_excludes_other_users(db) -> None:
    db.add_all(
        [
            _my("acme/tenant-admin", "tenant-admin", "多租户后台", stars=10),
            _my("acme/tenant_admin", "tenant_admin", "多租户后台模板", stars=8),
        ]
    )
    db.commit()

    only_one = detect_duplicates(db, "my", my_repo_ids=_ids("acme/tenant-admin"), max_repos=5000)
    assert only_one["clusters"] == []

    both = detect_duplicates(
        db, "my", my_repo_ids=_ids("acme/tenant-admin", "acme/tenant_admin"), max_repos=5000
    )
    assert len(both["clusters"]) == 1


def test_scope_trending_excludes_my_rows(db) -> None:
    db.add_all(
        [
            _my("acme/awesome-tool", "awesome-tool", "工具集", stars=120),
            _trending("Acme/Awesome-Tool", "Awesome Tool", "工具集", stars=130),
        ]
    )
    db.commit()
    result = detect_duplicates(db, "trending", max_repos=5000)
    assert result["clusters"] == []


def test_min_score_filters_cluster(db) -> None:
    db.add_all(
        [
            _my("acme/tenant-admin", "tenant-admin", "多租户后台", stars=10),
            _my("acme/tenant_admin", "tenant_admin", "多租户后台模板", stars=8),
        ]
    )
    db.commit()
    strict = detect_duplicates(
        db,
        "my",
        my_repo_ids=_ids("acme/tenant-admin", "acme/tenant_admin"),
        min_score=0.999,
        max_repos=5000,
    )
    assert strict["clusters"] == []


def test_merge_suggestion_collects_best_fields(db) -> None:
    db.add_all(
        [
            _my(
                "acme/tool",
                "tool",
                "工具",
                stars=100,
                language="TypeScript",
                category="devtools",
                summary="",
            ),
            _trending(
                "Acme/Tool",
                "Tool",
                "Acme 出品的开发者工具集，支持插件扩展与多语言",
                stars=900,
                tech="Node.js, TypeScript",
            ),
        ]
    )
    db.commit()
    result = detect_duplicates(db, "all", my_repo_ids=_ids("acme/tool"), max_repos=5000)
    cluster = result["clusters"][0]
    suggestion = cluster["suggestion"]
    assert suggestion["keep"]["source"] == "my"
    fields = {item["field"]: item for item in suggestion["fields"]}
    assert fields["description"]["from"]["source"] == "trending"
    assert fields["stars"]["value"] == 900
    assert "techStack" in fields
    assert suggestion["action"] in {"merge", "review"}


def test_max_clusters_limits_output(db) -> None:
    db.add_all(
        [
            _my("acme/alpha-one", "alpha-one", "Alpha 工具", stars=10),
            _my("acme/alpha_one", "alpha_one", "Alpha 工具", stars=9),
            _my("acme/beta-two", "beta-two", "Beta 工具", stars=8),
            _my("acme/beta_two", "beta_two", "Beta 工具", stars=7),
        ]
    )
    db.commit()
    result = detect_duplicates(
        db,
        "my",
        my_repo_ids=_ids("acme/alpha-one", "acme/alpha_one", "acme/beta-two", "acme/beta_two"),
        max_repos=5000,
        max_clusters=1,
    )
    assert len(result["clusters"]) == 1


def test_cluster_key_is_stable_regardless_of_order(db) -> None:
    rows = [
        _my("acme/one", "one", "同一项目", stars=1),
        _my("acme/two", "two", "同一项目", stars=1),
    ]
    first = cluster_key([_to_repo(row) for row in rows])
    second = cluster_key([_to_repo(row) for row in reversed(rows)])
    assert first == second


def _to_repo(row):
    from app.services.duplicates import _to_repo as converter

    return converter("my", row)


def test_scan_api_contract(db) -> None:
    db.add_all(
        [
            _my("acme/api-one", "api-one", "API 工具", stars=10),
            _my("acme/api_one", "api_one", "API 工具", stars=8),
        ]
    )
    db.commit()
    client = TestClient(app)
    response = client.post(
        "/api/duplicates/scan",
        json={
            "scope": "my",
            "myRepoIds": _ids("acme/api-one", "acme/api_one"),
            "maxRepos": 5000,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "my"
    assert body["scanId"].startswith("dup_")
    assert body["scanned"] == 2
    assert len(body["clusters"]) == 1
    assert body["clusters"][0]["members"][0]["repoId"].startswith(PREFIX)
    fields = body["clusters"][0]["suggestion"]["fields"]
    if fields:
        assert "from" in fields[0]


def test_scan_api_rejects_invalid_scope() -> None:
    client = TestClient(app)
    response = client.post("/api/duplicates/scan", json={"scope": "unknown"})
    assert response.status_code == 422


def test_normalize_scope_rejects_unknown() -> None:
    with SessionLocal() as session:
        with pytest.raises(DuplicateError):
            detect_duplicates(session, "unknown")
