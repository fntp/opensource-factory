"""模型路由与升级（REQ-202610-0965 / M7-06）。

在 M3-01 的全局模型选型之上，为不同任务（摘要 / 向量 / 打标 / 分类 / 问答 / 精排）
提供可持久化的模型路由：

- 任务级配置存于 ``model_route_configs``，缺省走内置默认；
- 四种策略：``budget``（预算优先）、``balanced``（均衡）、``quality``（质量优先）、
  ``manual``（人工指定）；
- 任何路由结果都必须满足 ``resident_mb <= MODEL_BUDGET_MB``；
- 升级建议只提示，不自动切换；应用升级必须显式调用接口。

模块不访问网络；Ollama 实时探测由 ``model_budget.probe_ollama`` 负责。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from app.config import get_settings
from app.services.model_budget import DEFAULT_BUDGET_MB, probe_ollama

logger = logging.getLogger(__name__)

TaskKey = Literal["summary", "embedding", "tagging", "classification", "chat", "rerank"]
StrategyKey = Literal["budget", "balanced", "quality", "manual"]
ProviderKey = Literal["ollama", "deepseek", "rules"]

VALID_STRATEGIES: tuple[str, ...] = ("budget", "balanced", "quality", "manual")
TASK_KEYS: tuple[str, ...] = (
    "summary",
    "embedding",
    "tagging",
    "classification",
    "chat",
    "rerank",
)

# 配置缓存：多进程部署时靠短 TTL 收敛；本进程写入会立即失效。
_CONFIG_CACHE: tuple[float, dict[str, "RouteConfig"]] | None = None
_CONFIG_TTL_SECONDS = 10.0


def _utcnow() -> datetime:
    """统一使用无时区 UTC 时间（与项目其他表一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RouteValidationError(ValueError):
    """路由配置非法（未知任务 / 策略 / 候选 / 超预算）。"""


@dataclass(frozen=True)
class RouteModel:
    """参与路由的模型目录项。"""

    id: str
    name: str
    provider: ProviderKey
    kind: Literal["llm", "embedding", "rules"]
    quality: int
    cost_per_1k: float
    latency_ms: int
    resident_mb: int
    quantization: str = ""
    dimension: int | None = None
    context_tokens: int = 8192
    note: str = ""


@dataclass(frozen=True)
class TaskSpec:
    """任务定义与候选模型。"""

    key: str
    label: str
    description: str
    default_strategy: str
    default_model_id: str
    candidates: tuple[str, ...]
    upgrade_kinds: tuple[str, ...] = ("llm",)


@dataclass(frozen=True)
class RouteConfig:
    """任务级路由覆盖配置。"""

    task: str
    strategy: str
    model_id: str | None = None
    updated_by: str = ""
    updated_at: datetime | None = None


@dataclass(frozen=True)
class RouteDecision:
    """单个任务的路由结果。"""

    task: str
    label: str
    description: str
    strategy: str
    model_id: str
    model_name: str
    provider: str
    kind: str
    quality: int
    cost_per_1k: float
    latency_ms: int
    resident_mb: int
    quantization: str
    dimension: int | None
    budget_mb: int
    within_budget: bool
    reason: str
    fallback_models: tuple[str, ...]
    updated_by: str = ""
    updated_at: datetime | None = None


@dataclass(frozen=True)
class UpgradeCandidate:
    """升级建议（eligible=False 时说明被预算 / 延迟阻塞的原因）。"""

    model: RouteModel
    eligible: bool
    reason: str


