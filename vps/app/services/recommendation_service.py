"""每日推荐生成服务（M3-05）。

流程：

1. 以收藏库（`my_repositories`）的平均向量构建用户画像；
2. 从热榜（`trending_repositories`）取候选，剔除已收藏仓库；
3. 相似度 + 热榜热度加权打分，按阈值过滤后取 top_k；
4. 以 `(user_id, repo_id)` 幂等更新推荐，未入选的旧 `new` 推荐标记 `expired`。

向量优先复用 M3-02 的 `repo_vectors`；缺失或模型 / 后端不兼容时现场编码并回写，
保证任务在向量化管线尚未跑过时也能独立完成。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import MyRepository, Recommendation, RepoVector, TrendingRepository, User
from app.services.embedding import EmbeddingService, get_embedding_service
from app.services.recommender import (
    Candidate,
    build_profile_vector,
    build_reason,
    rank_candidates,
)
from app.services.vector_pipeline import build_repo_text, text_digest

logger = logging.getLogger(__name__)

# 用户画像最多使用的收藏仓库数（按 stars 优先），避免超大收藏库拖慢每日任务
PROFILE_LIMIT = 1000
# SQLite 单条 SQL 的参数上限约 999，IN 查询按 200 分块
VECTOR_QUERY_CHUNK = 200


def _utcnow() -> datetime:
    """统一使用无时区 UTC 时间（与模型默认值一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _chunks(items: Sequence[str], size: int) -> Iterable[list[str]]:
    """把列表切成固定大小的小块。"""
    step = max(1, int(size))
    for start in range(0, len(items), step):
        yield list(items[start : start + step])


def _parse_vector(raw: str | None) -> list[float]:
    """解析 `repo_vectors.vector` 中的 JSON 数组；非法内容返回空列表。"""
    if not raw:
        return []
    try:
        values = json.loads(raw)
        if not isinstance(values, list):
            return []
        return [float(value) for value in values]
    except (TypeError, ValueError):
        return []


def _load_vector_rows(
    db: Session, source: str, repo_ids: Sequence[str]
) -> dict[str, RepoVector]:
    """按 id 分块读取 `repo_vectors`，返回 repo_id → 行。"""
    rows: dict[str, RepoVector] = {}
    for chunk in _chunks(list(repo_ids), VECTOR_QUERY_CHUNK):
        found = (
            db.execute(
                select(RepoVector).where(
                    RepoVector.source == source,
                    RepoVector.repo_id.in_(chunk),
                )
            )
            .scalars()
            .all()
        )
        for row in found:
            rows[row.repo_id] = row
    return rows


def _load_stored_vectors(
    db: Session,
    source: str,
    repo_ids: Sequence[str],
    service: EmbeddingService,
) -> dict[str, list[float]]:
    """读取与当前模型 / 后端兼容的已持久化向量。"""
    vectors: dict[str, list[float]] = {}
    for repo_id, row in _load_vector_rows(db, source, repo_ids).items():
        if row.model != service.model_name or row.backend != service.backend:
            continue
        vector = _parse_vector(row.vector)
        if vector:
            vectors[repo_id] = vector
    return vectors


def _encode_in_batches(
    service: EmbeddingService, texts: Sequence[str], batch_size: int
) -> list[list[float]]:
    """分批编码；单批失败只丢该批，保证每日任务可继续。"""
    vectors: list[list[float]] = []
    step = max(1, int(batch_size))
    for start in range(0, len(texts), step):
        batch = list(texts[start : start + step])
        try:
            encoded = service.encode(batch)
        except Exception:  # noqa: BLE001 - 单批编码失败降级为空向量
            logger.exception("推荐候选向量编码失败（batch=%d）", len(batch))
            encoded = []
        encoded = list(encoded)
        if len(encoded) < len(batch):
            encoded.extend([[] for _ in range(len(batch) - len(encoded))])
        vectors.extend(encoded[: len(batch)])
    return vectors


def ensure_repo_vectors(
    db: Session,
    source: str,
    rows: Sequence[Any],
    service: EmbeddingService,
    *,
    batch_size: int = 32,
) -> dict[str, list[float]]:
    """确保给定仓库都有可用向量：优先复用，缺失时编码并 upsert 回 `repo_vectors`。"""
    if not rows:
        return {}
    repo_ids = [row.id for row in rows]
    vectors = _load_stored_vectors(db, source, repo_ids, service)
    missing = [row for row in rows if row.id not in vectors]
    if not missing:
        return vectors

    texts = [build_repo_text(source, row) for row in missing]
    encoded = _encode_in_batches(service, texts, batch_size)
    existing = _load_vector_rows(db, source, [row.id for row in missing])

    for row, text, vector in zip(missing, texts, encoded):
        if not vector:
            continue
        vectors[row.id] = vector
        payload = json.dumps(
            [round(float(value), 6) for value in vector], separators=(",", ":")
        )
        digest = text_digest(text)
        previous = existing.get(row.id)
        if previous is None:
            db.add(
                RepoVector(
                    source=source,
                    repo_id=row.id,
                    model=service.model_name,
                    backend=service.backend,
                    dim=len(vector),
                    text_hash=digest,
                    vector=payload,
                )
            )
        else:
            previous.model = service.model_name
            previous.backend = service.backend
            previous.dim = len(vector)
            previous.text_hash = digest
            previous.vector = payload
            previous.updated_at = _utcnow()
    db.flush()
    return vectors


