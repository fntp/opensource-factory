"""热榜详情接口测试：摘要回退优先级、元信息与 404（无网络）。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.trending import build_trending_summary
from app.db import SessionLocal
from app.main import app
from app.models import TrendingRepository


def _make_row(repo_id: str, **overrides) -> TrendingRepository:
    values = {
        "id": repo_id,
        "platform": "github",
        "name": repo_id.split("/")[-1],
        "html_url": f"https://github.com/{repo_id}",
        "stars_today": 512,
        "description": "构建上下文感知推理应用的开源框架",
        "tech_stack": "Python, LLM, RAG",
        "owner": repo_id.split("/")[0],
        "language": "Python",
        "stars": 94210,
    }
    values.update(overrides)
    return TrendingRepository(**values)


def test_build_summary_prefers_readme_summary() -> None:
    row = _make_row("demo/readme", readme_summary="模型生成的中文摘要")
    assert build_trending_summary(row) == ("模型生成的中文摘要", "readme")


def test_build_summary_falls_back_to_description_then_tech() -> None:
    row = _make_row("demo/description", description="项目描述")
    assert build_trending_summary(row) == ("项目描述", "description")

    row.description = ""
    assert build_trending_summary(row) == ("该项目主要使用 Python, LLM, RAG。", "tech")

    row.tech_stack = ""
    assert build_trending_summary(row) == ("", "empty")


def test_trending_detail_returns_summary_and_metadata() -> None:
    repo_id = "openai/detail-test-0915"
    db = SessionLocal()
    try:
        db.merge(_make_row(repo_id, readme_summary="这是一个用于测试的热榜项目摘要。"))
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        resp = client.get(f"/api/trending/{repo_id}")
        missing = client.get("/api/trending/openai/not-found-0915")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == repo_id
    assert body["owner"] == "openai"
    assert body["language"] == "Python"
    assert body["stars"] == 94210
    assert body["stars_today"] == 512
    assert body["tech_stack"] == "Python, LLM, RAG"
    assert body["summary"] == "这是一个用于测试的热榜项目摘要。"
    assert body["summary_source"] == "readme"
    assert missing.status_code == 404

    db = SessionLocal()
    try:
        row = db.get(TrendingRepository, repo_id)
        if row is not None:
            db.delete(row)
            db.commit()
    finally:
        db.close()