# 目录中的质量分 / 延迟 / 成本均为工程估算，用于路由排序与展示，不做账单依据。
MODEL_ROUTING_CATALOG: dict[str, RouteModel] = {
    "local-rules": RouteModel(
        id="local-rules",
        name="本地规则引擎",
        provider="rules",
        kind="rules",
        quality=45,
        cost_per_1k=0.0,
        latency_ms=5,
        resident_mb=0,
        quantization="none",
        note="零成本、零模型驻留；打标 / 分类默认",
    ),
    "local-heuristic": RouteModel(
        id="local-heuristic",
        name="本地启发式精排",
        provider="rules",
        kind="rules",
        quality=40,
        cost_per_1k=0.0,
        latency_ms=20,
        resident_mb=0,
        quantization="none",
        note="为 M7-07 精排预留；当前不调用 LLM",
    ),
    "bge-m3-int8": RouteModel(
        id="bge-m3-int8",
        name="BAAI/bge-m3",
        provider="ollama",
        kind="embedding",
        quality=92,
        cost_per_1k=0.0,
        latency_ms=60,
        resident_mb=1100,
        quantization="int8",
        dimension=1024,
        note="默认向量模型；1024 维",
    ),
    "bge-small-zh-v1.5": RouteModel(
        id="bge-small-zh-v1.5",
        name="BAAI/bge-small-zh-v1.5",
        provider="ollama",
        kind="embedding",
        quality=78,
        cost_per_1k=0.0,
        latency_ms=25,
        resident_mb=300,
        quantization="fp32",
        dimension=512,
        note="低配降级；512 维，切换需重建向量索引",
    ),
    "bge-m3-fp16": RouteModel(
        id="bge-m3-fp16",
        name="BAAI/bge-m3",
        provider="ollama",
        kind="embedding",
        quality=93,
        cost_per_1k=0.0,
        latency_ms=80,
        resident_mb=2300,
        quantization="fp16",
        dimension=1024,
        note="超出 2G 预算，仅作为升级阻塞提示",
    ),
    "qwen2.5-1.5b-q4": RouteModel(
        id="qwen2.5-1.5b-q4",
        name="qwen2.5:1.5b-instruct-q4_K_M",
        provider="ollama",
        kind="llm",
        quality=72,
        cost_per_1k=0.0,
        latency_ms=1200,
        resident_mb=1300,
        quantization="q4_K_M",
        context_tokens=32768,
        note="默认本地摘要模型；≤2B 量化",
    ),
    "deepseek-r1-1.5b-q4": RouteModel(
        id="deepseek-r1-1.5b-q4",
        name="deepseek-r1:1.5b",
        provider="ollama",
        kind="llm",
        quality=78,
        cost_per_1k=0.0,
        latency_ms=2600,
        resident_mb=1400,
        quantization="q4_K_M",
        context_tokens=65536,
        note="本地推理型备选；质量略高但更慢",
    ),
    "deepseek-chat": RouteModel(
        id="deepseek-chat",
        name="deepseek-chat",
        provider="deepseek",
        kind="llm",
        quality=90,
        cost_per_1k=0.001,
        latency_ms=1800,
        resident_mb=0,
        quantization="cloud",
        context_tokens=65536,
        note="云端模型；需要 DEEPSEEK_API_KEY，按量计费",
    ),
    "qwen2.5-3b-q4": RouteModel(
        id="qwen2.5-3b-q4",
        name="qwen2.5:3b-instruct-q4_K_M",
        provider="ollama",
        kind="llm",
        quality=82,
        cost_per_1k=0.0,
        latency_ms=2200,
        resident_mb=2200,
        quantization="q4_K_M",
        context_tokens=32768,
        note="超过 2G 预算，仅作为升级阻塞提示",
    ),
    "qwen2.5-7b-q4": RouteModel(
        id="qwen2.5-7b-q4",
        name="qwen2.5:7b",
        provider="ollama",
        kind="llm",
        quality=88,
        cost_per_1k=0.0,
        latency_ms=5000,
        resident_mb=4700,
        quantization="q4_K_M",
        context_tokens=32768,
        note="旧默认；超出预算，仅作为升级阻塞提示",
    ),
}

