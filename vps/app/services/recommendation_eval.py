"""每日推荐评估（M4-01）。

职责：

- 对每日生成的推荐计算「质量分」，并施加「匹配度阈值」硬门槛；
- 通过者标记 `qualified`（可推送），未通过者标记 `filtered`；
- 每次运行写入 `recommendation_evaluation_runs`，保留阈值与计数，便于审计与调参。

质量分口径（与匹配度分离）：

    quality = repo_quality × 0.7 + reason_quality × 0.3

- `repo_quality`：仓库内容完整度（简介 / 技术栈 / 今日 Star / README 摘要 / 语言）；
- `reason_quality`：推荐理由的完整度与依据覆盖；
- `match_score`：原始余弦相似度，作为独立硬门槛（`EVAL_MATCH_THRESHOLD`）。

全部计算为本地规则，不访问网络、不加载模型，测试可完全离线。
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Recommendation, RecommendationEvaluationRun, TrendingRepository, User

logger = logging.getLogger(__name__)

# 评估只处理「评估态」记录；用户反馈 / 已推送 / 已过期记录保持原状
EVALUATABLE_STATUSES: tuple[str, ...] = ("new", "qualified", "filtered")
# SQLite IN 查询分块，避免参数过多
QUERY_CHUNK = 200
# 质量分中仓库 / 理由的权重
REPO_QUALITY_WEIGHT = 0.7
REASON_QUALITY_WEIGHT = 0.3


def _utcnow() -> datetime:
    """统一使用无时区 UTC 时间（与模型默认值一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _chunks(items: Sequence[str], size: int = QUERY_CHUNK) -> Iterable[list[str]]:
    step = max(1, int(size))
    for start in range(0, len(items), step):
        yield list(items[start : start + step])


