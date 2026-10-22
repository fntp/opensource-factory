"""自动分类建议测试（M7-02，不访问网络）。

覆盖：关键词词边界 / 中文包含匹配 / 字段权重 / 语言弱信号 / 多业务线排序 /
perRepo 限制 / minScore 过滤 / 空仓库跳过 / VPS 接口契约。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.category_suggestions import (
    BUSINESS_LINES,
    RepoSnapshot,
    business_line_description,
    contains_keyword,
    normalize_text,
    suggest_categories,
    suggest_for_repos,
)


def test_normalize_text_collapses_whitespace() -> None:
    assert normalize_text("  Payment   Gateway \n") == "payment gateway"


def test_contains_keyword_uses_word_boundary_for_ascii() -> None:
    assert contains_keyword("A payment gateway", "payment")
    assert not contains_keyword("email client", "ai")
    assert not contains_keyword("reactive streams", "react")
    assert contains_keyword("React dashboard", "react")


def test_contains_keyword_supports_chinese_substring() -> None:
    assert contains_keyword("支持多渠道支付与自动对账", "支付")
    assert not contains_keyword("支持多渠道收款", "支付")


def test_payment_repo_suggests_fintech_first() -> None:
    repo = RepoSnapshot(
        repo_id="demo/pay-gateway",
        name="pay-gateway",
        description="多渠道 payment gateway，支持支付、退款与对账",
        language="Go",
        summary="面向电商的支付网关，提供统一支付、结算与风控能力。",
        tags=("支付", "网关"),
    )
    suggestions = suggest_categories(repo)
    assert suggestions
    assert suggestions[0].category_name == "金融 / 支付"
    assert suggestions[0].business_line == "fintech"
    assert suggestions[0].score >= 0.55
    assert "支付" in suggestions[0].reason or "payment" in suggestions[0].reason
    assert suggestions[0].evidence


def test_name_hit_outweighs_summary_hit() -> None:
    name_repo = RepoSnapshot(repo_id="demo/name", name="payment-service", summary="普通项目")
    summary_repo = RepoSnapshot(repo_id="demo/summary", name="service", summary="payment")
    name_score = next(
        item.score
        for item in suggest_categories(name_repo, min_score=0.0)
        if item.business_line == "fintech"
    )
    summary_score = next(
        item.score
        for item in suggest_categories(summary_repo, min_score=0.0)
        if item.business_line == "fintech"
    )
    assert name_score > summary_score


def test_language_is_only_a_weak_signal() -> None:
    repo = RepoSnapshot(
        repo_id="demo/ui-kit",
        name="ui-kit",
        description="组件库与设计系统",
        language="TypeScript",
    )
    suggestions = suggest_categories(repo)
    frontend = next(item for item in suggestions if item.business_line == "web-frontend")
    assert frontend.score > 0.45
    # 语言单独不足以超过默认阈值
    language_only = RepoSnapshot(repo_id="demo/ts", name="utils", language="TypeScript")
    assert suggest_categories(language_only) == []


def test_per_repo_limit_and_min_score() -> None:
    repo = RepoSnapshot(
        repo_id="demo/full",
        name="payment ecommerce saas database docker security react mobile blog course",
        description="支付 电商 多租户 数据库 容器 安全 前端 移动端 内容 教育",
    )
    suggestions = suggest_categories(repo, per_repo=2, min_score=0.55)
    assert len(suggestions) == 2
    assert suggestions[0].score >= suggestions[1].score
    assert all(item.score >= 0.55 for item in suggestions)

    high_threshold = suggest_categories(repo, per_repo=5, min_score=1.0)
    assert high_threshold == []


def test_suggest_for_repos_skips_empty_and_counts() -> None:
    repos = [
        RepoSnapshot(repo_id="demo/pay", name="pay", description="payment 支付 对账"),
        RepoSnapshot(repo_id="demo/empty"),
        RepoSnapshot(repo_id="demo/unknown", name="zzz", description="nothing here"),
    ]
    items, scanned, suggested, skipped = suggest_for_repos(repos)
    assert scanned == 2
    assert suggested == len(items[0]["suggestions"])  # type: ignore[index]
    assert skipped == 2
    assert items[0]["repoId"] == "demo/pay"


def test_business_line_catalog_is_unique() -> None:
    keys = [line.key for line in BUSINESS_LINES]
    names = [line.name for line in BUSINESS_LINES]
    assert len(keys) == len(set(keys))
    assert len(names) == len(set(names))
    assert business_line_description("fintech")


def test_generate_api_contract() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/category-suggestions/generate",
        json={
            "repos": [
                {
                    "repoId": "demo/ai-app",
                    "name": "llm-chat",
                    "description": "基于大模型的对话应用",
                    "language": "Python",
                    "summary": "支持 RAG 检索增强与 Agent 工具调用。",
                    "tags": ["LLM", "RAG"],
                }
            ],
            "perRepo": 2,
            "minScore": 0.5,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["scanned"] == 1
    assert payload["suggested"] >= 1
    assert payload["items"][0]["repoId"] == "demo/ai-app"
    assert payload["items"][0]["suggestions"][0]["categoryName"] == "AI / 大模型"
    assert payload["items"][0]["suggestions"][0]["businessLine"] == "ai"
    assert payload["generatedAt"]