TASK_SPECS: dict[str, TaskSpec] = {
    "summary": TaskSpec(
        key="summary",
        label="摘要生成",
        description="README 摘要：本地优先，云端作为质量升级",
        default_strategy="budget",
        default_model_id="qwen2.5-1.5b-q4",
        candidates=("qwen2.5-1.5b-q4", "deepseek-r1-1.5b-q4", "deepseek-chat"),
        upgrade_kinds=("llm",),
    ),
    "embedding": TaskSpec(
        key="embedding",
        label="向量化",
        description="BGE-M3 默认；切换小模型会改变向量维度",
        default_strategy="quality",
        default_model_id="bge-m3-int8",
        candidates=("bge-m3-int8", "bge-small-zh-v1.5"),
        upgrade_kinds=("embedding",),
    ),
    "tagging": TaskSpec(
        key="tagging",
        label="自动打标",
        description="规则引擎零成本；LLM 为增强选项",
        default_strategy="budget",
        default_model_id="local-rules",
        candidates=("local-rules", "qwen2.5-1.5b-q4", "deepseek-chat"),
        upgrade_kinds=("llm",),
    ),
    "classification": TaskSpec(
        key="classification",
        label="自动分类",
        description="规则引擎零成本；LLM 为增强选项",
        default_strategy="budget",
        default_model_id="local-rules",
        candidates=("local-rules", "qwen2.5-1.5b-q4", "deepseek-chat"),
        upgrade_kinds=("llm",),
    ),
    "chat": TaskSpec(
        key="chat",
        label="问答检索",
        description="质量优先；云端未配置时运行期降级本地",
        default_strategy="quality",
        default_model_id="deepseek-chat",
        candidates=("deepseek-chat", "qwen2.5-1.5b-q4", "deepseek-r1-1.5b-q4"),
        upgrade_kinds=("llm",),
    ),
    "rerank": TaskSpec(
        key="rerank",
        label="精排",
        description="为 M7-07 预留的路由位；当前使用本地启发式",
        default_strategy="budget",
        default_model_id="local-heuristic",
        candidates=("local-heuristic", "qwen2.5-1.5b-q4", "deepseek-chat"),
        upgrade_kinds=("llm",),
    ),
}


def get_model(model_id: str) -> RouteModel | None:
    """按 id 取目录模型。"""
    return MODEL_ROUTING_CATALOG.get(model_id)


def _budget_value(budget_mb: int | None) -> int:
    settings = get_settings()
    value = budget_mb if budget_mb is not None else settings.MODEL_BUDGET_MB
    return max(1, int(value or DEFAULT_BUDGET_MB))


def current_budget_mb() -> int:
    """当前进程的推理内存预算（MB）。"""
    return _budget_value(None)


def _validate_task(task: str) -> TaskSpec:
    spec = TASK_SPECS.get(task)
    if spec is None:
        raise RouteValidationError(
            f"未知任务 {task!r}；可选值：{', '.join(TASK_KEYS)}"
        )
    return spec


def _validate_strategy(strategy: str) -> str:
    normalized = (strategy or "").strip().lower()
    if normalized not in VALID_STRATEGIES:
        raise RouteValidationError(
            f"未知策略 {strategy!r}；可选值：{', '.join(VALID_STRATEGIES)}"
        )
    return normalized


def _candidate_models(spec: TaskSpec) -> list[RouteModel]:
    return [
        MODEL_ROUTING_CATALOG[model_id]
        for model_id in spec.candidates
        if model_id in MODEL_ROUTING_CATALOG
    ]


def _upgrade_models(spec: TaskSpec) -> list[RouteModel]:
    return [
        model
        for model in MODEL_ROUTING_CATALOG.values()
        if model.kind in spec.upgrade_kinds
    ]


def _local_first(models: list[RouteModel]) -> tuple[list[RouteModel], list[RouteModel]]:
    local = [model for model in models if model.provider != "deepseek"]
    cloud = [model for model in models if model.provider == "deepseek"]
    return local, cloud


def _budget_sort(models: list[RouteModel]) -> list[RouteModel]:
    return sorted(
        models,
        key=lambda model: (model.resident_mb, model.cost_per_1k, -model.quality),
    )


def _balanced_sort(models: list[RouteModel]) -> list[RouteModel]:
    def score(model: RouteModel) -> float:
        return (
            model.quality
            - model.latency_ms / 1000.0 * 3.0
            - model.cost_per_1k * 1000.0
        )

    return sorted(models, key=lambda model: (-score(model), model.resident_mb))