def _load_profile_rows(db: Session) -> list[MyRepository]:
    """取收藏库中 star 最多的前 N 条作为画像来源。"""
    return list(
        db.execute(
            select(MyRepository)
            .order_by(MyRepository.stars.desc(), MyRepository.id.asc())
            .limit(PROFILE_LIMIT)
        )
        .scalars()
        .all()
    )


def _load_candidates(
    db: Session, collected_ids: set[str], candidate_limit: int
) -> tuple[list[TrendingRepository], int]:
    """读取热榜候选并排除已收藏，返回 (候选列表, 被排除的已收藏数)。"""
    limit = max(1, int(candidate_limit))
    # 多取 len(collected_ids) 条，避免热门榜前列大量已收藏时候选不足。
    fetch_limit = limit + len(collected_ids)
    rows = list(
        db.execute(
            select(TrendingRepository)
            .order_by(TrendingRepository.stars_today.desc(), TrendingRepository.id.asc())
            .limit(fetch_limit)
        )
        .scalars()
        .all()
    )
    filtered = [row for row in rows if row.id not in collected_ids]
    excluded = len(rows) - len(filtered)
    return filtered[:limit], excluded


def _skipped(user_id: str, reason: str, *, top_k: int, min_score: float) -> dict[str, Any]:
    """构造跳过的用户级结果。"""
    return {
        "userId": user_id,
        "status": "skipped",
        "reason": reason,
        "created": 0,
        "updated": 0,
        "expired": 0,
        "selected": 0,
        "candidates": 0,
        "vectorizedCandidates": 0,
        "excludedCollected": 0,
        "belowThreshold": 0,
        "profileSize": 0,
        "minScore": round(min_score, 4),
        "topK": top_k,
    }


def generate_for_user(
    db: Session,
    user_id: str,
    *,
    service: Optional[EmbeddingService] = None,
    settings: Optional[Settings] = None,
    min_score: Optional[float] = None,
    top_k: Optional[int] = None,
    candidate_limit: Optional[int] = None,
) -> dict[str, Any]:
    """为单个用户生成一轮推荐（幂等，可重复执行）。"""
    config = settings or get_settings()
    embedding = service or get_embedding_service()
    effective_top_k = max(1, int(top_k if top_k is not None else config.RECOMMEND_DAILY_TOP_K))
    effective_min_score = float(
        config.RECOMMEND_MIN_SCORE if min_score is None else min_score
    )
    effective_min_score = max(0.0, min(1.0, effective_min_score))
    effective_candidate_limit = max(
        1,
        int(
            candidate_limit
            if candidate_limit is not None
            else config.RECOMMEND_CANDIDATE_LIMIT
        ),
    )

    profile_rows = _load_profile_rows(db)
    if not profile_rows:
        return _skipped(
            user_id,
            "本地没有仓库数据，无法构建用户画像",
            top_k=effective_top_k,
            min_score=effective_min_score,
        )

    profile_vectors = ensure_repo_vectors(
        db,
        "my",
        profile_rows,
        embedding,
        batch_size=config.VECTORIZE_BATCH_SIZE,
    )
    profile_vec = build_profile_vector(
        [profile_vectors.get(row.id, []) for row in profile_rows]
    )
    if not profile_vec:
        return _skipped(
            user_id,
            "收藏库向量为空，无法构建用户画像",
            top_k=effective_top_k,
            min_score=effective_min_score,
        )

    collected_ids = set(db.execute(select(MyRepository.id)).scalars().all())
    candidates, excluded_collected = _load_candidates(
        db, collected_ids, effective_candidate_limit
    )
    if not candidates:
        return _skipped(
            user_id,
            "热榜数据为空，请先执行 crawl-trending",
            top_k=effective_top_k,
            min_score=effective_min_score,
        )

    candidate_vectors = ensure_repo_vectors(
        db,
        "trending",
        candidates,
        embedding,
        batch_size=config.VECTORIZE_BATCH_SIZE,
    )
    usable_candidates = [row for row in candidates if candidate_vectors.get(row.id)]
    if not usable_candidates:
        # 编码整体失败时不要清空已有推荐，保留上一轮结果等待下次重试。
        return _skipped(
            user_id,
            "候选向量为空，跳过本轮推荐",
            top_k=effective_top_k,
            min_score=effective_min_score,
        )

    ranked = rank_candidates(
        profile_vec,
        [
            Candidate(
                repo_id=row.id,
                vector=candidate_vectors.get(row.id, []),
                stars_today=int(row.stars_today or 0),
            )
            for row in usable_candidates
        ],
        collected_ids=collected_ids,
        min_score=effective_min_score,
        top_k=effective_top_k,
        similarity_weight=config.RECOMMEND_SIMILARITY_WEIGHT,
        trending_weight=config.RECOMMEND_TRENDING_WEIGHT,
    )

    by_id = {row.id: row for row in candidates}
    existing_rows = list(
        db.execute(
            select(Recommendation).where(Recommendation.user_id == user_id)
        )
        .scalars()
        .all()
    )
    existing_by_repo = {row.repo_id: row for row in existing_rows}
    selected_ids = {item.repo_id for item in ranked}

    created = 0
    updated = 0
    expired = 0
    now = _utcnow()
    for item in ranked:
        repo = by_id.get(item.repo_id)
        if repo is None:
            continue
        reason = build_reason(repo, item.score, similarity=item.similarity)
        existing = existing_by_repo.get(item.repo_id)
        if existing is None:
            db.add(
                Recommendation(
                    id=uuid4().hex,
                    user_id=user_id,
                    repo_id=item.repo_id,
                    score=round(float(item.score), 6),
                    reason=reason,
                    status="new",
                    created_at=now,
                )
            )
            created += 1
            continue

        existing.score = round(float(item.score), 6)
        existing.reason = reason
        # 只有 new / expired 可以被重新激活；saved / dismissed / pushed 保留用户反馈。
        if existing.status in ("new", "expired"):
            existing.status = "new"
        updated += 1

    for row in existing_rows:
        if row.status != "new":
            continue
        if row.repo_id in collected_ids or row.repo_id not in selected_ids:
            row.status = "expired"
            expired += 1

    db.commit()
    return {
        "userId": user_id,
        "status": "ok",
        "created": created,
        "updated": updated,
        "expired": expired,
        "selected": len(ranked),
        "candidates": len(candidates),
        "vectorizedCandidates": len(usable_candidates),
        "excludedCollected": excluded_collected,
        "belowThreshold": max(0, len(usable_candidates) - len(ranked)),
        "profileSize": len(profile_vectors),
        "minScore": round(effective_min_score, 4),
        "topK": effective_top_k,
    }


