"""快捷入口评估的离线测试（REQ-202610-0973 / M8-04）。

覆盖：权重口径、平台评分与排名、M8-05 API 就绪度、报告 / 契约渲染与 CLI。
全部用例不访问网络、不读写数据库、不依赖真实令牌。
"""
from __future__ import annotations

import json

import pytest

from app.services import quick_entry_eval as qe


def test_criteria_weights_sum_to_one() -> None:
    qe.validate_criteria()
    assert len(qe.CRITERIA) == 8
    assert sum(item.weight for item in qe.CRITERIA) == pytest.approx(1.0)
    assert all(item.weight > 0 for item in qe.CRITERIA)


def test_platform_catalog_scores_complete() -> None:
    keys = {item.key for item in qe.CRITERIA}
    assert len(qe.PLATFORMS) == 6
    for platform in qe.PLATFORMS:
        assert set(platform.scores) == keys, platform.id
        assert all(1 <= value <= 5 for value in platform.scores.values()), platform.id


def test_rank_platforms_order_and_ranks() -> None:
    ranked = qe.rank_platforms()
    assert [item.platform.id for item in ranked] == [
        "raycast",
        "shortcuts",
        "browser-omnibox",
        "vscode",
        "alfred",
        "utools",
    ]
    assert [item.rank for item in ranked] == [1, 2, 3, 4, 5, 6]
    scores = [item.weighted_score for item in ranked]
    assert scores == sorted(scores, reverse=True)


def test_weighted_score_matches_manual_calculation() -> None:
    raycast = next(item for item in qe.PLATFORMS if item.id == "raycast")
    result = qe.score_platform(raycast)
    assert result.weighted_score == pytest.approx(4.10)
    assert result.grade == "A"


def test_grade_uses_rounded_score_at_boundary() -> None:
    utools = next(item for item in qe.PLATFORMS if item.id == "utools")
    result = qe.score_platform(utools)
    assert result.weighted_score == pytest.approx(3.20)
    assert result.grade == "B-"


def test_unknown_ready_key_raises() -> None:
    with pytest.raises(ValueError, match="未知的 API 能力 key"):
        qe.assess_api_readiness(["token.issue", "not-a-real-key"])


def test_assess_api_readiness_defaults_to_blocked() -> None:
    statuses = qe.assess_api_readiness()
    assert len(statuses) == 16
    assert all(item.ready is False for item in statuses)
    readiness = [qe.platform_readiness(item.id, statuses) for item in qe.PLATFORMS]
    assert all(item.state == "blocked" for item in readiness)
    assert all(item.coverage == 0 for item in readiness)


def test_assess_api_readiness_all_ready() -> None:
    all_keys = [item.key for item in qe.API_REQUIREMENTS]
    statuses = qe.assess_api_readiness(all_keys)
    assert all(item.ready for item in statuses)
    for platform in qe.PLATFORMS:
        readiness = qe.platform_readiness(platform.id, statuses)
        assert readiness.state == "ready"
        assert readiness.coverage == 100
        assert readiness.missing == ()


def test_platform_readiness_reports_missing_capabilities() -> None:
    core = [item.key for item in qe.API_REQUIREMENTS if item.key in qe._CORE_KEYS]
    statuses = qe.assess_api_readiness(core)
    raycast = qe.platform_readiness("raycast", statuses)
    assert raycast.state == "blocked"
    assert raycast.missing == ("openapi", "deep_link")
    assert raycast.coverage == 87


def test_build_evaluation_phases_and_effort() -> None:
    evaluation = qe.build_evaluation(generated_at="2026-10-22")
    assert evaluation.generated_at == "2026-10-22"
    assert len(evaluation.phases) == 5
    assert evaluation.phases[0].id == "m8-05"
    expected = (
        sum(item.effort_days[0] for item in evaluation.phases),
        sum(item.effort_days[1] for item in evaluation.phases),
    )
    assert evaluation.total_effort_days == expected
    assert evaluation.primary == "raycast"
    assert evaluation.secondary == "shortcuts"
    assert evaluation.deferred == ("vscode", "alfred", "utools")


def test_build_evaluation_all_ready_summary() -> None:
    evaluation = qe.build_evaluation(ready_keys=[item.key for item in qe.API_REQUIREMENTS])
    assert "16/16" in evaluation.summary
    assert "Raycast" in evaluation.summary
    assert all(item.state == "ready" for item in evaluation.platform_readiness)


def test_render_markdown_contains_sections() -> None:
    text = qe.render_markdown(qe.build_evaluation(generated_at="2026-10-22"))
    assert "# 快捷入口评估" in text
    assert "## 1. 结论摘要" in text
    assert "## 5. M8-05 API 就绪度" in text
    assert "## 10. 复跑方式" in text
    assert "Raycast 扩展" in text
    assert "Apple 快捷指令" in text
    assert "quick-entry-api-contract.json" in text


def test_render_contract_schema_and_endpoints() -> None:
    contract = qe.render_contract(qe.build_evaluation(generated_at="2026-10-22"))
    assert contract["schema"] == "openfactory.quick-entry.v1"
    assert contract["version"] == 1
    endpoints = contract["endpoints"]
    assert isinstance(endpoints, list)
    assert len(endpoints) == 10
    assert {item["method"] for item in endpoints} >= {"GET", "POST", "DELETE"}
    paths = {item["path"] for item in endpoints}
    assert "/api/v1/search" in paths
    assert "/api/v1/bookmarks" in paths
    assert contract["security"]["rateLimits"]["read"] == "60/min"


def test_evaluation_to_dict() -> None:
    payload = qe.build_evaluation(generated_at="2026-10-22").to_dict()
    assert payload["schema"] == "openfactory.quick-entry-evaluation.v1"
    assert len(payload["platforms"]) == 6
    assert payload["platforms"][0]["id"] == "raycast"
    assert payload["recommendation"]["primary"] == "raycast"
    assert len(payload["apiRequirements"]) == 16


def test_cli_report_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert qe.main(["report", "--json", "--generated-at", "2026-10-22"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "openfactory.quick-entry-evaluation.v1"
    assert payload["generatedAt"] == "2026-10-22"


def test_cli_contract_writes_file(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "contract.json"
    assert qe.main(["contract", "--generated-at", "2026-10-22", "--out", str(target)]) == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema"] == "openfactory.quick-entry.v1"
    assert "已写入" in capsys.readouterr().out


def test_cli_invalid_ready_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert qe.main(["report", "--ready", "bogus.key"]) == 2
    captured = capsys.readouterr()
    assert "错误" in captured.err
    assert "bogus.key" in captured.err