def _quality_sort(models: list[RouteModel]) -> list[RouteModel]:
    return sorted(
        models,
        key=lambda model: (-model.quality, model.cost_per_1k, model.resident_mb),
    )


def _ordered_candidates(spec: TaskSpec, strategy: str, budget_mb: int) -> list[RouteModel]:
    eligible = [
        model
        for model in _candidate_models(spec)
        if model.resident_mb <= budget_mb
    ]
    if not eligible:
        raise RouteValidationError(
            f"任务 {spec.key} 没有预算内候选模型（预算 {budget_mb} MB）"
        )

    if strategy == "quality":
        return _quality_sort(eligible)
    local, cloud = _local_first(eligible)
    if strategy == "balanced":
        return _balanced_sort(local) + _balanced_sort(cloud)
    return _budget_sort(local) + _budget_sort(cloud)


def _select_reason(model: RouteModel, strategy: str, budget_mb: int) -> str:
    if strategy == "budget":
        return (
            f"预算优先：{model.name} 驻留 {model.resident_mb} MB / "
            f"预算 {budget_mb} MB，成本 {model.cost_per_1k:.4f}/千 tokens"
        )
    if strategy == "balanced":
        return (
            f"均衡策略：质量 {model.quality}、延迟 {model.latency_ms} ms、"
            f"成本 {model.cost_per_1k:.4f}/千 tokens"
        )
    if strategy == "quality":
        return (
            f"质量优先：{model.name} 质量分 {model.quality}，"
            f"驻留 {model.resident_mb} MB / 预算 {budget_mb} MB"
        )
    return f"人工指定：{model.name}（驻留 {model.resident_mb} MB）"


def select_model(
    task: str,
    strategy: str,
    budget_mb: int | None = None,
    manual_model_id: str | None = None,
) -> tuple[RouteModel, str]:
    """按策略选择模型；非法任务 / 策略 / 超预算会抛 ``RouteValidationError``。"""
    spec = _validate_task(task)
    normalized = _validate_strategy(strategy)
    budget = _budget_value(budget_mb)

    if normalized == "manual":
        model_id = (manual_model_id or "").strip()
        if not model_id:
            raise RouteValidationError("manual 策略必须指定 modelId")
        if model_id not in spec.candidates:
            raise RouteValidationError(
                f"模型 {model_id!r} 不是任务 {task} 的候选；可选值：{', '.join(spec.candidates)}"
            )
        model = MODEL_ROUTING_CATALOG[model_id]
        if model.resident_mb > budget:
            raise RouteValidationError(
                f"模型 {model.name} 驻留 {model.resident_mb} MB 超出预算 {budget} MB"
            )
        return model, _select_reason(model, normalized, budget)

    ordered = _ordered_candidates(spec, normalized, budget)
    return ordered[0], _select_reason(ordered[0], normalized, budget)


def _fallback_models(
    spec: TaskSpec, selected: RouteModel, budget_mb: int
) -> tuple[str, ...]:
    """回退链：预算内、质量次之的候选（不含当前模型）。"""
    eligible = [
        model
        for model in _candidate_models(spec)
        if model.id != selected.id and model.resident_mb <= budget_mb
    ]
    return tuple(model.id for model in _quality_sort(eligible))


