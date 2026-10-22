"""推荐质量评估与调参（M3-08）。

提供离线、可复现的推荐质量评估：

1. **抽样评估集**：把收藏库按固定种子切分成「画像集 / 留出正样本」，再从热榜采样
   未收藏仓库作为负样本，形成多个评估折叠（fold）；
2. **排序指标**：Precision@K / Recall@K / HitRate / MRR / NDCG@K，以及覆盖率与多样性；
3. **阈值调优**：对 `RECOMMEND_MIN_SCORE` 与相似度 / 热度权重做二维网格扫描，
   按 F1（并列时覆盖率、与当前配置的接近程度）给出建议参数；
4. **线上反馈旁证**：汇总本地 `recommendations.status`，给出收藏率 / 忽略率。

本模块不访问网络；向量优先复用 `repo_vectors`，缺失时由 `ensure_repo_vectors` 现场编码。
评估只读业务数据，唯一的写入是向量缓存（与每日推荐任务一致）。
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import MyRepository, Recommendation, TrendingRepository
from app.services.embedding import EmbeddingService, get_embedding_service
from app.services.recommendation_service import ensure_repo_vectors
from app.services.recommender import Candidate, RankedCandidate, build_profile_vector, rank_candidates

logger = logging.getLogger(__name__)

DEFAULT_MIN_SCORE_GRID: tuple[float, ...] = (0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50)
DEFAULT_WEIGHT_GRID: tuple[float, ...] = (0.6, 0.7, 0.8, 0.9, 1.0)

_METRIC_KEYS = (
    "precision",
    "recall",
    "f1",
    "hitRate",
    "mrr",
    "ndcg",
    "coverage",
    "diversity",
    "avgResults",
)


@dataclass(frozen=True)
class EvalCandidate:
    """评估候选：正样本来自收藏库留出集，负样本来自热榜。"""

    repo_id: str
    vector: Sequence[float]
    stars_today: int = 0
    group: str = ""


@dataclass(frozen=True)
class EvalSample:
    """一个评估折叠：画像向量 + 留出正样本 + 候选池。"""

    fold: int
    profile_size: int
    profile_vec: tuple[float, ...]
    positive_ids: frozenset[str]
    candidates: tuple[EvalCandidate, ...]
    groups: Mapping[str, str]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def precision_at_k(ranked_ids: Sequence[str], positive_ids: set[str] | frozenset[str], k: int) -> float:
    """返回列表前 k 条中正样本占比（分母为实际返回条数，最多 k）。"""
    if k <= 0:
        return 0.0
    top = list(ranked_ids)[:k]
    if not top:
        return 0.0
    hits = sum(1 for repo_id in top if repo_id in positive_ids)
    return hits / len(top)


def recall_at_k(ranked_ids: Sequence[str], positive_ids: set[str] | frozenset[str], k: int) -> float:
    """前 k 条覆盖了多少比例的正样本。"""
    if k <= 0 or not positive_ids:
        return 0.0
    top = list(ranked_ids)[:k]
    hits = sum(1 for repo_id in top if repo_id in positive_ids)
    return hits / len(positive_ids)


def hit_rate_at_k(ranked_ids: Sequence[str], positive_ids: set[str] | frozenset[str], k: int) -> float:
    """前 k 条是否至少命中一个正样本。"""
    if k <= 0 or not positive_ids:
        return 0.0
    return 1.0 if any(repo_id in positive_ids for repo_id in list(ranked_ids)[:k]) else 0.0


def reciprocal_rank_at_k(
    ranked_ids: Sequence[str], positive_ids: set[str] | frozenset[str], k: int
) -> float:
    """第一个正样本的倒数排名（未命中为 0）。"""
    if k <= 0 or not positive_ids:
        return 0.0
    for index, repo_id in enumerate(list(ranked_ids)[:k], start=1):
        if repo_id in positive_ids:
            return 1.0 / index
    return 0.0


def _dcg(gains: Sequence[float]) -> float:
    return sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))


def ndcg_at_k(ranked_ids: Sequence[str], positive_ids: set[str] | frozenset[str], k: int) -> float:
    """二值相关性 NDCG@K。"""
    if k <= 0 or not positive_ids:
        return 0.0
    gains = [1.0 if repo_id in positive_ids else 0.0 for repo_id in list(ranked_ids)[:k]]
    ideal = [1.0] * min(len(positive_ids), k)
    ideal_dcg = _dcg(ideal)
    return _dcg(gains) / ideal_dcg if ideal_dcg > 0 else 0.0


def diversity_at_k(
    ranked_ids: Sequence[str], groups: Mapping[str, str], k: int
) -> float:
    """返回列表中不同语言 / 技术栈分组的占比（越高越多样）。"""
    top = list(ranked_ids)[:k]
    if not top:
        return 0.0
    distinct = {str(groups.get(repo_id) or "").strip().lower() for repo_id in top}
    return len(distinct) / len(top)


def _aggregate(
    scored_lists: Sequence[Sequence[RankedCandidate]],
    samples: Sequence[EvalSample],
    top_k: int,
) -> dict[str, float]:
    """聚合多个 fold 的指标（逐 fold 求均值）。"""
    if not scored_lists:
        return {key: 0.0 for key in _METRIC_KEYS}

    precisions: list[float] = []
    recalls: list[float] = []
    hit_rates: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    diversities: list[float] = []
    result_counts: list[int] = []

    for scored, sample in zip(scored_lists, samples):
        ids = [item.repo_id for item in scored[:top_k]]
        result_counts.append(len(ids))
        precisions.append(precision_at_k(ids, sample.positive_ids, top_k))
        recalls.append(recall_at_k(ids, sample.positive_ids, top_k))
        hit_rates.append(hit_rate_at_k(ids, sample.positive_ids, top_k))
        reciprocal_ranks.append(reciprocal_rank_at_k(ids, sample.positive_ids, top_k))
        ndcgs.append(ndcg_at_k(ids, sample.positive_ids, top_k))
        diversities.append(diversity_at_k(ids, sample.groups, top_k))

    precision = _mean(precisions)
    recall = _mean(recalls)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    coverage = sum(1 for count in result_counts if count > 0) / len(result_counts)
    return {
        "precision": _round(precision),
        "recall": _round(recall),
        "f1": _round(f1),
        "hitRate": _round(_mean(hit_rates)),
        "mrr": _round(_mean(reciprocal_ranks)),
        "ndcg": _round(_mean(ndcgs)),
        "coverage": _round(coverage),
        "diversity": _round(_mean(diversities)),
        "avgResults": _round(_mean([float(count) for count in result_counts])),
    }


def _score_samples(
    samples: Sequence[EvalSample],
    similarity_weight: float,
    trending_weight: float,
) -> list[list[RankedCandidate]]:
    """对每个 fold 的候选打分（阈值交给后续网格过滤）。"""
    scored: list[list[RankedCandidate]] = []
    for sample in samples:
        ranked = rank_candidates(
            sample.profile_vec,
            [
                Candidate(
                    repo_id=item.repo_id,
                    vector=item.vector,
                    stars_today=item.stars_today,
                )
                for item in sample.candidates
            ],
            min_score=0.0,
            top_k=len(sample.candidates),
            similarity_weight=similarity_weight,
            trending_weight=trending_weight,
        )
        scored.append(ranked)
    return scored


def _threshold_rows(
    scored_by_sample: Sequence[Sequence[RankedCandidate]],
    samples: Sequence[EvalSample],
    thresholds: Sequence[float],
    top_k: int,
) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for threshold in thresholds:
        filtered = [
            [item for item in scored if item.score + 1e-12 >= threshold]
            for scored in scored_by_sample
        ]
        rows.append({"minScore": _round(threshold), **_aggregate(filtered, samples, top_k)})
    return rows


def _pick_best(
    rows: Sequence[dict[str, float]],
    *,
    similarity_weight: float,
    trending_weight: float,
    current_min_score: float,
    current_similarity_weight: float,
) -> dict[str, float]:
    """按 F1 → 覆盖率 → 参数接近当前值挑选最优行。"""

    def key(row: Mapping[str, float]) -> tuple[float, float, float, float]:
        return (
            float(row["f1"]),
            float(row["coverage"]),
            -abs(float(row["minScore"]) - current_min_score),
            -abs(similarity_weight - current_similarity_weight),
        )

    best = max(rows, key=key)
    return {
        **best,
        "similarityWeight": _round(similarity_weight),
        "trendingWeight": _round(trending_weight),
    }


def _parse_grid(raw: str, default: Sequence[float]) -> list[float]:
    """解析逗号分隔的 0~1 网格；非法项忽略，空结果回退默认。"""
    values: list[float] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = float(part)
        except ValueError:
            continue
        if 0.0 <= value <= 1.0:
            values.append(_round(value))
    return sorted(set(values)) or list(default)


def build_eval_samples(
    db: Session,
    *,
    service: Optional[EmbeddingService] = None,
    settings: Optional[Settings] = None,
    sample_size: Optional[int] = None,
    holdout_ratio: Optional[float] = None,
    top_k: Optional[int] = None,
    negatives_per_positive: Optional[int] = None,
    seed: Optional[int] = None,
) -> tuple[list[EvalSample], dict[str, Any], list[str]]:
    """构建确定性抽样评估集，返回 (samples, dataset 摘要, warnings)。"""
    config = settings or get_settings()
    embedding = service or get_embedding_service()

    max_samples = max(1, int(config.RECOMMEND_EVAL_MAX_SAMPLES))
    n_samples = max(1, min(int(sample_size or config.RECOMMEND_EVAL_SAMPLE_SIZE), max_samples))
    ratio = float(holdout_ratio if holdout_ratio is not None else config.RECOMMEND_EVAL_HOLDOUT_RATIO)
    ratio = min(0.8, max(0.05, ratio))
    effective_top_k = max(1, int(top_k or config.RECOMMEND_EVAL_TOP_K))
    negatives_per = max(1, int(negatives_per_positive or config.RECOMMEND_EVAL_NEGATIVES_PER_POSITIVE))
    seed_value = int(seed if seed is not None else config.RECOMMEND_EVAL_SEED)

    warnings: list[str] = []
    dataset: dict[str, Any] = {
        "myRepositories": 0,
        "trendingRepositories": 0,
        "usableMyRepositories": 0,
        "negativePool": 0,
        "samples": 0,
        "skippedSamples": 0,
        "positives": 0,
        "negatives": 0,
        "avgCandidates": 0.0,
        "holdoutRatio": _round(ratio),
        "topK": effective_top_k,
        "negativesPerPositive": negatives_per,
        "seed": seed_value,
    }

    my_rows = list(
        db.execute(select(MyRepository).order_by(MyRepository.id.asc())).scalars().all()
    )
    dataset["myRepositories"] = len(my_rows)
    if len(my_rows) < 2:
        warnings.append("收藏库不足 2 条，无法切分画像集与留出集")
        return [], dataset, warnings

    my_vectors = ensure_repo_vectors(
        db, "my", my_rows, embedding, batch_size=config.VECTORIZE_BATCH_SIZE
    )
    usable_my = [row for row in my_rows if my_vectors.get(row.id)]
    dataset["usableMyRepositories"] = len(usable_my)
    if len(usable_my) < 2:
        warnings.append("可用向量不足 2 条，无法构建评估集")
        return [], dataset, warnings

    trending_rows = list(
        db.execute(select(TrendingRepository).order_by(TrendingRepository.id.asc())).scalars().all()
    )
    dataset["trendingRepositories"] = len(trending_rows)
    collected = {row.id for row in my_rows}
    negative_pool = [row for row in trending_rows if row.id not in collected]
    pool_limit = max(1, int(config.RECOMMEND_CANDIDATE_LIMIT))
    if len(negative_pool) > pool_limit:
        negative_pool = random.Random(seed_value).sample(negative_pool, pool_limit)

    negative_vectors = ensure_repo_vectors(
        db, "trending", negative_pool, embedding, batch_size=config.VECTORIZE_BATCH_SIZE
    )
    usable_negatives = [row for row in negative_pool if negative_vectors.get(row.id)]
    dataset["negativePool"] = len(usable_negatives)
    if not usable_negatives:
        warnings.append("热榜没有可用的负样本，评估结果仅反映正样本内部排序")

    my_by_id = {row.id: row for row in usable_my}
    my_ids = [row.id for row in usable_my]
    samples: list[EvalSample] = []
    skipped = 0
    total_positives = 0
    total_negatives = 0
    total_candidates = 0

    for fold in range(n_samples):
        rng = random.Random(seed_value + fold)
        shuffled = list(my_ids)
        rng.shuffle(shuffled)
        holdout_count = max(1, int(round(len(shuffled) * ratio)))
        holdout_count = min(holdout_count, len(shuffled) - 1)
        positive_ids = shuffled[:holdout_count]
        profile_ids = shuffled[holdout_count:]
        profile_vec = build_profile_vector([my_vectors[repo_id] for repo_id in profile_ids])
        if not profile_vec:
            skipped += 1
            continue

        negative_count = min(len(usable_negatives), negatives_per * len(positive_ids))
        negatives = rng.sample(usable_negatives, negative_count) if negative_count else []

        candidates: list[EvalCandidate] = []
        groups: dict[str, str] = {}
        for repo_id in positive_ids:
            row = my_by_id[repo_id]
            candidates.append(
                EvalCandidate(
                    repo_id=repo_id,
                    vector=my_vectors[repo_id],
                    stars_today=0,
                    group=row.language or "",
                )
            )
            groups[repo_id] = row.language or ""
        for row in negatives:
            candidates.append(
                EvalCandidate(
                    repo_id=row.id,
                    vector=negative_vectors[row.id],
                    stars_today=int(row.stars_today or 0),
                    group=row.tech_stack or "",
                )
            )
            groups[row.id] = row.tech_stack or ""

        if len(candidates) <= len(positive_ids):
            skipped += 1
            continue

        samples.append(
            EvalSample(
                fold=fold,
                profile_size=len(profile_ids),
                profile_vec=tuple(profile_vec),
                positive_ids=frozenset(positive_ids),
                candidates=tuple(candidates),
                groups=groups,
            )
        )
        total_positives += len(positive_ids)
        total_negatives += len(negatives)
        total_candidates += len(candidates)

    dataset["samples"] = len(samples)
    dataset["skippedSamples"] = skipped
    dataset["positives"] = total_positives
    dataset["negatives"] = total_negatives
    dataset["avgCandidates"] = _round(total_candidates / len(samples)) if samples else 0.0
    if skipped:
        warnings.append(f"{skipped} 个折叠因画像向量为空或候选不足被跳过")
    return samples, dataset, warnings


def feedback_metrics(db: Session, user_id: Optional[str] = None) -> dict[str, Any]:
    """汇总推荐状态，作为离线指标的线上旁证。"""
    stmt = select(Recommendation.status, func.count(Recommendation.id))
    if user_id:
        stmt = stmt.where(Recommendation.user_id == str(user_id))
    stmt = stmt.group_by(Recommendation.status)
    counts = {str(status): int(count) for status, count in db.execute(stmt).all()}

    by_status = {
        status: counts.get(status, 0)
        for status in ("new", "pushed", "saved", "dismissed", "expired")
    }
    for status, count in counts.items():
        by_status.setdefault(status, count)
    decided = by_status.get("saved", 0) + by_status.get("dismissed", 0)
    total = sum(by_status.values())
    return {
        "total": total,
        "byStatus": by_status,
        "decided": decided,
        "saveRate": _round(by_status.get("saved", 0) / decided) if decided else 0.0,
        "dismissRate": _round(by_status.get("dismissed", 0) / decided) if decided else 0.0,
    }


def sweep_parameters(
    samples: Sequence[EvalSample],
    *,
    thresholds: Sequence[float],
    weight_grid: Sequence[float],
    top_k: int,
    current_min_score: float,
    current_similarity_weight: float,
    current_trending_weight: float,
) -> tuple[list[dict[str, float]], list[dict[str, float]], dict[str, Any], dict[str, float]]:
    """二维扫描阈值与权重。

    返回 (当前权重下的阈值行, 每个权重的最优行, 推荐参数, 当前参数行)。
    """
    current_scored = _score_samples(samples, current_similarity_weight, current_trending_weight)
    threshold_rows = _threshold_rows(current_scored, samples, thresholds, top_k)
    current_row = _threshold_rows(
        current_scored, samples, [current_min_score], top_k
    )[0]

    weight_rows: list[dict[str, float]] = []
    best_row: Optional[dict[str, float]] = None
    for similarity_weight in weight_grid:
        trending_weight = _round(max(0.0, 1.0 - similarity_weight))
        scored = _score_samples(samples, similarity_weight, trending_weight)
        rows = _threshold_rows(scored, samples, thresholds, top_k)
        row = _pick_best(
            rows,
            similarity_weight=similarity_weight,
            trending_weight=trending_weight,
            current_min_score=current_min_score,
            current_similarity_weight=current_similarity_weight,
        )
        weight_rows.append(row)
        if best_row is None:
            best_row = row
            continue
        best_key = (
            best_row["f1"],
            best_row["coverage"],
            -abs(best_row["minScore"] - current_min_score),
            -abs(best_row["similarityWeight"] - current_similarity_weight),
        )
        row_key = (
            row["f1"],
            row["coverage"],
            -abs(row["minScore"] - current_min_score),
            -abs(row["similarityWeight"] - current_similarity_weight),
        )
        if row_key > best_key:
            best_row = row

    assert best_row is not None  # weight_grid 至少一项（_parse_grid 保证）
    improved = (
        best_row["f1"] > current_row["f1"] + 1e-9
        or best_row["ndcg"] > current_row["ndcg"] + 1e-9
    )
    if best_row["f1"] <= 0:
        recommended: dict[str, Any] = {
            "minScore": _round(current_min_score),
            "similarityWeight": _round(current_similarity_weight),
            "trendingWeight": _round(current_trending_weight),
            "reason": "所有候选参数都未命中留出正样本，保留当前参数；建议先积累收藏库与热榜数据。",
            "improved": False,
        }
    else:
        reason = (
            f"在 {len(samples)} 个评估折叠上，F1 从 {current_row['f1']:.4f} "
            f"变为 {best_row['f1']:.4f}，覆盖率 {best_row['coverage']:.0%}；"
            f"建议 min_score={best_row['minScore']:.2f}、"
            f"相似度权重={best_row['similarityWeight']:.2f}。"
        )
        if not improved:
            reason = "当前参数与最优候选相当，" + reason
        recommended = {
            "minScore": best_row["minScore"],
            "similarityWeight": best_row["similarityWeight"],
            "trendingWeight": best_row["trendingWeight"],
            "reason": reason,
            "improved": bool(improved),
        }

    return threshold_rows, weight_rows, recommended, current_row


def evaluate_recommendation_quality(
    db: Session,
    *,
    user_id: Optional[str] = None,
    service: Optional[EmbeddingService] = None,
    settings: Optional[Settings] = None,
    sample_size: Optional[int] = None,
    top_k: Optional[int] = None,
    holdout_ratio: Optional[float] = None,
    negatives_per_positive: Optional[int] = None,
    seed: Optional[int] = None,
) -> dict[str, Any]:
    """运行一次完整评估，返回可直接序列化为 `RecommendEvalReport` 的字典。"""
    config = settings or get_settings()
    samples, dataset, warnings = build_eval_samples(
        db,
        service=service,
        settings=config,
        sample_size=sample_size,
        holdout_ratio=holdout_ratio,
        top_k=top_k,
        negatives_per_positive=negatives_per_positive,
        seed=seed,
    )
    thresholds = _parse_grid(config.RECOMMEND_EVAL_MIN_SCORE_GRID, DEFAULT_MIN_SCORE_GRID)
    weight_grid = _parse_grid(config.RECOMMEND_EVAL_WEIGHT_GRID, DEFAULT_WEIGHT_GRID)
    current_min_score = max(0.0, min(1.0, float(config.RECOMMEND_MIN_SCORE)))
    current_similarity_weight = max(0.0, float(config.RECOMMEND_SIMILARITY_WEIGHT))
    current_trending_weight = max(0.0, float(config.RECOMMEND_TRENDING_WEIGHT))
    effective_top_k = int(dataset["topK"])

    report: dict[str, Any] = {
        "status": "ok",
        "generatedAt": _utcnow(),
        "config": {
            "sampleSize": dataset["samples"],
            "holdoutRatio": dataset["holdoutRatio"],
            "topK": effective_top_k,
            "negativesPerPositive": dataset["negativesPerPositive"],
            "seed": dataset["seed"],
            "minScoreGrid": thresholds,
            "weightGrid": weight_grid,
            "maxSamples": int(config.RECOMMEND_EVAL_MAX_SAMPLES),
        },
        "dataset": dataset,
        "metrics": {key: 0.0 for key in _METRIC_KEYS},
        "thresholds": [],
        "weights": [],
        "recommended": {
            "minScore": _round(current_min_score),
            "similarityWeight": _round(current_similarity_weight),
            "trendingWeight": _round(current_trending_weight),
            "reason": "",
            "improved": False,
        },
        "current": {
            "minScore": _round(current_min_score),
            **{key: 0.0 for key in _METRIC_KEYS},
        },
        "feedback": feedback_metrics(db, user_id),
        "warnings": warnings,
    }

    if not samples:
        report["status"] = "insufficient_data"
        report["recommended"]["reason"] = "评估数据不足，无法给出调参建议。"
        if not warnings:
            warnings.append("评估数据不足")
        logger.info("推荐评估跳过：数据不足（%s）", "；".join(warnings))
        return report

    threshold_rows, weight_rows, recommended, current_row = sweep_parameters(
        samples,
        thresholds=thresholds,
        weight_grid=weight_grid,
        top_k=effective_top_k,
        current_min_score=current_min_score,
        current_similarity_weight=current_similarity_weight,
        current_trending_weight=current_trending_weight,
    )
    report["thresholds"] = threshold_rows
    report["weights"] = weight_rows
    report["recommended"] = recommended
    report["current"] = current_row
    report["metrics"] = {key: current_row[key] for key in _METRIC_KEYS}
    logger.info(
        "推荐评估完成: samples=%d current(F1=%.4f) recommended(minScore=%.2f simWeight=%.2f)",
        len(samples),
        current_row["f1"],
        recommended["minScore"],
        recommended["similarityWeight"],
    )
    return report
