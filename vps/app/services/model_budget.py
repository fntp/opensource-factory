"""模型选型与 2G 推理预算校验（REQ-202610-0919 / M3-01）。

本模块只依赖标准库，便于在未安装应用依赖、甚至未创建虚拟环境的部署机上运行：

    cd vps
    python -m app.model_budget check
    python -m app.model_budget check --probe      # 额外探测本机 Ollama /api/ps
    python -m app.model_budget check --json

预算口径（见 docs/planning/resource-plan.md §3）：

- 同一时刻仅加载 1 个模型（摘要与向量化任务分队列串行）；
- 因此约束的是**峰值驻留** ``max(embedding, llm) <= MODEL_BUDGET_MB``，
  而不是两个模型驻留之和；
- 估算值来自模型权重 + 运行时开销，M5-06 资源实测时按实际 RSS 复核。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any, Literal, Sequence

DEFAULT_BUDGET_MB = 2048

# bge-m3 的 int8 口径：ONNX int8 / PyTorch 动态量化 / Ollama q8 均视为量化版本
_INT8_ALIASES = frozenset({"int8", "q8", "q8_0", "onnx-int8", "onnx_int8", "int8-dynamic"})
_FP16_ALIASES = frozenset({"fp16", "float16", "half"})

# 参数规模匹配（避免 17b 被误判为 7b）
_SIZE_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)b(?![\d.])")

ModelKind = Literal["embedding", "llm"]


@dataclass(frozen=True)
class ModelSpec:
    """单个候选模型的预算规格。"""

    id: str
    name: str
    kind: ModelKind
    quantization: str
    resident_mb: int
    disk_mb: int
    dimension: int | None = None
    parameters_b: float | None = None
    note: str = ""


@dataclass(frozen=True)
class BudgetItem:
    """一个角色（embedding / llm）的校验结果。"""

    role: str
    configured_name: str
    model_id: str | None
    quantization: str | None
    resident_mb: int | None
    disk_mb: int | None
    dimension: int | None
    within_budget: bool
    message: str


@dataclass(frozen=True)
class BudgetReport:
    """完整的离线预算报告。"""

    budget_mb: int
    items: tuple[BudgetItem, ...]
    peak_resident_mb: int
    total_resident_mb: int
    verified: bool
    budget_ok: bool
    summary: str


@dataclass(frozen=True)
class LoadedModel:
    """Ollama /api/ps 返回的已加载模型。"""

    name: str
    size_mb: int
    size_vram_mb: int
    within_budget: bool


@dataclass(frozen=True)
class ProbeResult:
    """Ollama 实时探测结果。"""

    reachable: bool
    models: tuple[LoadedModel, ...]
    peak_resident_mb: int
    budget_ok: bool
    error: str = ""


# 选型表：数值与 resource-plan §3 保持一致；改动需同步文档与测试。
MODEL_CATALOG: dict[str, ModelSpec] = {
    "bge-m3-int8": ModelSpec(
        id="bge-m3-int8",
        name="BAAI/bge-m3",
        kind="embedding",
        quantization="int8",
        resident_mb=1100,
        disk_mb=1200,
        dimension=1024,
        parameters_b=0.568,
        note="首选；ONNX int8 / 动态量化，fp16 约 2.3G 超预算",
    ),
    "bge-m3-fp16": ModelSpec(
        id="bge-m3-fp16",
        name="BAAI/bge-m3",
        kind="embedding",
        quantization="fp16",
        resident_mb=2300,
        disk_mb=2300,
        dimension=1024,
        parameters_b=0.568,
        note="超预算，仅按需人工启用",
    ),
    "bge-small-zh-v1.5": ModelSpec(
        id="bge-small-zh-v1.5",
        name="BAAI/bge-small-zh-v1.5",
        kind="embedding",
        quantization="fp32",
        resident_mb=300,
        disk_mb=100,
        dimension=512,
        parameters_b=0.024,
        note="降级模型；模型缺失 / 超预算时切换",
    ),
    "qwen2.5-1.5b-q4": ModelSpec(
        id="qwen2.5-1.5b-q4",
        name="qwen2.5:1.5b-instruct-q4_K_M",
        kind="llm",
        quantization="q4_K_M",
        resident_mb=1300,
        disk_mb=1000,
        parameters_b=1.5,
        note="默认摘要模型；≤2B 量化",
    ),
    "deepseek-r1-1.5b-q4": ModelSpec(
        id="deepseek-r1-1.5b-q4",
        name="deepseek-r1:1.5b",
        kind="llm",
        quantization="q4_K_M",
        resident_mb=1400,
        disk_mb=1100,
        parameters_b=1.5,
        note="备选摘要模型；推理型，较慢",
    ),
    "qwen2.5-3b-q4": ModelSpec(
        id="qwen2.5-3b-q4",
        name="qwen2.5:3b-instruct-q4_K_M",
        kind="llm",
        quantization="q4_K_M",
        resident_mb=2200,
        disk_mb=1900,
        parameters_b=3.0,
        note="超过 2B 口径且超预算",
    ),
    "qwen2.5-7b-q4": ModelSpec(
        id="qwen2.5-7b-q4",
        name="qwen2.5:7b",
        kind="llm",
        quantization="q4_K_M",
        resident_mb=4700,
        disk_mb=4700,
        parameters_b=7.0,
        note="旧默认；超预算，仅按需人工启用",
    ),
}


def _normalize_name(name: str) -> str:
    """归一化模型名：小写、空格 / 下划线转连字符。"""
    return re.sub(r"[\s_]+", "-", (name or "").strip().lower())


def _is_int8(quantization: str) -> bool:
    return (quantization or "").strip().lower() in _INT8_ALIASES


def resolve_embedding_spec(
    model_name: str, quantization: str = "int8"
) -> ModelSpec | None:
    """按模型名 + 量化口径解析 embedding 规格；未收录返回 None。"""
    normalized = _normalize_name(model_name)
    if "bge-m3" in normalized or "bgem3" in normalized:
        return MODEL_CATALOG["bge-m3-int8" if _is_int8(quantization) else "bge-m3-fp16"]
    if "bge-small-zh" in normalized:
        return MODEL_CATALOG["bge-small-zh-v1.5"]
    return None


def resolve_llm_spec(model_name: str) -> ModelSpec | None:
    """按模型名解析 Ollama LLM 规格；未收录返回 None。"""
    normalized = _normalize_name(model_name)

    if "qwen2.5" in normalized or "qwen2-5" in normalized:
        match = _SIZE_RE.search(normalized)
        if not match:
            return None
        size = float(match.group(1))
        if size <= 1.6:
            return MODEL_CATALOG["qwen2.5-1.5b-q4"]
        if size <= 3.1:
            return MODEL_CATALOG["qwen2.5-3b-q4"]
        if size <= 7.1:
            return MODEL_CATALOG["qwen2.5-7b-q4"]
        return None

    if "deepseek-r1" in normalized:
        match = _SIZE_RE.search(normalized)
        if match and float(match.group(1)) <= 1.6:
            return MODEL_CATALOG["deepseek-r1-1.5b-q4"]
    return None


def _item_for(role: str, configured: str, spec: ModelSpec | None, budget_mb: int) -> BudgetItem:
    if spec is None:
        return BudgetItem(
            role=role,
            configured_name=configured or "（未配置）",
            model_id=None,
            quantization=None,
            resident_mb=None,
            disk_mb=None,
            dimension=None,
            within_budget=False,
            message="未收录的模型，无法验证内存预算；请先登记到 MODEL_CATALOG",
        )

    within = spec.resident_mb <= budget_mb
    if within:
        percent = round(spec.resident_mb / budget_mb * 100)
        message = f"预算内（占上限 {percent}%）"
    else:
        message = f"超出预算（{spec.resident_mb} MB > {budget_mb} MB）"
    return BudgetItem(
        role=role,
        configured_name=configured,
        model_id=spec.id,
        quantization=spec.quantization,
        resident_mb=spec.resident_mb,
        disk_mb=spec.disk_mb,
        dimension=spec.dimension,
        within_budget=within,
        message=message,
    )


def build_model_budget_report(
    embedding_model: str,
    ollama_model: str,
    embedding_quantization: str = "int8",
    budget_mb: int = DEFAULT_BUDGET_MB,
) -> BudgetReport:
    """构建离线预算报告（纯函数，不访问网络）。"""
    budget = max(1, int(budget_mb or DEFAULT_BUDGET_MB))
    embedding_spec = resolve_embedding_spec(embedding_model, embedding_quantization)
    llm_spec = resolve_llm_spec(ollama_model)

    items = (
        _item_for("embedding", embedding_model, embedding_spec, budget),
        _item_for("llm", ollama_model, llm_spec, budget),
    )
    known = [item.resident_mb for item in items if item.resident_mb is not None]
    peak = max(known, default=0)
    total = sum(known)
    verified = all(item.model_id is not None for item in items)
    budget_ok = verified and all(item.within_budget for item in items) and peak <= budget

    if budget_ok:
        percent = round(peak / budget * 100)
        summary = f"PASS：峰值驻留 {peak} MB / {budget} MB（{percent}%）"
    else:
        reasons = [f"{item.role}：{item.message}" for item in items if not item.within_budget]
        summary = "FAIL：" + "；".join(reasons)

    return BudgetReport(
        budget_mb=budget,
        items=items,
        peak_resident_mb=peak,
        total_resident_mb=total,
        verified=verified,
        budget_ok=budget_ok,
        summary=summary,
    )


def probe_ollama(
    base_url: str,
    budget_mb: int = DEFAULT_BUDGET_MB,
    *,
    timeout: float = 3.0,
    transport: Any = None,
) -> ProbeResult:
    """探测 Ollama ``/api/ps`` 中实际加载的模型（不访问网络时由调用方注入 transport）。

    不可达 / 返回异常时返回 ``reachable=False``，不抛异常；是否视为失败由调用方决定。
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ProbeResult(False, (), 0, False, "未配置 OLLAMA_BASE_URL")

    try:
        import httpx

        with httpx.Client(timeout=timeout, transport=transport) as client:
            resp = client.get(f"{base}/api/ps")
        resp.raise_for_status()
        payload = resp.json() or {}
    except Exception as exc:  # noqa: BLE001 - 探测失败属于预期降级路径
        return ProbeResult(False, (), 0, False, f"Ollama 不可达：{exc}")

    budget = max(1, int(budget_mb or DEFAULT_BUDGET_MB))
    models: list[LoadedModel] = []
    for raw in payload.get("models") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("model") or "unknown")
        size_mb = int(raw.get("size") or 0) // (1024 * 1024)
        vram_mb = int(raw.get("size_vram") or 0) // (1024 * 1024)
        models.append(
            LoadedModel(
                name=name,
                size_mb=size_mb,
                size_vram_mb=vram_mb,
                within_budget=size_mb <= budget,
            )
        )

    peak = max((item.size_mb for item in models), default=0)
    return ProbeResult(
        reachable=True,
        models=tuple(models),
        peak_resident_mb=peak,
        budget_ok=all(item.within_budget for item in models),
    )