def route_task(
    task: str,
    config: RouteConfig | None = None,
    budget_mb: int | None = None,
) -> RouteDecision:
    """计算任务路由结果；无效的持久化配置回退到任务默认策略。"""
    spec = _validate_task(task)
    budget = _budget_value(budget_mb)
    strategy = spec.default_strategy
    manual_model_id: str | None = None

    if config is not None:
        configured_strategy = (config.strategy or "").strip().lower()
        if configured_strategy in VALID_STRATEGIES:
            strategy = configured_strategy
            manual_model_id = config.model_id
        if strategy == "manual" and not manual_model_id:
            strategy = spec.default_strategy

    try:
        model, reason = select_model(task, strategy, budget, manual_model_id)
    except RouteValidationError as exc:
        logger.warning("任务 %s 的路由配置无效，回退默认策略：%s", task, exc)
        strategy = spec.default_strategy
        model, reason = select_model(task, strategy, budget)

    updated_by = config.updated_by if config else ""
    updated_at = config.updated_at if config else None
    return RouteDecision(
        task=spec.key,
        label=spec.label,
        description=spec.description,
        strategy=strategy,
        model_id=model.id,
        model_name=model.name,
        provider=model.provider,
        kind=model.kind,
        quality=model.quality,
        cost_per_1k=model.cost_per_1k,
        latency_ms=model.latency_ms,
        resident_mb=model.resident_mb,
        quantization=model.quantization,
        dimension=model.dimension,
        budget_mb=budget,
        within_budget=model.resident_mb <= budget,
        reason=reason,
        fallback_models=_fallback_models(spec, model, budget),
        updated_by=updated_by,
        updated_at=updated_at,
    )


def upgrade_candidates(
    task: str,
    current_model_id: str | None = None,
    budget_mb: int | None = None,
) -> list[UpgradeCandidate]:
    """返回比当前模型质量更高的升级候选，并标记是否被预算 / 延迟阻塞。"""
    spec = _validate_task(task)
    budget = _budget_value(budget_mb)
    if current_model_id:
        current = MODEL_ROUTING_CATALOG.get(current_model_id)
    else:
        current = MODEL_ROUTING_CATALOG.get(
            route_task(task, budget_mb=budget).model_id
        )
    if current is None:
        current = MODEL_ROUTING_CATALOG[spec.default_model_id]

    result: list[UpgradeCandidate] = []
    for model in _upgrade_models(spec):
        if model.quality <= current.quality:
            continue
        if model.resident_mb > budget:
            result.append(
                UpgradeCandidate(
                    model=model,
                    eligible=False,
                    reason=(
                        f"需将预算提高至 {model.resident_mb} MB"
                        f"（当前 {budget} MB）"
                    ),
                )
            )
            continue
        if model.latency_ms > max(current.latency_ms * 2, current.latency_ms + 2500):
            result.append(
                UpgradeCandidate(
                    model=model,
                    eligible=False,
                    reason=f"延迟明显更高（{model.latency_ms} ms）",
                )
            )
            continue
        cost_note = (
            f"，云端成本约 {model.cost_per_1k:.4f}/千 tokens"
            if model.provider == "deepseek"
            else ""
        )
        result.append(
            UpgradeCandidate(
                model=model,
                eligible=True,
                reason=(
                    f"预算内可升级：质量 {current.quality} → {model.quality}"
                    f"{cost_note}"
                ),
            )
        )

    result.sort(key=lambda item: (not item.eligible, -item.model.quality))
    return result


def _config_cache_valid(now: float) -> bool:
    return _CONFIG_CACHE is not None and now < _CONFIG_CACHE[0]


def clear_route_cache() -> None:
    """清空进程内配置缓存（写入配置后调用）。"""
    global _CONFIG_CACHE
    _CONFIG_CACHE = None


def _load_configs_from_db(db: Any) -> dict[str, RouteConfig]:
    from app.models import ModelRouteConfig

    rows = db.query(ModelRouteConfig).all()
    return {
        row.task: RouteConfig(
            task=row.task,
            strategy=row.strategy,
            model_id=row.model_id,
            updated_by=row.updated_by or "",
            updated_at=row.updated_at,
        )
        for row in rows
    }


def load_route_configs(db: Any = None, *, use_cache: bool = True) -> dict[str, RouteConfig]:
    """读取任务级配置；数据库不可用时返回空配置（调用方回退默认）。"""
    global _CONFIG_CACHE

    import time

    now = time.monotonic()
    if db is None and use_cache and _config_cache_valid(now):
        return dict(_CONFIG_CACHE[1])  # type: ignore[index]

    session = db
    owns_session = False
    if session is None:
        try:
            from app.db import SessionLocal

            session = SessionLocal()
            owns_session = True
        except Exception as exc:  # noqa: BLE001 - 配置读取失败不阻塞任务
            logger.debug("创建路由配置会话失败：%s", exc)
            return {}

    try:
        configs = _load_configs_from_db(session)
    except Exception as exc:  # noqa: BLE001 - 表不存在 / 数据库未初始化时回退默认
        logger.debug("读取模型路由配置失败，使用默认：%s", exc)
        configs = {}
    finally:
        if owns_session:
            session.close()

    if db is None and use_cache:
        _CONFIG_CACHE = (now + _CONFIG_TTL_SECONDS, configs)
    return configs


