"""降级路径自检（REQ-202610-0927 / M3-09）。

覆盖两类故障，并保证检查本身**不加载真实模型、不访问网络**：

1. 模型缺失 / 超预算 → `EmbeddingService` 使用确定性 hash 向量（256 维、L2 归一化）；
2. LLM 不可用 / 超预算 → `summarize()` 返回截断原文（带降级说明）。

检查结果既可由 CLI（`python -m app.degradation check`）输出，也可由
`GET /api/degradation/status` 供部署后核对。
"""
from __future__ import annotations

import contextlib
import math
import sys
from dataclasses import asdict, dataclass
from typing import Iterator
from unittest import mock

from app.config import Settings, get_settings
from app.services.embedding import FALLBACK_DIM, EmbeddingService
from app.services.model_budget import (
    DEFAULT_BUDGET_MB,
    resolve_embedding_spec,
    resolve_llm_spec,
)
from app.services.summarizer import summarize, truncated_summary

TRUNCATED_PREFIX = "（LLM 暂不可用，以下为项目原文截断）"
_SAMPLE_TEXT = "开源项目工厂：GitHub 仓库智能推荐与个人开源资产管理"


@dataclass(frozen=True)
class DegradationCheck:
    """单项降级检查结果。"""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class DegradationReport:
    """降级路径自检报告。"""

    ok: bool
    summary: str
    embedding_model: str
    embedding_quantization: str
    embedding_expected_backend: str
    llm_model: str
    llm_degraded: bool
    budget_mb: int
    checks: tuple[DegradationCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@contextlib.contextmanager
def _blocked_imports(*module_names: str) -> Iterator[None]:
    """临时让指定模块不可导入（`sys.modules[name] = None` 会触发 ImportError）。"""
    missing = object()
    previous: dict[str, object] = {
        name: sys.modules.get(name, missing) for name in module_names
    }
    for name in module_names:
        sys.modules[name] = None  # type: ignore[assignment]
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value  # type: ignore[assignment]


def _is_unit_vector(vector: list[float]) -> bool:
    norm = math.sqrt(sum(value * value for value in vector))
    return abs(norm - 1.0) < 1e-9


def check_embedding_fallback() -> DegradationCheck:
    """强制 hash 兜底：维度、归一化、跨实例确定性与余弦合理性。"""
    service = EmbeddingService(force_fallback=True)
    first = service.encode_one(_SAMPLE_TEXT)
    second = EmbeddingService(force_fallback=True).encode_one(_SAMPLE_TEXT)
    same = service.cosine(first, second)
    ok = (
        service.backend == "hash"
        and service.degraded_reason == "forced"
        and len(first) == FALLBACK_DIM
        and _is_unit_vector(first)
        and first == second
        and abs(same - 1.0) < 1e-9
    )
    return DegradationCheck(
        name="embedding_hash_fallback",
        ok=ok,
        detail=(
            f"backend={service.backend} dim={len(first)} "
            f"cosine={same:.6f} reason={service.degraded_reason or '-'}"
        ),
    )


def check_embedding_model_missing() -> DegradationCheck:
    """真实模型依赖不可导入时，必须降级为 hash 而不是抛异常。"""
    with _blocked_imports("sentence_transformers", "FlagEmbedding"):
        service = EmbeddingService(force_fallback=False)
        vector = service.encode_one(_SAMPLE_TEXT)
        backend = service.backend
        reason = service.degraded_reason
    ok = (
        backend == "hash"
        and reason.startswith("model_missing")
        and len(vector) == FALLBACK_DIM
        and _is_unit_vector(vector)
    )
    return DegradationCheck(
        name="embedding_model_missing",
        ok=ok,
        detail=f"backend={backend} dim={len(vector)} reason={reason or '-'}",
    )


def check_embedding_over_budget() -> DegradationCheck:
    """超预算的 embedding 模型不得加载，直接使用 hash。"""
    service = EmbeddingService(model_name="BAAI/bge-m3", budget_mb=512)
    vector = service.encode_one(_SAMPLE_TEXT)
    backend = service.backend
    reason = service.degraded_reason
    ok = (
        backend == "hash"
        and reason.startswith("over_budget")
        and len(vector) == FALLBACK_DIM
        and _is_unit_vector(vector)
    )
    return DegradationCheck(
        name="embedding_over_budget",
        ok=ok,
        detail=f"backend={backend} budget={service.budget_mb}MB reason={reason or '-'}",
    )


def check_summary_truncated() -> DegradationCheck:
    """无 LLM 时返回截断原文，且正文不超过 max_chars。"""
    text = "开源项目工厂" * 100
    result = truncated_summary(text, max_chars=80)
    body = result.split("\n", 1)[1] if "\n" in result else ""
    ok = result.startswith(TRUNCATED_PREFIX) and len(body) == 80
    return DegradationCheck(
        name="summary_truncated",
        ok=ok,
        detail=f"prefix={'yes' if result.startswith(TRUNCATED_PREFIX) else 'no'} body={len(body)}",
    )


def check_summary_over_budget() -> DegradationCheck:
    """Ollama 模型超预算时跳过请求，直接走截断摘要。"""
    over_budget = Settings(
        OLLAMA_BASE_URL="http://127.0.0.1:9",
        OLLAMA_MODEL="qwen2.5:7b",
        MODEL_BUDGET_MB=2048,
        DEEPSEEK_API_KEY="",
    )
    text = "超预算摘要降级验证" * 50
    with mock.patch(
        "app.services.summarizer.get_settings", return_value=over_budget
    ), mock.patch(
        "app.services.summarizer.httpx.Client",
        side_effect=AssertionError("超预算时不应发起 Ollama 请求"),
    ):
        result = summarize(text, max_chars=60)
    ok = result.startswith(TRUNCATED_PREFIX) and len(result.split("\n", 1)[1]) == 60
    return DegradationCheck(
        name="summary_over_budget",
        ok=ok,
        detail=(
            f"ollama={over_budget.OLLAMA_MODEL} budget={over_budget.MODEL_BUDGET_MB}MB "
            f"truncated={'yes' if result.startswith(TRUNCATED_PREFIX) else 'no'}"
        ),
    )


def run_degradation_checks() -> DegradationReport:
    """执行全部降级检查并汇总报告（不抛异常）。"""
    settings = get_settings()
    budget_mb = int(settings.MODEL_BUDGET_MB or DEFAULT_BUDGET_MB)
    checks = (
        check_embedding_fallback(),
        check_embedding_model_missing(),
        check_embedding_over_budget(),
        check_summary_truncated(),
        check_summary_over_budget(),
    )

    embedding_spec = resolve_embedding_spec(
        settings.EMBEDDING_MODEL, settings.EMBEDDING_QUANTIZATION
    )
    llm_spec = resolve_llm_spec(settings.OLLAMA_MODEL)
    embedding_over_budget = (
        embedding_spec is not None and embedding_spec.resident_mb > budget_mb
    )
    embedding_expected = (
        "hash"
        if settings.EMBEDDING_FORCE_FALLBACK or embedding_over_budget
        else "model"
    )
    llm_over_budget = llm_spec is not None and llm_spec.resident_mb > budget_mb
    llm_degraded = llm_over_budget or not (settings.OLLAMA_BASE_URL or "").strip()

    ok = all(check.ok for check in checks)
    failed = [check.name for check in checks if not check.ok]
    summary = (
        "PASS：模型缺失 / 超预算均按预期降级（hash 向量 + 截断摘要）"
        if ok
        else f"FAIL：{', '.join(failed)}"
    )
    return DegradationReport(
        ok=ok,
        summary=summary,
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_quantization=settings.EMBEDDING_QUANTIZATION,
        embedding_expected_backend=embedding_expected,
        llm_model=settings.OLLAMA_MODEL,
        llm_degraded=llm_degraded,
        budget_mb=budget_mb,
        checks=checks,
    )
