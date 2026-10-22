"""Agent 工作流测试（REQ-202610-0968 / M7-09，无网络）。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services.agent_workflow import (
    ActionSnapshot,
    RepoSnapshot,
    build_agent_response,
    build_draft,
    compute_stats,
    plan_workflow,
)

REPOS = [
    RepoSnapshot(
        repo_id="acme/agent-kit",
        name="agent-kit",
        description="面向开发者的 Agent 编排工具",
        language="TypeScript",
        stars=12800,
        category="AI / 大模型",
        tags=("Agent", "TypeScript"),
        summary="可视化编排 Agent 与工作流。",
    ),
    RepoSnapshot(
        repo_id="acme/pay-gateway",
        name="pay-gateway",
        description="多渠道支付网关",
        language="Go",
        stars=3200,
        category="金融 / 支付",
        tags=("支付", "Go"),
        summary="统一支付、结算与对账。",
    ),
    RepoSnapshot(
        repo_id="acme/notes",
        name="notes",
        description="本地优先的笔记应用",
        language="Rust",
        stars=800,
        category="效率工具",
        tags=("笔记",),
    ),
]

TAGS = [
    ActionSnapshot("tag", "acme/agent-kit", "AI/LLM", 0.92, "摘要命中"),
    ActionSnapshot("tag", "acme/notes", "本地优先", 0.68, "摘要命中"),
]
CATEGORIES = [
    ActionSnapshot("category", "acme/agent-kit", "AI / 大模型", 0.88, "名称命中"),
]


def test_compute_stats_counts_categories_languages_tags() -> None:
    stats = compute_stats(REPOS)
    assert stats["totalRepos"] == 3
    assert stats["totalStars"] == 16800
    assert stats["categoryCount"] == 3
    assert stats["languageCount"] == 3
    assert stats["tagCount"] == 5
    assert stats["topLanguage"] == "TypeScript"


def test_plan_workflow_marks_steps_and_threshold() -> None:
    steps = plan_workflow("full", REPOS, TAGS, CATEGORIES, 0.75, "apply")
    by_key = {step["key"]: step for step in steps}
    assert by_key["inventory"]["count"] == 3
    assert by_key["tags"]["count"] == 1
    assert by_key["categories"]["count"] == 1
    assert by_key["draft"]["status"] == "ready"
    assert "写入" in by_key["tags"]["detail"]


def test_plan_workflow_preview_does_not_claim_write() -> None:
    steps = plan_workflow("organize", REPOS, TAGS, CATEGORIES, 0.75, "preview")
    by_key = {step["key"]: step for step in steps}
    assert "不写入" in by_key["tags"]["detail"]
    assert by_key["draft"]["status"] == "ready"


def test_plan_workflow_draft_template_skips_organize() -> None:
    steps = plan_workflow("draft", REPOS, TAGS, CATEGORIES, 0.75, "apply")
    by_key = {step["key"]: step for step in steps}
    assert by_key["organize"]["status"] == "skipped"
    assert by_key["draft"]["status"] == "ready"


def test_build_draft_groups_categories_and_escapes_markdown() -> None:
    draft = build_draft(
        "full",
        REPOS,
        applied_tags=TAGS[:1],
        applied_categories=CATEGORIES,
        generated_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
    )
    markdown = draft["markdown"]
    assert draft["title"].startswith("我的开源收藏精选")
    assert "## 概览" in markdown
    assert "## 本期亮点" in markdown
    assert "### AI / 大模型（1）" in markdown
    assert "acme/agent-kit" in markdown
    assert "应用标签建议 1 条" in markdown
    assert "应用分类建议 1 条" in markdown
    assert draft["highlights"]


def test_build_draft_handles_empty_collection() -> None:
    draft = build_draft("draft", [], generated_at=datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert "收藏库还是空的" in draft["markdown"]
    assert draft["stats"]["totalRepos"] == 0


def test_build_agent_response_normalizes_template_mode_threshold() -> None:
    result = build_agent_response(
        template="unknown",
        mode="apply",
        threshold=1.5,
        repos=REPOS,
        pending_tags=TAGS,
        pending_categories=CATEGORIES,
        focus="Agent 专题",
    )
    assert result["template"] == "draft"
    assert result["mode"] == "apply"
    assert result["threshold"] == 1.0
    assert result["draft"]["title"] == "Agent 专题 · 收藏精选草稿"
    assert len(result["plan"]) == 3


def test_agent_draft_api_contract() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/agent/draft",
        json={
            "template": "full",
            "mode": "apply",
            "threshold": 0.7,
            "focus": "本周精选",
            "repos": [
                {
                    "repoId": "demo/ai-app",
                    "name": "ai-app",
                    "description": "基于大模型的对话应用",
                    "language": "Python",
                    "stars": 1200,
                    "category": "AI / 大模型",
                    "tags": ["LLM", "RAG"],
                    "summary": "支持 RAG 与 Agent 工具调用。",
                }
            ],
            "pendingTags": [
                {"kind": "tag", "repoId": "demo/ai-app", "value": "RAG", "score": 0.9}
            ],
            "pendingCategories": [
                {
                    "kind": "category",
                    "repoId": "demo/ai-app",
                    "value": "AI / 大模型",
                    "score": 0.86,
                }
            ],
            "appliedTags": [],
            "appliedCategories": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["template"] == "full"
    assert payload["threshold"] == 0.7
    assert payload["plan"][0]["key"] == "inventory"
    assert payload["draft"]["title"] == "本周精选 · 收藏精选草稿"
    assert "demo/ai-app" in payload["draft"]["markdown"]
    assert payload["generatedAt"]