def save_route_config(
    task: str,
    strategy: str,
    model_id: str | None = None,
    updated_by: str = "admin",
    db: Any = None,
) -> RouteConfig:
    """校验并写入任务配置（upsert）。"""
    spec = _validate_task(task)
    normalized = _validate_strategy(strategy)
    if normalized == "manual":
        if not (model_id or "").strip():
            raise RouteValidationError("manual 策略必须指定 modelId")
        select_model(task, normalized, manual_model_id=model_id)
    else:
        model_id = None

    from app.models import ModelRouteConfig

    session = db
    owns_session = False
    if session is None:
        from app.db import SessionLocal

        session = SessionLocal()
        owns_session = True
    try:
        row = session.get(ModelRouteConfig, spec.key)
        if row is None:
            row = ModelRouteConfig(task=spec.key, strategy=normalized, model_id=model_id)
            session.add(row)
        else:
            row.strategy = normalized
            row.model_id = model_id
        row.updated_by = (updated_by or "admin").strip()[:64] or "admin"
        row.updated_at = _utcnow()
        session.commit()
        session.refresh(row)
        config = RouteConfig(
            task=row.task,
            strategy=row.strategy,
            model_id=row.model_id,
            updated_by=row.updated_by or "",
            updated_at=row.updated_at,
        )
    finally:
        if owns_session:
            session.close()
    clear_route_cache()
    return config


def reset_route_config(task: str, db: Any = None) -> bool:
    """恢复单个任务默认；返回是否删除了已有配置。"""
    spec = _validate_task(task)

    from app.models import ModelRouteConfig

    session = db
    owns_session = False
    if session is None:
        from app.db import SessionLocal

        session = SessionLocal()
        owns_session = True
    try:
        row = session.get(ModelRouteConfig, spec.key)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True
    finally:
        if owns_session:
            session.close()
        clear_route_cache()


def reset_all_route_configs(db: Any = None) -> int:
    """恢复全部任务默认；返回删除条数。"""
    from app.models import ModelRouteConfig

    session = db
    owns_session = False
    if session is None:
        from app.db import SessionLocal

        session = SessionLocal()
        owns_session = True
    try:
        deleted = session.query(ModelRouteConfig).delete()
        session.commit()
        return int(deleted or 0)
    finally:
        if owns_session:
            session.close()
        clear_route_cache()


def get_route_decision(
    task: str,
    db: Any = None,
    budget_mb: int | None = None,
    *,
    use_cache: bool = True,
) -> RouteDecision:
    """运行链路入口：读取配置并返回任务路由决策。"""
    configs = load_route_configs(db=db, use_cache=use_cache)
    return route_task(task, configs.get(task), budget_mb)


def _model_payload(model: RouteModel, budget_mb: int) -> dict[str, Any]:
    return {
        "id": model.id,
        "name": model.name,
        "provider": model.provider,
        "kind": model.kind,
        "quality": model.quality,
        "costPer1k": model.cost_per_1k,
        "latencyMs": model.latency_ms,
        "residentMb": model.resident_mb,
        "quantization": model.quantization,
        "dimension": model.dimension,
        "contextTokens": model.context_tokens,
        "note": model.note,
        "withinBudget": model.resident_mb <= budget_mb,
    }