def _format_item(item: BudgetItem) -> str:
    state = "PASS" if item.within_budget else "FAIL"
    if item.model_id is None:
        return f"[{state}] {item.role:<9} {item.configured_name}  {item.message}"
    quantization = f" [{item.quantization}]" if item.quantization else ""
    dimension = f" / {item.dimension} 维" if item.dimension else ""
    return (
        f"[{state}] {item.role:<9} {item.configured_name}{quantization}  "
        f"{item.resident_mb} MB / 磁盘 {item.disk_mb} MB{dimension}  {item.message}"
    )


def _render_text(report: BudgetReport, probe: ProbeResult | None) -> str:
    lines = [
        f"模型预算校验（上限 {report.budget_mb} MB，同一时刻仅加载 1 个模型）",
        *(_format_item(item) for item in report.items),
        f"峰值驻留：{report.peak_resident_mb} MB / {report.budget_mb} MB"
        f"（合计 {report.total_resident_mb} MB，仅作参考）",
        f"结论：{report.summary}",
    ]
    if probe is not None:
        lines.append("")
        lines.append("Ollama 实时探测（/api/ps）：")
        if not probe.reachable:
            lines.append(f"[FAIL] {probe.error}")
        elif not probe.models:
            lines.append("[PASS] 当前未加载模型（0 MB）")
        else:
            for model in probe.models:
                state = "PASS" if model.within_budget else "FAIL"
                lines.append(
                    f"[{state}] {model.name}  {model.size_mb} MB"
                    f"（VRAM {model.size_vram_mb} MB）"
                )
            lines.append(f"峰值驻留：{probe.peak_resident_mb} MB / {report.budget_mb} MB")
        lines.append(f"探测结论：{'PASS' if probe.budget_ok else 'FAIL'}")
    return "\n".join(lines)


