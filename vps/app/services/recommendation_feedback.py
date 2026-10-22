"""推荐反馈回流（M3-07）。

职责：

- `fetch_feedback`：从 edge 内部接口读取用户的 `saved` / `dismissed` / `clicked` 反馈；
- `push_recommendations`：把 VPS 生成的推荐快照回写到 edge D1，供推荐页展示；
- `load_local_feedback` / `merge_exclusions`：edge 不可达时的本地降级与集合合并。

所有网络调用都是可选增强：未配置 `EDGE_BASE_URL` / `INTERNAL_TOKEN`、网络失败或
接口返回异常时返回空结果 / 0，不阻塞推荐生成主流程。测试使用 `httpx.MockTransport`，
不访问网络。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import MyRepository, Recommendation, TrendingRepository

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10.0
_MAX_PUSH_ITEMS = 500
_STATUSES = {"new", "saved", "dismissed", "pushed", "expired"}


@dataclass
class FeedbackSnapshot:
    """一次反馈读取的结果（edge 优先，本地降级）。"""

    user_id: str
    saved_repo_ids: list[str] = field(default_factory=list)
    dismissed_repo_ids: list[str] = field(default_factory=list)
    clicked_repo_ids: list[str] = field(default_factory=list)
    source: str = "unavailable"

    @property
    def excluded_repo_ids(self) -> set[str]:
        """生成推荐时需要排除的仓库（已收藏 + 已忽略）。"""
        return set(self.saved_repo_ids) | set(self.dismissed_repo_ids)


def _dedupe_sorted(values: Iterable[str]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def merge_exclusions(*groups: Iterable[str]) -> set[str]:
    """合并多组仓库 id（去空、去重）。"""
    merged: set[str] = set()
    for group in groups:
        for value in group:
            item = str(value).strip()
            if item:
                merged.add(item)
    return merged


def load_local_feedback(db: Session, user_id: str) -> FeedbackSnapshot:
    """读取本地推荐状态作为 edge 不可达时的兜底反馈。"""
    rows = list(
        db.execute(
            select(Recommendation).where(
                Recommendation.user_id == user_id,
                Recommendation.status.in_(("saved", "dismissed")),
            )
        )
        .scalars()
        .all()
    )
    saved = [row.repo_id for row in rows if row.status == "saved"]
    dismissed = [row.repo_id for row in rows if row.status == "dismissed"]
    return FeedbackSnapshot(
        user_id=user_id,
        saved_repo_ids=_dedupe_sorted(saved),
        dismissed_repo_ids=_dedupe_sorted(dismissed),
        source="local",
    )


class EdgeRecommendationClient:
    """edge 内部推荐接口客户端（同步 httpx）。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = _TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.timeout = max(1.0, float(timeout))
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Optional[Settings] = None) -> Optional["EdgeRecommendationClient"]:
        """未配置地址或令牌时返回 None（功能关闭）。"""
        cfg = settings or get_settings()
        base_url = (cfg.EDGE_BASE_URL or "").strip()
        token = (cfg.INTERNAL_TOKEN or "").strip()
        if not base_url or not token:
            return None
        return cls(base_url, token)

    def _headers(self) -> dict[str, str]:
        return {"X-Internal-Token": self.token, "Content-Type": "application/json"}

    def fetch_feedback(self, user_id: str) -> FeedbackSnapshot:
        """读取 edge 反馈；异常向上抛出，由调用方决定降级。"""
        with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
            response = client.get(
                f"{self.base_url}/api/internal/recommendations/feedback",
                params={"userId": user_id},
                headers=self._headers(),
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("edge 反馈响应不是对象")
        return FeedbackSnapshot(
            user_id=user_id,
            saved_repo_ids=_dedupe_sorted(payload.get("savedRepoIds") or []),
            dismissed_repo_ids=_dedupe_sorted(payload.get("dismissedRepoIds") or []),
            clicked_repo_ids=_dedupe_sorted(payload.get("clickedRepoIds") or []),
            source="edge",
        )

    def push_recommendations(self, user_id: str, items: Sequence[dict[str, Any]]) -> int:
        """把推荐快照写入 edge；返回成功条数。异常向上抛出。"""
        if not items:
            return 0
        with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
            response = client.post(
                f"{self.base_url}/api/internal/recommendations/upsert",
                json={"userId": user_id, "items": list(items)[:_MAX_PUSH_ITEMS]},
                headers=self._headers(),
            )
        response.raise_for_status()
        payload = response.json()
        return int(payload.get("count", 0)) if isinstance(payload, dict) else 0


def fetch_feedback(
    db: Session,
    user_id: str,
    *,
    settings: Optional[Settings] = None,
    client: Optional[EdgeRecommendationClient] = None,
) -> FeedbackSnapshot:
    """读取用户反馈：edge 优先，失败时合并本地兜底并标记 `source=local`。"""
    cfg = settings or get_settings()
    if not bool(getattr(cfg, "RECOMMEND_FEEDBACK_SYNC", True)):
        return load_local_feedback(db, user_id)

    edge_client = client or EdgeRecommendationClient.from_settings(cfg)
    if edge_client is None:
        return load_local_feedback(db, user_id)

    try:
        snapshot = edge_client.fetch_feedback(user_id)
    except Exception as exc:  # noqa: BLE001 - 反馈读取失败不影响生成
        logger.warning("读取 edge 推荐反馈失败（user=%s）：%s", user_id, exc)
        return load_local_feedback(db, user_id)

    local = load_local_feedback(db, user_id)
    snapshot.saved_repo_ids = _dedupe_sorted(
        list(snapshot.saved_repo_ids) + list(local.saved_repo_ids)
    )
    snapshot.dismissed_repo_ids = _dedupe_sorted(
        list(snapshot.dismissed_repo_ids) + list(local.dismissed_repo_ids)
    )
    snapshot.clicked_repo_ids = _dedupe_sorted(
        list(snapshot.clicked_repo_ids) + list(local.clicked_repo_ids)
    )
    return snapshot


def _snapshot_maps(
    db: Session, repo_ids: Sequence[str]
) -> tuple[dict[str, TrendingRepository], dict[str, MyRepository]]:
    """批量读取推荐对应的热榜 / 收藏仓库快照。"""
    ids = _dedupe_sorted(repo_ids)
    if not ids:
        return {}, {}
    trending = {
        row.id: row
        for row in db.execute(
            select(TrendingRepository).where(TrendingRepository.id.in_(ids))
        )
        .scalars()
        .all()
    }
    mine = {
        row.id: row
        for row in db.execute(select(MyRepository).where(MyRepository.id.in_(ids)))
        .scalars()
        .all()
    }
    return trending, mine


def _parse_based_on(raw: Optional[str]) -> list[str]:
    """把本地 `based_on` JSON 字符串解析为 edge 需要的数组；非法值返回空列表。"""
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(values, list):
        return []
    return [str(item) for item in values if str(item).strip()]


def _parse_detail(raw: Optional[str]) -> dict[str, Any] | None:
    """解析精排明细 JSON；非法值返回 None。"""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def build_push_items(db: Session, user_id: str) -> list[dict[str, Any]]:
    """把用户本地推荐转换为 edge upsert 契约。"""
    rows = list(
        db.execute(select(Recommendation).where(Recommendation.user_id == user_id))
        .scalars()
        .all()
    )
    if not rows:
        return []
    trending, mine = _snapshot_maps(db, [row.repo_id for row in rows])

    items: list[dict[str, Any]] = []
    for row in rows:
        repo_id = str(row.repo_id or "").strip()
        if not repo_id:
            continue
        repo = trending.get(repo_id) or mine.get(repo_id)
        owner = (getattr(repo, "owner", None) or repo_id.split("/")[0] or "").strip()
        name = (getattr(repo, "name", None) or (repo_id.split("/")[1] if "/" in repo_id else repo_id)).strip()
        status = row.status if row.status in _STATUSES else "new"
        items.append(
            {
                "id": row.id,
                "repoId": repo_id,
                "score": round(float(row.score or 0), 6),
                "baseScore": round(float(getattr(row, "base_score", 0) or 0), 6),
                "rerankScore": round(float(getattr(row, "rerank_score", 0) or 0), 6),
                "rerankRank": getattr(row, "rerank_rank", None),
                "rerankDetail": _parse_detail(getattr(row, "rerank_detail", None)),
                "reason": row.reason or "",
                "basedOn": _parse_based_on(getattr(row, "based_on", None)),
                "owner": owner or None,
                "name": name or None,
                "description": getattr(repo, "description", None) or "",
                "language": getattr(repo, "language", None) or "",
                "stars": int(getattr(repo, "stars", 0) or 0),
                "url": getattr(repo, "html_url", None) or f"https://github.com/{repo_id}",
                "status": status,
            }
        )
    return items


def push_recommendations(
    db: Session,
    user_id: str,
    *,
    settings: Optional[Settings] = None,
    client: Optional[EdgeRecommendationClient] = None,
) -> int:
    """把本地推荐回写 edge；失败只记日志并返回 0。"""
    cfg = settings or get_settings()
    if not bool(getattr(cfg, "RECOMMEND_FEEDBACK_SYNC", True)):
        return 0
    edge_client = client or EdgeRecommendationClient.from_settings(cfg)
    if edge_client is None:
        return 0

    items = build_push_items(db, user_id)
    if not items:
        return 0
    try:
        return edge_client.push_recommendations(user_id, items)
    except Exception as exc:  # noqa: BLE001 - 回写失败不影响本地任务
        logger.warning("回写 edge 推荐失败（user=%s）：%s", user_id, exc)
        return 0


def feedback_stats(db: Session, user_id: str) -> dict[str, Any]:
    """本地反馈统计（用于任务返回值 / 调试）。"""
    rows = list(
        db.execute(select(Recommendation).where(Recommendation.user_id == user_id))
        .scalars()
        .all()
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status or "new"] = counts.get(row.status or "new", 0) + 1
    return {"userId": user_id, "total": len(rows), "statuses": counts}