def task_payload(task: str, config: RouteConfig | None, budget_mb: int) -> dict[str, Any]:
    """单个任务的 API 载荷。"""
    spec = _validate_task(task)
    decision = route_task(task, config, budget_mb)
    upgrades = upgrade_candidates(task, decision.model_id, budget_mb)
    return {
        "task": decision.task,
        "label": decision.label,
        "description": decision.description,
        "strategy": decision.strategy,
        "modelId": decision.model_id,
        "modelName": decision.model_name,
        "provider": decision.provider,
        "kind": decision.kind,
        "quality": decision.quality,
        "costPer1k": decision.cost_per_1k,
        "latencyMs": decision.latency_ms,
        "residentMb": decision.resident_mb,
        "quantization": decision.quantization,
        "dimension": decision.dimension,
        "budgetMb": decision.budget_mb,
        "withinBudget": decision.within_budget,
        "reason": decision.reason,
        "fallbackModels": list(decision.fallback_models),
        "candidates": [
            _model_payload(model, budget_mb) for model in _candidate_models(spec)
        ],
        "upgrades": [
            {
                "modelId": item.model.id,
                "modelName": item.model.name,
                "provider": item.model.provider,
                "quality": item.model.quality,
                "residentMb": item.model.resident_mb,
                "costPer1k": item.model.cost_per_1k,
                "latencyMs": item.model.latency_ms,
                "eligible": item.eligible,
                "reason": item.reason,
            }
            for item in upgrades
        ],
        "updatedBy": decision.updated_by,
        "updatedAt": decision.updated_at.isoformat() if decision.updated_at else None,
    }


def overview_payload(
    configs: dict[str, RouteConfig] | None = None,
    budget_mb: int | None = None,
) -> dict[str, Any]:
    """模型路由总览：任务列表 + 目录 + 预算报告。"""
    budget = _budget_value(budget_mb)
    current = configs if configs is not None else load_route_configs()
    tasks = [
        task_payload(task, current.get(task), budget)
        for task in TASK_KEYS
    ]
    peak = max((item["residentMb"] for item in tasks), default=0)
    updated_values = [item["updatedAt"] for item in tasks if item["updatedAt"]]
    return {
        "budgetMb": budget,
        "peakResidentMb": peak,
        "budgetPercent": round(peak / budget * 100) if budget else 0,
        "withinBudget": all(item["withinBudget"] for item in tasks),
        "taskCount": len(tasks),
        "localModelCount": sum(
            1 for model in MODEL_ROUTING_CATALOG.values() if model.provider == "ollama"
        ),
        "cloudModelCount": sum(
            1 for model in MODEL_ROUTING_CATALOG.values() if model.provider == "deepseek"
        ),
        "ruleModelCount": sum(
            1 for model in MODEL_ROUTING_CATALOG.values() if model.provider == "rules"
        ),
        "updatedAt": max(updated_values) if updated_values else None,
        "tasks": tasks,
        "models": [
            _model_payload(model, budget) for model in MODEL_ROUTING_CATALOG.values()
        ],
    }


def health_payload(budget_mb: int | None = None, *, timeout: float = 2.0) -> dict[str, Any]:
    """模型通道健康状态（Ollama 探测失败不抛异常）。"""
    settings = get_settings()
    budget = _budget_value(budget_mb)
    probe = probe_ollama(settings.OLLAMA_BASE_URL, budget_mb=budget, timeout=timeout)
    return {
        "ollama": {
            "configured": bool((settings.OLLAMA_BASE_URL or "").strip()),
            "reachable": probe.reachable,
            "models": [
                {
                    "name": model.name,
                    "sizeMb": model.size_mb,
                    "sizeVramMb": model.size_vram_mb,
                    "withinBudget": model.within_budget,
                }
                for model in probe.models
            ],
            "peakResidentMb": probe.peak_resident_mb,
            "budgetOk": probe.budget_ok,
            "error": probe.error,
        },
        "deepseek": {
            "configured": bool((settings.DEEPSEEK_API_KEY or "").strip()),
            "model": settings.DEEPSEEK_MODEL,
            "baseUrl": settings.DEEPSEEK_BASE_URL,
        },
        "rules": {"available": True},
        "budgetMb": budget,
        "checkedAt": _utcnow().isoformat(),
    }
