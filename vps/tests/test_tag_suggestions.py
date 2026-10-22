"""自动打标建议测试（REQ-202610-0960 / M7-01，无网络）。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository
from app.services.tag_suggestions import (
    generate_for_repositories,
    normalize_tag_key,
    suggest_tags,
)

SUMMARY = (
    "这个项目是一个面向开发者的智能工作台，提供仓库同步与中文摘要生成。"
    "后端基于 Python FastAPI 构建，前端使用 React 与 TypeScript，适合团队管理开源资产。"
)


def _add_repo(repo_id: str, *, summary: str | None, language: str | None = "Python", stars: int = 10) -> None:
    db = SessionLocal()
    try:
        db.merge(
            MyRepository(
                id=repo_id,
                platform="github",
                name=repo_id.split("/")[-1],
                description="示例仓库",
                html_url=f"https://github.com/{repo_id}",
                stars=stars,
                language=language,
                readme_summary=summary,
            )
        )
        db.commit()
    finally:
        db.close()


def _remove_repos(*repo_ids: str) -> None:
    db = SessionLocal()
    try:
        for repo_id in repo_ids:
            row = db.get(MyRepository, repo_id)
            if row is not None:
                db.delete(row)
        db.commit()
    finally:
        db.close()


def test_normalize_tag_key() -> None:
    assert normalize_tag_key("  #AI/LLM ") == "ai/llm"
    assert normalize_tag_key("Next.js") == "next.js"


def test_language_field_wins_and_framework_detected() -> None:
    tags = suggest_tags(SUMMARY, language="Python")
    names = [item["name"] for item in tags]
    assert names[0] == "Python"
    assert tags[0]["score"] == 0.83  # 0.45 + 0.35 + 一次额外命中
    assert "FastAPI" in names
    assert "React" in names
    assert all(item["evidence"] for item in tags)


def test_english_alias_uses_word_boundary() -> None:
    tags = suggest_tags("一个 reactive 风格的实验项目，与网页框架无关。", language="")
    assert "React" not in [item["name"] for item in tags]

    tags = suggest_tags("前端使用 React 构建交互界面。", language="")
    react = next(item for item in tags if item["name"] == "React")
    assert react["category"] == "framework"
    assert "React" in react["evidence"]


def test_chinese_keyword_and_reason() -> None:
    tags = suggest_tags("基于大模型构建的对话应用，支持私有化部署。", language="")
    by_name = {item["name"]: item for item in tags}
    assert "AI/LLM" in by_name
    assert "大模型" in by_name["AI/LLM"]["reason"]
    assert by_name["AI/LLM"]["category"] == "domain"
    assert "自托管" in by_name


def test_existing_tags_are_excluded() -> None:
    tags = suggest_tags(SUMMARY, language="Python", existing_tags=["python", "React"])
    names = [item["name"] for item in tags]
    assert "Python" not in names
    assert "React" not in names
    assert "FastAPI" in names


def test_limit_is_capped_per_repo() -> None:
    tags = suggest_tags(SUMMARY, language="Python", limit=2)
    assert len(tags) == 2
    assert tags[0]["score"] >= tags[1]["score"]


def test_description_fallback_marks_source() -> None:
    tags = suggest_tags("", description="一个基于 Vue 的数据可视化面板。", language="")
    vue = next(item for item in tags if item["name"] == "Vue")
    assert "简介" in vue["reason"]


def test_generate_for_repositories_skips_missing_summary() -> None:
    init_db()
    _add_repo("test-0960/has-summary", summary=SUMMARY, language="Python", stars=100)
    _add_repo("test-0960/no-summary", summary=None, language="Python", stars=50)
    try:
        db = SessionLocal()
        try:
            result = generate_for_repositories(db, repo_ids=["test-0960/has-summary", "test-0960/no-summary"])
        finally:
            db.close()
        assert result["scanned"] == 2
        assert result["suggested"] == 1
        assert result["skipped"] == 1
        assert result["items"][0]["repoId"] == "test-0960/has-summary"
        assert result["items"][0]["tags"]
    finally:
        _remove_repos("test-0960/has-summary", "test-0960/no-summary")


def test_generate_api_contract() -> None:
    init_db()
    _add_repo("test-0960/api", summary=SUMMARY, language="Python", stars=200)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/tag-suggestions/generate",
            json={"repoIds": ["test-0960/api"], "perRepo": 4},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["scanned"] == 1
        assert body["suggested"] == 1
        assert body["items"][0]["repoId"] == "test-0960/api"
        assert len(body["items"][0]["tags"]) <= 4
        first = body["items"][0]["tags"][0]
        assert set(first) == {"name", "category", "score", "reason", "evidence"}
    finally:
        _remove_repos("test-0960/api")
