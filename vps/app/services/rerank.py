"""推荐精排（Rerank，REQ-202610-0966 / M7-07）。

在 M3-05 粗排（相似度 + 热榜热度）之后做第二阶段排序：

1. 计算 6 个可解释信号：相关性 / 画像亲和 / 时效 / 动量 / 人气 / 健康度；
2. 按配置权重加权得到精排分；
3. 用 MMR（Maximal Marginal Relevance）做多样性重排，避免同质项目霸榜；
4. 输出精排前后名次、信号贡献与中文理由。

本模块全部为纯计算，不访问数据库 / 网络，便于离线单测与前端契约复用。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

# 各信号的默认权重（总和不必为 1，内部会按权重和归一化）
DEFAULT_WEIGHTS: dict[str, float] = {
    "relevance": 0.45,
    "affinity": 0.15,
    "freshness": 0.12,
    "momentum": 0.10,
    "popularity": 0.08,
    "health": 0.10,
}

SIGNAL_LABELS: dict[str, str] = {
    "relevance": "相关性",
    "affinity": "画像亲和",
    "freshness": "时效",
    "momentum": "动量",
    "popularity": "人气",
    "health": "健康度",
}

SIGNAL_REASONS: dict[str, str] = {
    "relevance": "与你收藏方向语义相关",
    "affinity": "语言 / 技术栈与你的收藏高度重合",
    "freshness": "近期仍有活跃提交",
    "momentum": "今日热度快速上升",
    "popularity": "社区关注度高",
    "health": "项目元数据完整、维护状态良好",
}

_FRESHNESS_HALF_LIFE_DAYS = 180.0
_REASON_MIN_CONTRIBUTION = 0.06
_MAX_REASONS = 3


@dataclass(frozen=True)
class RerankWeights:
    """精排信号权重（负值按 0 处理）。"""

    relevance: float = 0.45
    affinity: float = 0.15
    freshness: float = 0.12
    momentum: float = 0.10
    popularity: float = 0.08
    health: float = 0.10

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None) -> "RerankWeights":
        """从 dict / 环境配置构造；缺失或非法值回退默认值。"""
        data = dict(DEFAULT_WEIGHTS)
        if values:
            for key in data:
                if key in values:
                    data[key] = _safe_float(values.get(key), data[key])
        return cls(**data)

    def as_dict(self) -> dict[str, float]:
        return {
            "relevance": self.relevance,
            "affinity": self.affinity,
            "freshness": self.freshness,
            "momentum": self.momentum,
            "popularity": self.popularity,
            "health": self.health,
        }

    def normalized(self) -> dict[str, float]:
        """归一化到总和为 1；全 0 时退化为纯相关性。"""
        raw = {key: max(0.0, float(value)) for key, value in self.as_dict().items()}
        total = sum(raw.values())
        if total <= 0:
            return {key: (1.0 if key == "relevance" else 0.0) for key in raw}
        return {key: value / total for key, value in raw.items()}


@dataclass(frozen=True)
class RerankCandidate:
    """参与精排的候选及其仓库元数据。"""

    repo_id: str
    base_score: float
    similarity: float = 0.0
    stars_today: int = 0
    stars: int = 0
    language: str = ""
    tech_stack: tuple[str, ...] = ()
    description: str = ""
    readme_summary: str = ""
    license_spdx: str | None = None
    pushed_at: datetime | None = None
    open_issues_count: int = 0
    archived: bool = False
    disabled: bool = False
    health_score: int | None = None
    vector: tuple[float, ...] = ()


@dataclass(frozen=True)
class RerankItem:
    """单条精排结果。"""

    repo_id: str
    base_score: float
    rerank_score: float
    rank_before: int
    rank_after: int
    signals: dict[str, float] = field(default_factory=dict)
    contributions: dict[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    diversity_penalty: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """转成可持久化 / 可返回前端的 camelCase 结构。"""
        return {
            "repoId": self.repo_id,
            "baseScore": round(self.base_score, 6),
            "rerankScore": round(self.rerank_score, 6),
            "rankBefore": self.rank_before,
            "rankAfter": self.rank_after,
            "signals": {key: round(value, 6) for key, value in self.signals.items()},
            "contributions": {
                key: round(value, 6) for key, value in self.contributions.items()
            },
            "reasons": list(self.reasons),
            "diversityPenalty": round(self.diversity_penalty, 6),
        }


@dataclass(frozen=True)
class RerankResult:
    """一次精排的完整结果。"""

    items: tuple[RerankItem, ...]
    metrics: dict[str, Any]
    weights: dict[str, float]
    mmr_lambda: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "metrics": dict(self.metrics),
            "weights": dict(self.weights),
            "mmrLambda": self.mmr_lambda,
        }


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(number) or math.isinf(number):
        return fallback
    return number


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, _safe_float(value)))


def _log_norm(value: float, maximum: float) -> float:
    """对数归一化到 0~1；最大值为 0 时返回 0。"""
    top = max(0.0, _safe_float(maximum))
    if top <= 0:
        return 0.0
    current = max(0.0, _safe_float(value))
    return _clamp(math.log1p(current) / math.log1p(top))


def _tokens(values: Iterable[str]) -> set[str]:
    """技术栈 / 语言归一：小写、去空白、拆分常见分隔符。"""
    result: set[str] = set()
    for raw in values:
        for part in str(raw or "").replace("，", "/").replace(",", "/").replace("、", "/").split("/"):
            token = part.strip().lower()
            if token:
                result.add(token)
    return result


def build_interest_terms(
    languages: Sequence[str] = (),
    tech_terms: Sequence[str] = (),
) -> set[str]:
    """把用户画像的语言 + 技术词合并为归一化词集合。"""
    return _tokens(list(languages) + list(tech_terms))


def affinity_score(candidate: RerankCandidate, interest_terms: set[str]) -> float:
    """画像亲和：候选语言 / 技术栈命中画像词的比例。"""
    if not interest_terms:
        return 0.0
    candidate_terms = _tokens([candidate.language, *candidate.tech_stack])
    if not candidate_terms:
        return 0.0
    matched = candidate_terms & interest_terms
    if not matched:
        return 0.0
    # 以候选自身可识别技术面为分母，避免技术栈越全反而被稀释
    return _clamp(len(matched) / min(len(candidate_terms), 6))


def freshness_score(
    pushed_at: datetime | None,
    now: datetime | None = None,
    *,
    half_life_days: float = _FRESHNESS_HALF_LIFE_DAYS,
) -> float:
    """时效：按最后提交时间做半衰期衰减；缺失时给中性 0.5。"""
    if pushed_at is None:
        return 0.5
    current = now or datetime.utcnow()
    days = max(0.0, (current - pushed_at).total_seconds() / 86400.0)
    half_life = max(1.0, float(half_life_days))
    return _clamp(0.5 ** (days / half_life))


def health_score(candidate: RerankCandidate) -> float:
    """健康度：归档 / 禁用直接 0；有实测 health_score 优先；否则按元数据完整度。"""
    if candidate.archived or candidate.disabled:
        return 0.0
    if candidate.health_score is not None:
        return _clamp(_safe_float(candidate.health_score) / 100.0)
    completeness = 0.0
    if (candidate.description or "").strip():
        completeness += 0.3
    if (candidate.readme_summary or "").strip():
        completeness += 0.3
    if (candidate.license_spdx or "").strip():
        completeness += 0.2
    if (candidate.language or "").strip():
        completeness += 0.1
    if candidate.tech_stack:
        completeness += 0.1
    return _clamp(completeness)


def compute_signals(
    candidate: RerankCandidate,
    *,
    max_stars_today: int,
    max_stars: int,
    interest_terms: set[str],
    now: datetime | None = None,
) -> dict[str, float]:
    """计算单条候选的 6 个归一化信号。"""
    return {
        "relevance": _clamp(candidate.base_score),
        "affinity": affinity_score(candidate, interest_terms),
        "freshness": freshness_score(candidate.pushed_at, now),
        "momentum": _log_norm(candidate.stars_today, max_stars_today),
        "popularity": _log_norm(candidate.stars, max_stars),
        "health": health_score(candidate),
    }


def weighted_score(signals: Mapping[str, float], weights: RerankWeights | Mapping[str, float]) -> float:
    """按权重计算精排分（权重自动归一化）。"""
    normalized = (
        weights.normalized()
        if isinstance(weights, RerankWeights)
        else RerankWeights.from_mapping(weights).normalized()
    )
    total = sum(_clamp(signals.get(key, 0.0)) * weight for key, weight in normalized.items())
    return _clamp(total)


def _vector_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """余弦相似度；维度不一致或空向量返回 0。"""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += float(a) * float(b)
        left_norm += float(a) * float(a)
        right_norm += float(b) * float(b)
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return _clamp(dot / math.sqrt(left_norm * right_norm))


def candidate_similarity(left: RerankCandidate, right: RerankCandidate) -> float:
    """候选间相似度：优先向量余弦，缺失时回退语言 / 技术栈 Jaccard。"""
    vector_sim = _vector_similarity(left.vector, right.vector)
    if vector_sim > 0:
        return vector_sim
    left_terms = _tokens([left.language, *left.tech_stack])
    right_terms = _tokens([right.language, *right.tech_stack])
    if not left_terms or not right_terms:
        return 0.0
    union = left_terms | right_terms
    if not union:
        return 0.0
    return len(left_terms & right_terms) / len(union)


def _mmr_select(
    candidates: Sequence[RerankCandidate],
    scores: Mapping[str, float],
    *,
    top_k: int,
    mmr_lambda: float,
) -> list[tuple[RerankCandidate, float]]:
    """MMR 贪心选择：质量优先，同时惩罚与已选条目的相似度。"""
    remaining = list(candidates)
    selected: list[RerankCandidate] = []
    chosen: list[tuple[RerankCandidate, float]] = []
    lam = _clamp(mmr_lambda)
    limit = max(0, int(top_k))
    while remaining and len(chosen) < limit:
        best: tuple[float, str, RerankCandidate, float] | None = None
        for candidate in remaining:
            max_sim = 0.0
            for picked in selected:
                max_sim = max(max_sim, candidate_similarity(candidate, picked))
            mmr = lam * scores.get(candidate.repo_id, 0.0) - (1.0 - lam) * max_sim
            key = (-mmr, candidate.repo_id)
            if best is None or key < (best[0], best[1]):
                best = (key[0], key[1], candidate, max_sim)
        if best is None:
            break
        _, _, picked, max_sim = best
        remaining.remove(picked)
        selected.append(picked)
        chosen.append((picked, max_sim))
    return chosen


def _build_reasons(
    signals: Mapping[str, float],
    contributions: Mapping[str, float],
    diversity_penalty: float,
) -> tuple[str, ...]:
    """按贡献度生成 1~3 条中文精排理由。"""
    ranked = sorted(
        (
            (key, value)
            for key, value in contributions.items()
            if value >= _REASON_MIN_CONTRIBUTION
        ),
        key=lambda pair: (-pair[1], pair[0]),
    )
    reasons = [SIGNAL_REASONS[key] for key, _ in ranked[:_MAX_REASONS] if key in SIGNAL_REASONS]
    if diversity_penalty >= 0.05:
        reasons.append("为提升列表多样性做了降权")
    if not reasons:
        reasons.append("综合信号排序")
    return tuple(reasons)


def _diversity(items: Sequence[RerankItem], by_id: Mapping[str, RerankCandidate]) -> float:
    """Top 列表的平均两两差异度（1 - 相似度）。"""
    if len(items) < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for index, left in enumerate(items):
        for right in items[index + 1 :]:
            left_row = by_id.get(left.repo_id)
            right_row = by_id.get(right.repo_id)
            if left_row is None or right_row is None:
                continue
            total += 1.0 - candidate_similarity(left_row, right_row)
            pairs += 1
    return _clamp(total / pairs) if pairs else 0.0


def _language_coverage(items: Sequence[RerankItem], by_id: Mapping[str, RerankCandidate]) -> float:
    if not items:
        return 0.0
    languages = {
        (by_id[item.repo_id].language or "").strip().lower()
        for item in items
        if item.repo_id in by_id and (by_id[item.repo_id].language or "").strip()
    }
    return _clamp(len(languages) / len(items))


def rerank_candidates(
    candidates: Sequence[RerankCandidate],
    *,
    weights: RerankWeights | Mapping[str, float] | None = None,
    top_k: int = 20,
    mmr_lambda: float = 0.75,
    interest_terms: Iterable[str] | None = None,
    now: datetime | None = None,
) -> RerankResult:
    """对粗排候选做精排并返回结果与指标。

    - `candidates` 应已按业务阈值过滤（这里只负责重排）；
    - 同分按 `repo_id` 升序，保证结果稳定可复现；
    - `top_k <= 0` 时返回空结果。
    """
    weight_obj = weights if isinstance(weights, RerankWeights) else RerankWeights.from_mapping(weights)
    normalized_weights = weight_obj.normalized()
    usable = [item for item in candidates if item.repo_id]
    if not usable or int(top_k) <= 0:
        return RerankResult(
            items=(),
            metrics={
                "total": 0,
                "selected": 0,
                "movedUp": 0,
                "movedDown": 0,
                "unchanged": 0,
                "avgRankShift": 0.0,
                "diversityBefore": 0.0,
                "diversityAfter": 0.0,
                "languageCoverage": 0.0,
            },
            weights=normalized_weights,
            mmr_lambda=_clamp(mmr_lambda),
        )

    terms = set(interest_terms or ())
    max_stars_today = max(int(item.stars_today or 0) for item in usable)
    max_stars = max(int(item.stars or 0) for item in usable)

    signals_by_id: dict[str, dict[str, float]] = {}
    contributions_by_id: dict[str, dict[str, float]] = {}
    scores: dict[str, float] = {}
    for item in usable:
        signals = compute_signals(
            item,
            max_stars_today=max_stars_today,
            max_stars=max_stars,
            interest_terms=terms,
            now=now,
        )
        signals_by_id[item.repo_id] = signals
        contributions_by_id[item.repo_id] = {
            key: signals[key] * normalized_weights[key] for key in signals
        }
        scores[item.repo_id] = weighted_score(signals, weight_obj)

    before_order = sorted(usable, key=lambda item: (-item.base_score, item.repo_id))
    before_rank = {item.repo_id: index + 1 for index, item in enumerate(before_order)}

    chosen = _mmr_select(
        usable, scores, top_k=int(top_k), mmr_lambda=mmr_lambda
    )
    by_id = {item.repo_id: item for item in usable}
    items: list[RerankItem] = []
    for index, (candidate, max_sim) in enumerate(chosen):
        diversity_penalty = (1.0 - _clamp(mmr_lambda)) * max_sim
        signals = signals_by_id[candidate.repo_id]
        items.append(
            RerankItem(
                repo_id=candidate.repo_id,
                base_score=candidate.base_score,
                rerank_score=scores[candidate.repo_id],
                rank_before=before_rank.get(candidate.repo_id, 0),
                rank_after=index + 1,
                signals=signals,
                contributions=contributions_by_id[candidate.repo_id],
                reasons=_build_reasons(
                    signals, contributions_by_id[candidate.repo_id], diversity_penalty
                ),
                diversity_penalty=diversity_penalty,
            )
        )

    moved_up = sum(1 for item in items if item.rank_before > item.rank_after)
    moved_down = sum(1 for item in items if item.rank_before < item.rank_after)
    unchanged = len(items) - moved_up - moved_down
    avg_shift = (
        sum(abs(item.rank_before - item.rank_after) for item in items) / len(items)
        if items
        else 0.0
    )
    before_items = [
        RerankItem(
            repo_id=item.repo_id,
            base_score=item.base_score,
            rerank_score=scores[item.repo_id],
            rank_before=before_rank[item.repo_id],
            rank_after=before_rank[item.repo_id],
        )
        for item in before_order[: len(items)]
    ]
    metrics = {
        "total": len(usable),
        "selected": len(items),
        "movedUp": moved_up,
        "movedDown": moved_down,
        "unchanged": unchanged,
        "avgRankShift": round(avg_shift, 4),
        "diversityBefore": round(_diversity(before_items, by_id), 4),
        "diversityAfter": round(_diversity(items, by_id), 4),
        "languageCoverage": round(_language_coverage(items, by_id), 4),
    }
    return RerankResult(
        items=tuple(items),
        metrics=metrics,
        weights=normalized_weights,
        mmr_lambda=_clamp(mmr_lambda),
    )