def generate_daily_recommendations(
    db: Session,
    user_id: Optional[str] = None,
    *,
    service: Optional[EmbeddingService] = None,
    settings: Optional[Settings] = None,
    min_score: Optional[float] = None,
    top_k: Optional[int] = None,
    candidate_limit: Optional[int] = None,
) -> dict[str, Any]:
    """每日推荐入口：指定用户 → 全部用户 → 兜底创建 default 用户。"""
    config = settings or get_settings()
    embedding = service or get_embedding_service()

    if user_id:
        target_users = [user_id]
    else:
        target_users = [
            str(item) for item in db.execute(select(User.id)).scalars().all()
        ]
        if not target_users:
            if db.get(User, "default") is None:
                db.add(User(id="default", username="default"))
                db.commit()
            target_users = ["default"]

    results: list[dict[str, Any]] = []
    for uid in target_users:
        try:
            results.append(
                generate_for_user(
                    db,
                    uid,
                    service=embedding,
                    settings=config,
                    min_score=min_score,
                    top_k=top_k,
                    candidate_limit=candidate_limit,
                )
            )
        except Exception as exc:  # noqa: BLE001 - 单用户失败不拖垮整轮任务
            db.rollback()
            logger.exception("推荐生成失败（user=%s）", uid)
            results.append(
                {
                    "userId": uid,
                    "status": "error",
                    "error": str(exc)[:300],
                    "created": 0,
                    "updated": 0,
                    "expired": 0,
                    "selected": 0,
                    "candidates": 0,
                    "vectorizedCandidates": 0,
                    "excludedCollected": 0,
                    "belowThreshold": 0,
                    "profileSize": 0,
                    "minScore": 0.0,
                    "topK": 0,
                }
            )

    ok_results = [item for item in results if item.get("status") == "ok"]
    error_results = [item for item in results if item.get("status") == "error"]
    if ok_results:
        status = "ok"
    elif error_results:
        status = "error"
    else:
        status = "skipped"

    effective_top_k = max(
        1, int(top_k if top_k is not None else config.RECOMMEND_DAILY_TOP_K)
    )
    effective_min_score = float(
        config.RECOMMEND_MIN_SCORE if min_score is None else min_score
    )
    summary = {
        "status": status,
        "users": target_users,
        "userCount": len(target_users),
        "created": sum(int(item.get("created", 0)) for item in results),
        "updated": sum(int(item.get("updated", 0)) for item in results),
        "expired": sum(int(item.get("expired", 0)) for item in results),
        "selected": sum(int(item.get("selected", 0)) for item in results),
        "minScore": round(max(0.0, min(1.0, effective_min_score)), 4),
        "topK": effective_top_k,
        "results": results,
    }
    logger.info(
        "每日推荐生成完成: status=%s users=%d created=%d updated=%d expired=%d",
        status,
        len(target_users),
        summary["created"],
        summary["updated"],
        summary["expired"],
    )
    return summary