def _load_settings() -> Any:
    """延迟导入 Settings，避免模块导入时依赖 pydantic。"""
    from app.config import get_settings

    return get_settings()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.model_budget",
        description="OpenFactory 模型选型与 2G 推理预算校验",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="校验当前配置的模型预算")
    check.add_argument("--embedding-model", default=None, help="覆盖 EMBEDDING_MODEL")
    check.add_argument("--ollama-model", default=None, help="覆盖 OLLAMA_MODEL")
    check.add_argument(
        "--embedding-quantization", default=None, help="覆盖 EMBEDDING_QUANTIZATION"
    )
    check.add_argument("--budget-mb", type=int, default=None, help="覆盖 MODEL_BUDGET_MB")
    check.add_argument("--probe", action="store_true", help="额外探测本机 Ollama /api/ps")
    check.add_argument("--json", action="store_true", help="以 JSON 输出")

    args = parser.parse_args(argv)

    settings = _load_settings()
    embedding_model = args.embedding_model or settings.EMBEDDING_MODEL
    ollama_model = args.ollama_model or settings.OLLAMA_MODEL
    quantization = args.embedding_quantization or settings.EMBEDDING_QUANTIZATION
    budget_mb = args.budget_mb or settings.MODEL_BUDGET_MB

    report = build_model_budget_report(
        embedding_model=embedding_model,
        ollama_model=ollama_model,
        embedding_quantization=quantization,
        budget_mb=budget_mb,
    )
    probe = (
        probe_ollama(settings.OLLAMA_BASE_URL, budget_mb=budget_mb)
        if args.probe
        else None
    )

    if args.json:
        payload: dict[str, Any] = {"report": asdict(report), "probe": asdict(probe) if probe else None}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render_text(report, probe))

    ok = report.budget_ok and (probe is None or probe.budget_ok)
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    sys.exit(main())
