"""模型选型与 2G 预算校验测试（REQ-202610-0919）。

全部用例离线执行：实时探测使用 ``httpx.MockTransport``，不访问本机 Ollama。
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.config import Settings
from app.runtime import REQUIRED_ENV_KEYS, SUBDIRS, check_runtime, parse_env_file
from app.services.model_budget import (
    DEFAULT_BUDGET_MB,
    build_model_budget_report,
    main,
    probe_ollama,
    resolve_embedding_spec,
    resolve_llm_spec,
)

ROOT = Path(__file__).resolve().parents[2]


def _defaults() -> tuple[str, str, str, int]:
    fields = Settings.model_fields
    return (
        str(fields["EMBEDDING_MODEL"].default),
        str(fields["OLLAMA_MODEL"].default),
        str(fields["EMBEDDING_QUANTIZATION"].default),
        int(fields["MODEL_BUDGET_MB"].default),
    )


def test_default_selection_fits_2g_budget() -> None:
    embedding, llm, quantization, budget = _defaults()
    report = build_model_budget_report(embedding, llm, quantization, budget)

    assert report.verified
    assert report.budget_ok, report.summary
    assert report.peak_resident_mb == 1300
    assert report.peak_resident_mb <= budget


def test_legacy_qwen_7b_is_rejected() -> None:
    report = build_model_budget_report("BAAI/bge-m3", "qwen2.5:7b", "int8")

    assert not report.budget_ok
    llm_item = next(item for item in report.items if item.role == "llm")
    assert llm_item.model_id == "qwen2.5-7b-q4"
    assert llm_item.resident_mb == 4700
    assert not llm_item.within_budget
    assert "FAIL" in report.summary


def test_bge_m3_fp16_is_rejected_but_int8_passes() -> None:
    fp16 = build_model_budget_report("BAAI/bge-m3", "qwen2.5:1.5b-instruct-q4_K_M", "fp16")
    int8 = build_model_budget_report("BAAI/bge-m3", "qwen2.5:1.5b-instruct-q4_K_M", "int8")

    assert not fp16.budget_ok
    assert fp16.items[0].resident_mb == 2300
    assert int8.budget_ok
    assert int8.items[0].resident_mb == 1100


def test_bge_small_fallback_fits_budget() -> None:
    report = build_model_budget_report(
        "BAAI/bge-small-zh-v1.5", "qwen2.5:1.5b-instruct-q4_K_M", "fp32"
    )
    assert report.budget_ok
    assert report.peak_resident_mb == 1300


def test_unknown_models_are_not_verifiable() -> None:
    report = build_model_budget_report("custom/unknown-model", "custom:1b", "int8")

    assert not report.verified
    assert not report.budget_ok
    assert all(item.model_id is None for item in report.items)


def test_resolve_model_specs() -> None:
    assert resolve_embedding_spec("BAAI/bge-m3", "int8").id == "bge-m3-int8"  # type: ignore[union-attr]
    assert resolve_embedding_spec("BAAI/bge-m3", "fp16").id == "bge-m3-fp16"  # type: ignore[union-attr]
    assert resolve_embedding_spec("BAAI/bge-small-zh-v1.5", "fp32").id == "bge-small-zh-v1.5"  # type: ignore[union-attr]
    assert resolve_embedding_spec("other/model", "int8") is None

    assert resolve_llm_spec("qwen2.5:1.5b-instruct-q4_K_M").id == "qwen2.5-1.5b-q4"  # type: ignore[union-attr]
    assert resolve_llm_spec("qwen2.5:3b-instruct-q4_K_M").id == "qwen2.5-3b-q4"  # type: ignore[union-attr]
    assert resolve_llm_spec("qwen2.5:7b").id == "qwen2.5-7b-q4"  # type: ignore[union-attr]
    assert resolve_llm_spec("qwen2.5:14b") is None
    assert resolve_llm_spec("deepseek-r1:1.5b").id == "deepseek-r1-1.5b-q4"  # type: ignore[union-attr]


def test_env_templates_use_budgeted_defaults() -> None:
    embedding, llm, quantization, budget = _defaults()
    for relative in ("vps/.env.example", "deploy/env/openfactory.env.example"):
        env = parse_env_file(ROOT / relative)
        assert env["EMBEDDING_MODEL"] == embedding, relative
        assert env["OLLAMA_MODEL"] == llm, relative
        assert env["EMBEDDING_QUANTIZATION"] == quantization, relative
        assert int(env["MODEL_BUDGET_MB"]) == budget, relative

        report = build_model_budget_report(
            env["EMBEDDING_MODEL"], env["OLLAMA_MODEL"], env["EMBEDDING_QUANTIZATION"], budget
        )
        assert report.budget_ok, f"{relative}: {report.summary}"


def test_cli_json_reports_pass(capsys) -> None:
    assert main(["check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["budget_ok"] is True
    assert payload["report"]["peak_resident_mb"] == 1300
    assert payload["probe"] is None


def test_cli_over_budget_exit_code(capsys) -> None:
    assert main(["check", "--ollama-model", "qwen2.5:7b"]) == 1
    output = capsys.readouterr().out
    assert "FAIL" in output
    assert "4700" in output


def _ps_payload(*models: tuple[str, int]) -> dict:
    return {
        "models": [
            {"name": name, "size": size_mb * 1024 * 1024, "size_vram": 0}
            for name, size_mb in models
        ]
    }


def test_probe_ollama_reads_loaded_models() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json=_ps_payload(("qwen2.5:1.5b-instruct-q4_K_M", 1300))
        )
    )
    result = probe_ollama("http://127.0.0.1:11434", transport=transport)

    assert result.reachable
    assert result.budget_ok
    assert result.peak_resident_mb == 1300
    assert result.models[0].name == "qwen2.5:1.5b-instruct-q4_K_M"


def test_probe_ollama_flags_oversized_loaded_model() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=_ps_payload(("qwen2.5:7b", 4700)))
    )
    result = probe_ollama("http://127.0.0.1:11434", transport=transport)

    assert result.reachable
    assert not result.budget_ok
    assert result.peak_resident_mb == 4700


def test_probe_ollama_unreachable_is_not_an_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = probe_ollama("http://127.0.0.1:11434", transport=httpx.MockTransport(handler))

    assert not result.reachable
    assert "不可达" in result.error
    assert not result.budget_ok


def test_probe_ollama_without_base_url() -> None:
    result = probe_ollama("")
    assert not result.reachable
    assert "OLLAMA_BASE_URL" in result.error


def _write_runtime_env(home: Path, overrides: dict[str, str] | None = None) -> None:
    home.mkdir(mode=0o700)
    for name in SUBDIRS:
        (home / name).mkdir(parents=True, exist_ok=True)
    values = {key: "placeholder-value" for key in REQUIRED_ENV_KEYS}
    values.update(
        {
            "EMBEDDING_MODEL": "BAAI/bge-m3",
            "EMBEDDING_QUANTIZATION": "int8",
            "EMBEDDING_DEVICE": "cpu",
            "OLLAMA_MODEL": "qwen2.5:1.5b-instruct-q4_K_M",
            "MODEL_BUDGET_MB": str(DEFAULT_BUDGET_MB),
            "INTERNAL_TOKEN": "a" * 64,
            "CORS_ORIGINS": "http://localhost:5173",
            "REDIS_URL": "redis://127.0.0.1:6379/0",
        }
    )
    if overrides:
        values.update(overrides)
    env_path = home / ".env"
    env_path.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n", encoding="utf-8")
    env_path.chmod(0o600)


def _by_name(results):
    return {item.name: item for item in results}


def test_runtime_check_passes_budgeted_models(tmp_path: Path) -> None:
    home = tmp_path / "openfactory"
    _write_runtime_env(home)
    results = _by_name(check_runtime(home))
    assert results["model_budget"].ok, results["model_budget"].detail


def test_runtime_check_flags_legacy_model(tmp_path: Path) -> None:
    home = tmp_path / "openfactory"
    _write_runtime_env(home, {"OLLAMA_MODEL": "qwen2.5:7b"})
    results = _by_name(check_runtime(home))
    assert not results["model_budget"].ok
    assert "4700" in results["model_budget"].detail
