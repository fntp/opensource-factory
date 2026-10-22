"""多轮问答式检索测试（M6-09，不访问网络）。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository, RepoVector, TrendingRepository
from app.services.conversation_search import (
    ChatError,
    ChatMessage,
    chat_search,
    detect_language,
    detect_scope,
    extract_topic,
    normalize_messages,
    resolve_context,
)
from app.services.embedding import EmbeddingService
from app.services.vector_pipeline import build_repo_text


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    session.execute(delete(RepoVector).where(RepoVector.repo_id.like("chat-test/%")))
    session.execute(delete(MyRepository).where(MyRepository.id.like("chat-test/%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like("chat-test/%")))
    session.commit()
    yield session
    session.close()


def _seed(db) -> dict[str, str]:
    rows = [
        MyRepository(
            id="chat-test/pay-rust",
            platform="github",
            name="pay-rust",
            description="Rust 支付网关，支持账单、结账与退款",
            html_url="https://example.com/chat-test/pay-rust",
            stars=120,
            language="Rust",
            readme_summary="面向跨境电商的支付网关",
        ),
        MyRepository(
            id="chat-test/pay-python",
            platform="github",
            name="pay-python",
            description="Python 支付对账与账单工具",
            html_url="https://example.com/chat-test/pay-python",
            stars=30,
            language="Python",
        ),
        MyRepository(
            id="chat-test/other-log",
            platform="github",
            name="log-analyzer",
            description="Go 日志分析与告警平台",
            html_url="https://example.com/chat-test/other-log",
            stars=88,
            language="Go",
        ),
        MyRepository(
            id="chat-test/secret-pay",
            platform="github",
            name="secret-pay",
            description="内部支付结算系统",
            html_url="https://example.com/chat-test/secret-pay",
            stars=999,
            language="Rust",
        ),
        TrendingRepository(
            id="chat-test/trend-pay",
            platform="github",
            name="trend-pay",
            description="开源支付聚合与账单平台",
            html_url="https://example.com/chat-test/trend-pay",
            stars=900,
            stars_today=50,
            tech_stack="TypeScript, React",
            language="TypeScript",
        ),
        TrendingRepository(
            id="chat-test/trend-log",
            platform="github",
            name="trend-log",
            description="日志可观测性平台",
            html_url="https://example.com/chat-test/trend-log",
            stars=700,
            stars_today=12,
            tech_stack="Go",
            language="Go",
        ),
    ]
    db.add_all(rows)
    db.commit()

    service = EmbeddingService(force_fallback=True)
    for row in rows:
        source = "my" if isinstance(row, MyRepository) else "trending"
        vector = service.encode_one(build_repo_text(source, row))
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
        "pay_rust": "chat-test/pay-rust",
        "pay_python": "chat-test/pay-python",
        "other_log": "chat-test/other-log",
        "secret_pay": "chat-test/secret-pay",
        "trend_pay": "chat-test/trend-pay",
        "trend_log": "chat-test/trend-log",
    }


def test_normalize_messages_validation() -> None:
    messages = normalize_messages(
        [
            {"role": "user", "content": "  我的收藏里有哪些支付项目？  "},
            {"role": "assistant", "content": "找到 2 个。"},
            {"role": "user", "content": "那 Rust 的呢？"},
        ]
    )
    assert [item.role for item in messages] == ["user", "assistant", "user"]
    assert messages[0].content == "我的收藏里有哪些支付项目？"

    with pytest.raises(ChatError):
        normalize_messages([])
    with pytest.raises(ChatError):
        normalize_messages([{"role": "system", "content": "hi"}])
    with pytest.raises(ChatError):
        normalize_messages([{"role": "user", "content": "x" * 501}])
    with pytest.raises(ChatError):
        normalize_messages(
            [
                {"role": "user", "content": "问题"},
                {"role": "assistant", "content": "回答"},
            ]
        )


def test_language_scope_and_topic_parsing() -> None:
    assert detect_language("那 Rust 的呢？") == ("Rust", True)
    assert detect_language("Python 项目") == ("Python", True)
    assert detect_language("不限语言") == ("", True)
    assert detect_language("支付项目") == ("", False)

    assert detect_scope("我的收藏里有哪些") == "my"
    assert detect_scope("热榜里有哪些") == "trending"
    assert detect_scope("全部来源") == "all"
    assert detect_scope("我的收藏和热榜对比") == "all"
    assert detect_scope("有哪些支付项目") is None

    assert extract_topic("我的收藏里有哪些支付相关项目？") == "支付"
    assert extract_topic("帮我找一些支付相关的项目") == "支付"
    assert extract_topic("那 Rust 的呢？") == ""
    assert extract_topic("还有吗？") == ""
    assert extract_topic("换个话题：推荐系统") == "推荐系统"


def test_resolve_context_inherits_topic_and_filters() -> None:
    messages = [
        ChatMessage("user", "我的收藏里有哪些支付相关项目？"),
        ChatMessage("assistant", "找到 2 个支付项目。"),
        ChatMessage("user", "那 Rust 的呢？"),
    ]
    context, question = resolve_context(messages)
    assert question == "那 Rust 的呢？"
    assert context.topic == "支付"
    assert context.language == "Rust"
    assert context.scope == "my"
    assert context.intent == "list"
    assert context.turn == 2

    messages.append(ChatMessage("user", "还有吗？"))
    context, _ = resolve_context(messages, shown_ids=["chat-test/pay-rust"])
    assert context.intent == "more"
    assert context.topic == "支付"
    assert context.language == "Rust"
    assert context.excluded == ("chat-test/pay-rust",)


def test_chat_search_my_scope_and_privacy(db) -> None:
    ids = _seed(db)
    result = chat_search(
        db,
        [{"role": "user", "content": "我的收藏里有哪些支付相关项目？"}],
        my_repo_ids=[ids["pay_rust"], ids["pay_python"]],
        top_k=5,
    )
    assert result["scope"] == "my"
    assert result["intent"] == "list"
    assert result["topic"] == "支付"
    assert result["total"] >= 2
    item_ids = {item["id"] for item in result["items"]}
    assert ids["pay_rust"] in item_ids
    assert ids["pay_python"] in item_ids
    assert ids["secret_pay"] not in item_ids
    assert ids["trend_pay"] not in item_ids
    assert "支付" in result["answer"]
    assert result["items"][0]["citation"] == 1
    assert result["suggestions"]


def test_chat_search_explicit_scope_override(db) -> None:
    ids = _seed(db)
    result = chat_search(
        db,
        [{"role": "user", "content": "我的收藏里有哪些支付相关项目？"}],
        my_repo_ids=[ids["pay_rust"], ids["pay_python"]],
        top_k=5,
        scope="trending",
    )
    assert result["scope"] == "trending"
    assert all(item["source"] == "trending" for item in result["items"])
    assert "每日热榜" in result["answer"]


def test_chat_search_language_followup(db) -> None:
    ids = _seed(db)
    messages = [
        {"role": "user", "content": "我的收藏里有哪些支付相关项目？"},
        {"role": "assistant", "content": "找到 2 个支付项目。"},
        {"role": "user", "content": "那 Rust 的呢？"},
    ]
    result = chat_search(
        db,
        messages,
        my_repo_ids=[ids["pay_rust"], ids["pay_python"]],
        top_k=5,
    )
    assert result["language"] == "Rust"
    assert result["topic"] == "支付"
    assert result["items"]
    assert all(item["language"] == "Rust" for item in result["items"])
    assert ids["secret_pay"] not in {item["id"] for item in result["items"]}
    assert "Rust" in result["answer"]


def test_chat_search_more_excludes_shown_ids(db) -> None:
    ids = _seed(db)
    first = chat_search(
        db,
        [{"role": "user", "content": "我的收藏里有哪些支付相关项目？"}],
        my_repo_ids=[ids["pay_rust"], ids["pay_python"]],
        top_k=1,
    )
    first_id = first["items"][0]["id"]
    assert first["total"] >= 2

    second = chat_search(
        db,
        [
            {"role": "user", "content": "我的收藏里有哪些支付相关项目？"},
            {"role": "assistant", "content": first["answer"]},
            {"role": "user", "content": "还有吗？"},
        ],
        my_repo_ids=[ids["pay_rust"], ids["pay_python"]],
        shown_ids=[first_id],
        top_k=5,
    )
    assert second["intent"] == "more"
    assert first_id not in {item["id"] for item in second["items"]}
    assert "继续" in second["answer"] or "没有更多" in second["answer"]


def test_chat_search_empty_my_repo_ids_returns_no_my_items(db) -> None:
    _seed(db)
    result = chat_search(
        db,
        [{"role": "user", "content": "我的收藏里有哪些支付相关项目？"}],
        my_repo_ids=[],
        top_k=5,
    )
    assert result["scope"] == "my"
    assert result["total"] == 0
    assert result["items"] == []
    assert "没有找到" in result["answer"]


def test_chat_search_count_and_compare(db) -> None:
    ids = _seed(db)
    count = chat_search(
        db,
        [{"role": "user", "content": "我的收藏里有多少支付相关项目？"}],
        my_repo_ids=[ids["pay_rust"], ids["pay_python"]],
        top_k=5,
    )
    assert count["intent"] == "count"
    assert "共有" in count["answer"]

    compare = chat_search(
        db,
        [{"role": "user", "content": "我的收藏和热榜里的支付项目对比"}],
        my_repo_ids=[ids["pay_rust"], ids["pay_python"]],
        top_k=5,
    )
    assert compare["intent"] == "compare"
    assert compare["scope"] == "all"
    assert "你的收藏" in compare["answer"]
    assert "每日热榜" in compare["answer"]


def test_chat_api_contract(db) -> None:
    ids = _seed(db)
    client = TestClient(app)
    response = client.post(
        "/api/search/chat",
        json={
            "messages": [{"role": "user", "content": "我的收藏里有哪些支付相关项目？"}],
            "myRepoIds": [ids["pay_rust"], ids["pay_python"]],
            "topK": 5,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer"]
    assert payload["items"]
    assert payload["suggestions"]
    assert payload["filters"]["terms"]

    bad = client.post(
        "/api/search/chat",
        json={"messages": [{"role": "user", "content": ""}]},
    )
    assert bad.status_code == 422
