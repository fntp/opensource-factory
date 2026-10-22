"""降级路径测试（REQ-202610-0927 / M3-09）。

全部用例离线执行：不加载真实模型、不访问网络。
覆盖「模型缺失 / 超预算 → hash 向量 / 截断摘要」两类降级，
以及自检服务、CLI 与内部接口。
"""
from __future__ import annotations

import json
import math

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.services.degradation import (
    TRUNCATED_PREFIX,
    _blocked_imports,
    check_embedding_fallback,
    check_embedding_model_missing,
    check_embedding_over_budget,
    check_summary_over_budget,
    check_summary_truncated,
    run_degradation_checks,
)
from app.services.embedding import FALLBACK_DIM, EmbeddingService
from app.services.summarizer import is_llm_over_budget, summarize, truncated_summary


def test_hash_fallback_is_deterministic_and_normalized() -> None:
    service = EmbeddingService(force_fallback=True)
    first = service.encode_one("开源项目工厂：GitHub 仓库智能推荐系统")
    second = EmbeddingService(force_fallback=True).encode_one(
        "开源项目工厂：GitHub 仓库智能推荐系统"
    )

    assert service.backend == "hash"
    assert service.degraded_reason == "forced"
    assert len(first) == FALLBACK_DIM
    assert abs(math.sqrt(sum(value * value for value in first)) - 1.0) < 1e-9
    assert first == second
    assert abs(service.cosine(first, second) - 1.0) < 1e-9


def test_model_missing_falls_back_to_hash() -> None:
    with _blocked_imports("sentence_transformers", "FlagEmbedding"):
        service = EmbeddingService(force_fallback=False)
        vector = service.encode_one("模型缺失时仍应返回可用向量")

    assert service.backend == "hash"
    assert service.degraded_reason.startswith("model_missing")
    assert len(vector) == FALLBACK_DIM


def test_over_budget_embedding_uses_hash_without_loading_model() -> None:
    service = EmbeddingService(model_name="BAAI/bge-m3", budget_mb=512)
    vector = service.encode_one("超预算模型不得加载")

    assert service.backend == "hash"
    assert service.degraded_reason.startswith("over_budget")
    assert "1100MB" in service.degraded_reason
    assert len(vector) == FALLBACK_DIM


def test_within_budget_does_not_trigger_budget_degradation() -> None:
    with _blocked_imports("sentence_transformers", "FlagEmbedding"):
        service = EmbeddingService(model_name="BAAI/bge-m3", budget_mb=2048)
        service.encode_one("预算内模型应继续尝试加载")

    # 依赖不可导入 → 仍是 model_missing，而不是 over_budget
    assert service.degraded_reason.startswith("model_missing")


def test_llm_budget_detection() -> None:
    over = Settings(OLLAMA_MODEL="qwen2.5:7b", MODEL_BUDGET_MB=2048)
    within = Settings(OLLAMA_MODEL="qwen2.5:1.5b-instruct-q4_K_M", MODEL_BUDGET_MB=2048)
    unknown = Settings(OLLAMA_MODEL="custom-model:latest", MODEL_BUDGET_MB=2048)

    assert is_llm_over_budget(over) is True
    assert is_llm_over_budget(within) is False
    assert is_llm_over_budget(unknown) is False  # 未收录模型不阻断


def test_truncated_summary_respects_max_chars() -> None:
    text = "开源项目工厂" * 100
    result = truncated_summary(text, max_chars=80)
    body = result.split("\n", 1)[1]

    assert result.startswith(TRUNCATED_PREFIX)
    assert len(body) == 80
    assert body == text[:80]


def test_summarize_without_llm_returns_truncated() -> None:
    settings = Settings(OLLAMA_BASE_URL="", DEEPSEEK_API_KEY="")
    from unittest import mock

    with mock.patch("app.services.summarizer.get_settings", return_value=settings):
        result = summarize("没有可用 LLM 时的摘要内容" * 40, max_chars=50)

    assert result.startswith(TRUNCATED_PREFIX)
    assert len(result.split("\n", 1)[1]) == 50


def test_summary_over_budget_skips_ollama_request() -> None:
    check = check_summary_over_budget()
    assert check.ok, check.detail


def test_individual_checks_all_pass() -> None:
    for check in (
        check_embedding_fallback(),
        check_embedding_model_missing(),
        check_embedding_over_budget(),
        check_summary_truncated(),
        check_summary_over_budget(),
    ):
        assert check.ok, check.detail


def test_report_all_pass() -> None:
    report = run_degradation_checks()

    assert report.ok, report.summary
    assert report.summary.startswith("PASS")
    assert len(report.checks) == 5
    assert report.budget_mb >= 1
    assert report.embedding_expected_backend == "hash"  # 测试环境强制 fallback


def test_cli_json_output(capsys) -> None:
    from app.degradation import main

    code = main(["check", "--json"])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["ok"] is True
    assert output["summary"].startswith("PASS")
    assert {item["name"] for item in output["checks"]} == {
        "embedding_hash_fallback",
        "embedding_model_missing",
        "embedding_over_budget",
        "summary_truncated",
        "summary_over_budget",
    }


def test_api_status_returns_report() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/degradation/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["embeddingExpectedBackend"] == "hash"
    assert len(body["checks"]) == 5
    assert all(item["ok"] for item in body["checks"])


def test_api_status_requires_internal_token_when_configured() -> None:
    from unittest import mock

    protected = mock.Mock()
    protected.INTERNAL_TOKEN = "test-internal-token"
    with mock.patch("app.security.get_settings", return_value=protected):
        with TestClient(app) as client:
            unauthorized = client.get("/api/degradation/status")
            authorized = client.get(
                "/api/degradation/status",
                headers={"X-Internal-Token": "test-internal-token"},
            )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