def clamp01(value: Any, default: float = 0.0) -> float:
    """把任意数值裁剪到 0~1；非法值返回默认值。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, float(default)))
    if math.isnan(number) or math.isinf(number):
        return max(0.0, min(1.0, float(default)))
    return max(0.0, min(1.0, number))


def score_reason_quality(reason: Optional[str]) -> float:
    """推荐理由质量：长度分档 + 依据关键词覆盖，结果 0~1。"""
    text = str(reason or "").strip()
    if not text:
        return 0.0
    score = 0.35
    length = len(text)
    if length >= 30:
        score += 0.20
    if length >= 60:
        score += 0.20
    if length >= 100:
        score += 0.10
    if "相似度" in text:
        score += 0.05
    if "主要使用" in text or "技术栈" in text:
        score += 0.05
    if "项目简介" in text:
        score += 0.05
    return round(clamp01(score), 6)


def _field(repo: Any, key: str, default: Any = None) -> Any:
    """兼容 SQLAlchemy 模型 / dict / 任意对象的字段读取。"""
    if isinstance(repo, dict):
        value = repo.get(key)
    else:
        value = getattr(repo, key, None)
    return default if value is None else value


def score_repo_quality(repo: Any) -> float:
    """仓库内容质量：简介 / 技术栈 / 今日 Star / README 摘要 / 语言，结果 0~1。

    字段缺失按 0 计；热榜表没有的列（如 `readme_summary`）不会导致异常。
    """
    if repo is None:
        return 0.0
    score = 0.0
    if str(_field(repo, "name", "")).strip():
        score += 0.05

    description = str(_field(repo, "description", "") or "").strip()
    if description:
        score += 0.35 * min(len(description) / 80.0, 1.0)

    tech_stack = str(_field(repo, "tech_stack", "") or "").strip()
    if tech_stack:
        score += 0.15 + 0.10 * min(len(tech_stack) / 40.0, 1.0)

    try:
        stars_today = max(0, int(_field(repo, "stars_today", 0) or 0))
    except (TypeError, ValueError):
        stars_today = 0
    if stars_today:
        score += 0.25 * min(math.log1p(stars_today) / math.log1p(1000), 1.0)

    summary = str(_field(repo, "readme_summary", "") or "").strip()
    if summary:
        score += 0.10 * min(len(summary) / 100.0, 1.0)

    if str(_field(repo, "language", "") or "").strip():
        score += 0.05
    return round(clamp01(score), 6)


def compute_quality_score(
    repo_quality: float,
    reason_quality: float,
    *,
    repo_weight: float = REPO_QUALITY_WEIGHT,
    reason_weight: float = REASON_QUALITY_WEIGHT,
) -> float:
    """按仓库 / 理由权重合成质量分；权重都为 0 时退化为仓库质量。"""
    repo_w = max(0.0, float(repo_weight))
    reason_w = max(0.0, float(reason_weight))
    total = repo_w + reason_w
    if total <= 0:
        return round(clamp01(repo_quality), 6)
    value = (clamp01(repo_quality) * repo_w + clamp01(reason_quality) * reason_w) / total
    return round(clamp01(value), 6)


@dataclass(frozen=True)
class EvaluationResult:
    """单条推荐的评估结果。"""

    passed: bool
    match_score: float
    quality_score: float
    repo_quality: float
    reason_quality: float
    detail: dict[str, Any] = field(default_factory=dict)


def evaluate_candidate(
    *,
    match_score: float,
    repo: Any,
    reason: Optional[str],
    match_threshold: float,
    quality_threshold: float,
    repo_weight: float = REPO_QUALITY_WEIGHT,
    reason_weight: float = REASON_QUALITY_WEIGHT,
) -> EvaluationResult:
    """评估单条推荐：匹配度硬门槛 + 质量分门槛，两者都过才算合格。"""
    match = clamp01(match_score)
    repo_score = score_repo_quality(repo)
    reason_score = score_reason_quality(reason)
    quality = compute_quality_score(
        repo_score,
        reason_score,
        repo_weight=repo_weight,
        reason_weight=reason_weight,
    )
    match_ok = match + 1e-12 >= clamp01(match_threshold)
    quality_ok = quality + 1e-12 >= clamp01(quality_threshold)
    passed = match_ok and quality_ok
    detail = {
        "match": round(match, 6),
        "repo": repo_score,
        "reason": reason_score,
        "quality": quality,
        "matchThreshold": round(clamp01(match_threshold), 6),
        "qualityThreshold": round(clamp01(quality_threshold), 6),
        "matchPassed": match_ok,
        "qualityPassed": quality_ok,
        "passed": passed,
    }
    return EvaluationResult(
        passed=passed,
        match_score=round(match, 6),
        quality_score=quality,
        repo_quality=repo_score,
        reason_quality=reason_score,
        detail=detail,
    )


def _load_repos(db: Session, repo_ids: Sequence[str]) -> dict[str, TrendingRepository]:
    """按 id 分块读取热榜仓库，返回 repo_id → 行。"""
    repos: dict[str, TrendingRepository] = {}
    for chunk in _chunks(list(dict.fromkeys(repo_ids))):
        rows = (
            db.execute(select(TrendingRepository).where(TrendingRepository.id.in_(chunk)))
            .scalars()
            .all()
        )
        for row in rows:
            repos[row.id] = row
    return repos


def _resolve_users(db: Session, user_id: Optional[str]) -> list[str]:
    """解析本次评估的目标用户；全部用户为空时兜底 default。"""
    if user_id:
        return [str(user_id)]
    users = [str(item) for item in db.execute(select(User.id)).scalars().all()]
    if users:
        return users
    if db.get(User, "default") is None:
        db.add(User(id="default", username="default"))
        db.commit()
    return ["default"]


def _effective_threshold(value: Optional[float], default: float) -> float:
    if value is None:
        return clamp01(default)
    return clamp01(value, default=default)


def create_run(
    db: Session,
    *,
    user_id: Optional[str],
    match_threshold: float,
    quality_threshold: float,
) -> RecommendationEvaluationRun:
    """创建一条评估运行记录（running）。"""
    run = RecommendationEvaluationRun(
        id=uuid4().hex,
        user_id=user_id,
        status="running",
        match_threshold=round(clamp01(match_threshold), 6),
        quality_threshold=round(clamp01(quality_threshold), 6),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def evaluate_for_user(
    db: Session,
    user_id: str,
    *,
    run: RecommendationEvaluationRun,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """评估单个用户的推荐，返回该用户的计数摘要。"""
    config = settings or get_settings()
    rows = list(
        db.execute(
            select(Recommendation)
            .where(
                Recommendation.user_id == user_id,
                Recommendation.status.in_(EVALUATABLE_STATUSES),
            )
            .order_by(Recommendation.score.desc(), Recommendation.id.asc())
        )
        .scalars()
        .all()
    )
    if not rows:
        return {
            "userId": user_id,
            "status": "skipped",
            "reason": "没有待评估的推荐",
            "total": 0,
            "qualified": 0,
            "filtered": 0,
            "skipped": 0,
            "failed": 0,
        }

    repos = _load_repos(db, [row.repo_id for row in rows])
    now = _utcnow()
    qualified = 0
    filtered = 0
    skipped = 0
    for row in rows:
        repo = repos.get(row.repo_id)
        if repo is None:
            # 热榜已清理 / 仓库被删除：不改变状态，计入跳过，等待下一轮
            skipped += 1
            continue
        # 生成任务会写入原始相似度；历史数据没有该列时回退到综合分（保守近似）
        match = row.match_score if float(row.match_score or 0.0) > 0 else float(row.score or 0.0)
        result = evaluate_candidate(
            match_score=match,
            repo=repo,
            reason=row.reason,
            match_threshold=run.match_threshold,
            quality_threshold=run.quality_threshold,
            repo_weight=config.EVAL_REPO_WEIGHT,
            reason_weight=config.EVAL_REASON_WEIGHT,
        )
        row.match_score = result.match_score
        row.quality_score = result.quality_score
        row.quality_detail = json.dumps(result.detail, ensure_ascii=False, separators=(",", ":"))
        row.evaluation_run_id = run.id
        row.evaluated_at = now
        row.status = "qualified" if result.passed else "filtered"
        if result.passed:
            qualified += 1
        else:
            filtered += 1

    db.commit()
    return {
        "userId": user_id,
        "status": "ok",
        "total": len(rows),
        "qualified": qualified,
        "filtered": filtered,
        "skipped": skipped,
        "failed": 0,
    }


def evaluate_daily(
    db: Session,
    user_id: Optional[str] = None,
    *,
    settings: Optional[Settings] = None,
    match_threshold: Optional[float] = None,
    quality_threshold: Optional[float] = None,
) -> dict[str, Any]:
    """每日评估入口：指定用户 → 全部用户 → 兜底 default。

    单用户异常只回滚该用户并计入 failed，不拖垮整轮评估。
    """
    config = settings or get_settings()
    effective_match = _effective_threshold(match_threshold, config.EVAL_MATCH_THRESHOLD)
    effective_quality = _effective_threshold(quality_threshold, config.EVAL_QUALITY_THRESHOLD)
    run = create_run(
        db,
        user_id=user_id,
        match_threshold=effective_match,
        quality_threshold=effective_quality,
    )

    users = _resolve_users(db, user_id)
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for uid in users:
        try:
            results.append(evaluate_for_user(db, uid, run=run, settings=config))
        except Exception as exc:  # noqa: BLE001 - 单用户失败不拖垮整轮
            db.rollback()
            logger.exception("推荐评估失败（user=%s）", uid)
            errors.append(f"{uid}: {str(exc)[:200]}")
            results.append(
                {
                    "userId": uid,
                    "status": "error",
                    "error": str(exc)[:300],
                    "total": 0,
                    "qualified": 0,
                    "filtered": 0,
                    "skipped": 0,
                    "failed": 1,
                }
            )

    run.total = sum(int(item.get("total", 0)) for item in results)
    run.qualified = sum(int(item.get("qualified", 0)) for item in results)
    run.filtered = sum(int(item.get("filtered", 0)) for item in results)
    run.skipped = sum(int(item.get("skipped", 0)) for item in results)
    run.failed = sum(int(item.get("failed", 0)) for item in results)
    # 全部用户都失败才把整轮标记 failed；部分失败保留 completed + error 明细
    run.status = "failed" if errors and len(errors) == len(results) else "completed"
    run.error = "；".join(errors)[:1000] or None
    run.finished_at = _utcnow()
    db.add(run)
    db.commit()

    summary = {
        "runId": run.id,
        "status": run.status,
        "userId": user_id,
        "users": users,
        "userCount": len(users),
        "total": run.total,
        "qualified": run.qualified,
        "filtered": run.filtered,
        "skipped": run.skipped,
        "failed": run.failed,
        "matchThreshold": run.match_threshold,
        "qualityThreshold": run.quality_threshold,
        "results": results,
    }
    logger.info(
        "每日推荐评估完成: run=%s users=%d total=%d qualified=%d filtered=%d skipped=%d",
        run.id,
        len(users),
        run.total,
        run.qualified,
        run.filtered,
        run.skipped,
    )
    return summary


def get_run(db: Session, run_id: str) -> Optional[RecommendationEvaluationRun]:
    """按 id 查询评估运行。"""
    return db.get(RecommendationEvaluationRun, run_id)


def list_runs(db: Session, limit: int = 20) -> list[RecommendationEvaluationRun]:
    """按创建时间倒序返回最近评估运行。"""
    return list(
        db.execute(
            select(RecommendationEvaluationRun)
            .order_by(RecommendationEvaluationRun.created_at.desc())
            .limit(max(1, min(int(limit), 100)))
        )
        .scalars()
        .all()
    )


def list_qualified(
    db: Session,
    *,
    user_id: Optional[str] = None,
    limit: int = 50,
) -> list[Recommendation]:
    """查询通过评估、等待推送的推荐（M4-02 通知中心的输入）。"""
    stmt = select(Recommendation).where(Recommendation.status == "qualified")
    if user_id:
        stmt = stmt.where(Recommendation.user_id == user_id)
    stmt = stmt.order_by(Recommendation.quality_score.desc(), Recommendation.score.desc())
    return list(db.execute(stmt.limit(max(1, min(int(limit), 200)))).scalars().all())
