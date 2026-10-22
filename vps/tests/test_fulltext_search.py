"""README 全文检索（M6-01）测试。

覆盖：FTS5 建表与触发器同步、中文 / 英文检索、bm25 排序、snippet、scope 过滤、
1~2 字短词 LIKE 回退、索引状态 / 重建、README 补索引任务、内部 API 契约。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository, RepoReadme, TrendingRepository
from app.services.fulltext import (
    FulltextError,
    delete_readme,
    get_index_status,
    rebuild_index,
    save_readme,
    search_fulltext,
    sync_readmes,
)


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    session.execute(delete(RepoReadme))
    session.execute(delete(MyRepository).where(MyRepository.id.like("fts-test/%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like("fts-test/%")))
    session.commit()
    yield session
    # 清理本文件的测试数据，避免污染其他用例的全局画像 / 候选集
    session.execute(delete(RepoReadme))
    session.execute(delete(MyRepository).where(MyRepository.id.like("fts-test/%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like("fts-test/%")))
    session.commit()
    session.close()


def _seed(db) -> dict[str, str]:
    rows = [
        MyRepository(
            id="fts-test/pay-gateway",
            platform="github",
            name="pay-gateway",
            description="分布式支付网关",
            html_url="https://example.com/fts-test/pay-gateway",
            stars=320,
            language="Go",
        ),
        MyRepository(
            id="fts-test/react-ui",
            platform="github",
            name="react-ui",
            description="React 组件库",
            html_url="https://example.com/fts-test/react-ui",
            stars=88,
            language="TypeScript",
        ),
        TrendingRepository(
            id="fts-test/vector-db",
            platform="github",
            name="vector-db",
            description="向量数据库",
            html_url="https://example.com/fts-test/vector-db",
            stars_today=66,
            language="Rust",
        ),
    ]
    db.add_all(rows)
    db.commit()
    save_readme(
        db,
        source="my",
        repo_id="fts-test/pay-gateway",
        content=(
            "# Pay Gateway\n\n"
            "一个面向跨境电商的支付网关，支持分布式事务、幂等重试与对账。\n"
            "Payment gateway with idempotent retry and reconciliation."
        ),
    )
    save_readme(
        db,
        source="my",
        repo_id="fts-test/react-ui",
        content="# React UI\n\n现代 React component library，支持主题定制与服务端渲染。",
    )
    save_readme(
        db,
        source="trending",
        repo_id="fts-test/vector-db",
        content="# Vector DB\n\n向量数据库，支持全文检索与混合搜索（hybrid search）。",
    )
    return {
        "my_pay": "fts-test/pay-gateway",
        "my_ui": "fts-test/react-ui",
        "trend_vector": "fts-test/vector-db",
    }


def test_save_readme_syncs_fts_trigger(db) -> None:
    _seed(db)
    rows = db.execute(text("SELECT source, repo_id FROM repo_readme_fts")).all()
    assert ("my", "fts-test/pay-gateway") in rows
    assert ("trending", "fts-test/vector-db") in rows

    save_readme(
        db,
        source="my",
        repo_id="fts-test/react-ui",
        content="# React UI\n\n更新后的内容：微前端与设计系统。",
    )
    result = search_fulltext(db, "微前端", scope="my")
    assert result["mode"] == "fts"
    assert [item["id"] for item in result["items"]] == ["fts-test/react-ui"]

    assert delete_readme(db, source="my", repo_id="fts-test/react-ui") is True
    assert search_fulltext(db, "微前端", scope="my")["count"] == 0


def test_search_chinese_and_english(db) -> None:
    ids = _seed(db)

    chinese = search_fulltext(db, "分布式事务", scope="all")
    assert chinese["mode"] == "fts"
    assert chinese["items"][0]["id"] == ids["my_pay"]
    assert "分布式事务" in chinese["items"][0]["snippet"]
    assert chinese["items"][0]["matchedTerms"] == ["分布式事务"]
    assert chinese["items"][0]["score"] > 0

    english = search_fulltext(db, "reconciliation", scope="all")
    assert english["mode"] == "fts"
    assert english["items"][0]["id"] == ids["my_pay"]


def test_search_short_query_falls_back_to_like(db) -> None:
    ids = _seed(db)
    result = search_fulltext(db, "支付", scope="all")
    assert result["mode"] == "like"
    assert result["items"][0]["id"] == ids["my_pay"]
    assert "支付" in result["items"][0]["snippet"]
    assert result["items"][0]["score"] == 1.0


def test_search_mixed_short_and_long_terms(db) -> None:
    ids = _seed(db)
    result = search_fulltext(db, "支付 分布式", scope="all")
    assert result["mode"] == "fts"
    assert [item["id"] for item in result["items"]] == [ids["my_pay"]]
    assert set(result["items"][0]["matchedTerms"]) == {"支付", "分布式"}


def test_search_scope_and_ranking(db) -> None:
    ids = _seed(db)

    trending = search_fulltext(db, "全文检索", scope="trending")
    assert [item["id"] for item in trending["items"]] == [ids["trend_vector"]]
    assert all(item["source"] == "trending" for item in trending["items"])

    my_only = search_fulltext(db, "React", scope="my")
    assert [item["id"] for item in my_only["items"]] == [ids["my_ui"]]

    with pytest.raises(FulltextError):
        search_fulltext(db, "React", scope="unknown")
    with pytest.raises(FulltextError):
        search_fulltext(db, "   ")


def test_index_status_and_rebuild(db) -> None:
    _seed(db)
    status = get_index_status(db)
    assert status["enabled"] is True
    assert status["totalDocs"] == 3
    assert status["bySource"] == {"my": 2, "trending": 1}
    assert status["ftsDocs"] == 3
    assert status["totalChars"] > 0

    db.execute(text("DELETE FROM repo_readme_fts"))
    db.commit()
    assert search_fulltext(db, "分布式事务", scope="all")["mode"] == "like"

    rebuilt = rebuild_index(db)
    assert rebuilt["rebuilt"] == 3
    assert search_fulltext(db, "分布式事务", scope="all")["mode"] == "fts"


def test_sync_readmes_fetches_and_skips_existing(db) -> None:
    db.add(
        MyRepository(
            id="fts-test/new-repo",
            platform="github",
            name="new-repo",
            description="待补索引",
            html_url="https://example.com/fts-test/new-repo",
            stars=1,
        )
    )
    db.commit()

    calls: list[str] = []

    def fetch(repo_id: str) -> str:
        calls.append(repo_id)
        return "# New Repo\n\n支持增量索引与全文检索。"

    first = sync_readmes(db, source="my", repo_ids=["fts-test/new-repo"], fetch_fn=fetch)
    assert first["status"] == "ok"
    assert first["indexed"] == 1
    assert calls == ["fts-test/new-repo"]
    assert search_fulltext(db, "增量索引", scope="my")["items"][0]["id"] == "fts-test/new-repo"

    second = sync_readmes(db, source="my", repo_ids=["fts-test/new-repo"], fetch_fn=fetch)
    assert second["total"] == 0
    assert second["indexed"] == 0

    forced = sync_readmes(
        db, source="my", repo_ids=["fts-test/new-repo"], force=True, fetch_fn=fetch
    )
    assert forced["indexed"] == 1


def test_search_api_endpoints(db) -> None:
    _seed(db)
    with TestClient(app) as client:
        response = client.post(
            "/api/search/fulltext", json={"query": "分布式事务", "scope": "all", "topK": 5}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "fts"
        assert body["items"][0]["fullName"] == "fts-test/pay-gateway"
        assert "分布式事务" in body["items"][0]["snippet"]

        status_response = client.get("/api/search/fulltext/status")
        assert status_response.status_code == 200
        assert status_response.json()["totalDocs"] == 3

        rebuilt = client.post("/api/search/fulltext/rebuild")
        assert rebuilt.status_code == 200
        assert rebuilt.json()["rebuilt"] == 3

        empty = client.post("/api/search/fulltext", json={"query": "   "})
        assert empty.status_code == 400

        bad_scope = client.post("/api/search/fulltext", json={"query": "x", "scope": "bad"})
        assert bad_scope.status_code == 422
