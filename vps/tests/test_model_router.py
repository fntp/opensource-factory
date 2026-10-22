"""模型路由与升级测试（REQ-202610-0965 / M7-06）。

全部离线：不访问 Ollama / DeepSeek，只验证目录、策略、预算、配置持久化与 API 契约。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import init_db
from app.main import app
from app.services import model_router
from app.services.model_router import (
    MODEL_ROUTING_CATALOG,
    TASK_KEYS,
    TASK_SPECS,
    RouteValidationError,
    clear_route_cache,
    get_route_decision,
    load_route_configs,
    overview_payload,
    reset_all_route_configs,
    route_task,
    save_route_config,
    select_model,
    upgrade_candidates,
)


@pytest.fixture(autouse=True)
def _clean_route_configs():
    init_db()
    reset_all_route_configs()
    clear_route_cache()
    yield
    reset_all_route_configs()
    clear_route_cache()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_catalog_and_tasks_are_complete() -> None:
    assert set(TASK_KEYS) == set(TASK_SPECS)
    for task, spec in TASK_SPECS.items():
        assert spec.default_model_id in spec.candidates
        for model_id in spec.candidates:
            model = MODEL_ROUTING_CATALOG[model_id]
            assert model.resident_mb <= 2048
        decision = route_task(task)
        assert decision.model_id in spec.candidates
        assert decision.within_budget is True
        assert decision.budget_mb == 2048


def test_strategies_select_expected_models() -> None:
    assert route_task("summary").model_id == "qwen2.5-1.5b-q4"
    assert route_task("summary", budget_mb=2048).strategy == "budget"
    assert route_task("embedding").model_id == "bge-m3-int8"
    assert route_task("tagging").model_id == "local-rules"
    assert route_task("chat").model_id == "deepseek-chat"

    balanced = select_model("summary", "balanced", 2048)[0]
    assert balanced.id == "deepseek-r1-1.5b-q4"

    quality = select_model("summary", "quality", 2048)[0]
    assert quality.id == "deepseek-chat"


def test_budget_filters_candidates_and_falls_back_to_cloud() -> None:
    small = route_task("embedding", budget_mb=512)
    assert small.model_id == "bge-small-zh-v1.5"
    assert small.resident_mb == 300

    cloud_only = route_task("summary", budget_mb=1000)
    assert cloud_only.model_id == "deepseek-chat"
    assert cloud_only.within_budget is True


def test_manual_strategy_requires_candidate_and_budget() -> None:
    model, reason = select_model("summary", "manual", 2048, "qwen2.5-1.5b-q4")
    assert model.id == "qwen2.5-1.5b-q4"
    assert "人工指定" in reason

    with pytest.raises(RouteValidationError, match="必须指定 modelId"):
        select_model("summary", "manual", 2048, None)

    with pytest.raises(RouteValidationError, match="不是任务"):
        select_model("summary", "manual", 2048, "qwen2.5-3b-q4")

    with pytest.raises(RouteValidationError, match="超出预算"):
        select_model("summary", "manual", 1000, "qwen2.5-1.5b-q4")

    with pytest.raises(RouteValidationError, match="未知任务"):
        select_model("unknown", "budget", 2048, None)


def test_fallback_chain_excludes_selected_and_respects_budget() -> None:
    decision = route_task("summary")
    assert decision.model_id == "qwen2.5-1.5b-q4"
    assert decision.fallback_models == (
        "deepseek-chat",
        "deepseek-r1-1.5b-q4",
    )

    embedding = route_task("embedding")
    assert embedding.fallback_models == ("bge-small-zh-v1.5",)


def test_upgrade_candidates_include_eligible_and_budget_blocked() -> None:
    summary = upgrade_candidates("summary", "qwen2.5-1.5b-q4")
    eligible = {item.model.id for item in summary if item.eligible}
    blocked = {item.model.id for item in summary if not item.eligible}

    assert {"deepseek-chat", "deepseek-r1-1.5b-q4"} <= eligible
    assert {"qwen2.5-3b-q4", "qwen2.5-7b-q4"} <= blocked
    assert all("预算" in item.reason for item in summary if not item.eligible)

    embedding = upgrade_candidates("embedding", "bge-m3-int8")
    assert [item.model.id for item in embedding] == ["bge-m3-fp16"]
    assert embedding[0].eligible is False
    assert "2300" in embedding[0].reason


def test_summary_and_embedding_services_use_route_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import summarizer
    from app.services.embedding import EmbeddingService

    save_route_config("summary", "manual", "deepseek-chat")
    calls: list[str] = []

    def fake_ollama(text: str, max_chars: int) -> str:
        calls.append("ollama")
        return "本地摘要"

    def fake_deepseek(text: str, max_chars: int) -> str:
        calls.append("deepseek")
        return "云端摘要"

    monkeypatch.setattr(summarizer, "_summarize_with_ollama", fake_ollama)
    monkeypatch.setattr(summarizer, "_summarize_with_deepseek", fake_deepseek)

    result = summarizer.summarize_with_source("README 正文")
    assert result.source == "deepseek"
    assert result.model == "deepseek-chat"
    assert calls == ["deepseek"]

    save_route_config("embedding", "manual", "bge-small-zh-v1.5")
    service = EmbeddingService(force_fallback=True)
    assert service.model_name == "BAAI/bge-small-zh-v1.5"
    assert service.quantization == "fp32"
    assert service.budget_mb == 2048


def test_config_persists_and_merges_into_decision() -> None:
    config = save_route_config("summary", "manual", "deepseek-chat", "tester")
    assert config.model_id == "deepseek-chat"

    configs = load_route_configs()
    assert configs["summary"].strategy == "manual"
    decision = get_route_decision("summary")
    assert decision.model_id == "deepseek-chat"
    assert decision.strategy == "manual"
    assert decision.updated_by == "tester"


def test_overview_payload_reports_budget() -> None:
    payload = overview_payload()
    assert payload["taskCount"] == 6
    assert payload["budgetMb"] == 2048
    assert payload["peakResidentMb"] == 1300
    assert payload["withinBudget"] is True
    assert payload["localModelCount"] >= 5
    assert len(payload["models"]) == len(MODEL_ROUTING_CATALOG)
    assert all(task["withinBudget"] for task in payload["tasks"])


def test_api_list_update_reset_and_health(client: TestClient) -> None:
    listed = client.get("/api/model-routes")
    assert listed.status_code == 200
    body = listed.json()
    assert body["taskCount"] == 6
    assert {task["task"] for task in body["tasks"]} == set(TASK_KEYS)

    updated = client.put(
        "/api/model-routes/summary",
        json={"strategy": "manual", "modelId": "deepseek-chat", "updatedBy": "api-test"},
    )
    assert updated.status_code == 200
    assert updated.json()["modelId"] == "deepseek-chat"
    assert updated.json()["updatedBy"] == "api-test"

    persisted = client.get("/api/model-routes").json()
    summary = next(task for task in persisted["tasks"] if task["task"] == "summary")
    assert summary["modelId"] == "deepseek-chat"

    deleted = client.delete("/api/model-routes/summary")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == 1
    assert get_route_decision("summary").model_id == "qwen2.5-1.5b-q4"

    health = client.get("/api/model-routes/health")
    assert health.status_code == 200
    health_body = health.json()
    assert health_body["ollama"]["configured"] is False
    assert health_body["deepseek"]["configured"] is False
    assert "apiKey" not in health_body["deepseek"]


def test_api_rejects_invalid_task_and_manual_config(client: TestClient) -> None:
    missing = client.put(
        "/api/model-routes/nope",
        json={"strategy": "budget"},
    )
    assert missing.status_code == 404

    manual_without_model = client.put(
        "/api/model-routes/summary",
        json={"strategy": "manual"},
    )
    assert manual_without_model.status_code == 400
    assert "modelId" in manual_without_model.json()["detail"]

    not_candidate = client.put(
        "/api/model-routes/summary",
        json={"strategy": "manual", "modelId": "qwen2.5-3b-q4"},
    )
    assert not_candidate.status_code == 400
    assert "不是任务" in not_candidate.json()["detail"]


def test_api_rejects_over_budget_model(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        model_router,
        "get_settings",
        lambda: Settings(MODEL_BUDGET_MB=1000),
    )
    response = client.put(
        "/api/model-routes/summary",
        json={"strategy": "manual", "modelId": "qwen2.5-1.5b-q4"},
    )
    assert response.status_code == 400
    assert "超出预算" in response.json()["detail"]


def test_api_apply_upgrade_and_reset_all(client: TestClient) -> None:
    upgraded = client.post("/api/model-routes/upgrade", json={"task": "summary"})
    assert upgraded.status_code == 200
    body = upgraded.json()
    assert body["ok"] is True
    assert body["modelId"] == "deepseek-chat"
    assert body["route"]["strategy"] == "manual"

    no_upgrade = client.post("/api/model-routes/upgrade", json={"task": "embedding"})
    assert no_upgrade.status_code == 200
    assert no_upgrade.json()["ok"] is False

    reset = client.post("/api/model-routes/reset")
    assert reset.status_code == 200
    assert reset.json()["deleted"] >= 1
    assert get_route_decision("summary").model_id == "qwen2.5-1.5b-q4"
