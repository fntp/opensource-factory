"""项目健康度（M6-05）：最后提交 / issue 活跃 / 归档标记。

设计：
- `evaluate_health` 是纯函数：按最后提交距今天数分档，用未关闭 issue 占 Star 比例做小幅修正，
  归档 / 禁用 / 缺失时间有明确优先级，输出可解释的中文 reasons；
- `refresh_repositories` 从 GitHub 拉取仓库元数据并更新 VPS 本地镜像（fetcher 可注入，测试不联网）；
- `push_health_to_edge` 把健康度快照批量回写 D1（`POST {edge}/api/repos/health`）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MyRepository

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "active"
STATUS_ATTENTION = "attention"
STATUS_STALE = "stale"
STATUS_ARCHIVED = "archived"
STATUS_UNKNOWN = "unknown"

STATUS_LABELS: dict[str, str] = {
    STATUS_ACTIVE: "活跃",
    STATUS_ATTENTION: "需关注",
    STATUS_STALE: "停滞",
    STATUS_ARCHIVED: "已归档",
    STATUS_UNKNOWN: "未知",
}

DEFAULT_ACTIVE_DAYS = 90
DEFAULT_ATTENTION_DAYS = 180
DEFAULT_STALE_DAYS = 365
DEFAULT_MAX_PER_RUN = 200

RepoFetcher = Callable[[str], Awaitable[Optional[dict[str, Any]]]]


def utcnow() -> datetime:
    """与项目其他模块一致：无时区 UTC 时间。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat() + "Z"


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


def normalize_status(value: Any) -> str:
    """把任意输入归一为合法健康度状态。"""
    text = str(value or "").strip().lower()
    if text in STATUS_LABELS:
        return text
    return STATUS_UNKNOWN


@dataclass(frozen=True)
class HealthSnapshot:
    """单个仓库的健康度快照。"""

    status: str
    score: int
    label: str
    last_push_at: datetime | None
    days_since_push: int | None
    open_issues: int
    archived: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(
        self,
        *,
        repo_id: str | None = None,
        name: str | None = None,
        html_url: str | None = None,
        language: str | None = None,
        stars: int = 0,
        checked_at: datetime | None = None,
    ) -> dict[str, Any]:
        """转换为 edge / admin 使用的 camelCase 结构。"""
        payload: dict[str, Any] = {
            "status": self.status,
            "label": self.label,
            "score": self.score,
            "lastPushAt": _iso(self.last_push_at),
            "daysSincePush": self.days_since_push,
            "openIssues": self.open_issues,
            "archived": self.archived,
            "reasons": list(self.reasons),
            "checkedAt": _iso(checked_at),
        }
        if repo_id is not None:
            payload.update(
                {
                    "repoId": repo_id,
                    "name": name or repo_id.split("/")[-1],
                    "htmlUrl": html_url or "",
                    "language": language,
                    "stars": int(stars or 0),
                }
            )
        return payload


def evaluate_health(
    *,
    pushed_at: datetime | None,
    open_issues_count: int = 0,
    archived: bool = False,
    disabled: bool = False,
    stars: int = 0,
    now: datetime | None = None,
    active_days: int = DEFAULT_ACTIVE_DAYS,
    attention_days: int = DEFAULT_ATTENTION_DAYS,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> HealthSnapshot:
    """计算健康度。

    优先级：归档 > 禁用 > 缺失最后提交时间 > 按天数分档。
    分数只用于排序与展示，状态由天数分档决定，避免 issue 扣分把「活跃」误判成「停滞」。
    """
    current = now or utcnow()
    active = max(1, int(active_days))
    attention = max(active, int(attention_days))
    stale = max(attention, int(stale_days))
    issues = max(0, int(open_issues_count or 0))

    if archived:
        return HealthSnapshot(
            status=STATUS_ARCHIVED,
            score=0,
            label=STATUS_LABELS[STATUS_ARCHIVED],
            last_push_at=pushed_at,
            days_since_push=None,
            open_issues=issues,
            archived=True,
            reasons=("仓库已归档，不再接收更新",),
        )

    days: int | None = None
    if pushed_at is not None:
        delta = current - pushed_at
        days = max(0, delta.days)

    if days is None:
        return HealthSnapshot(
            status=STATUS_UNKNOWN,
            score=0,
            label=STATUS_LABELS[STATUS_UNKNOWN],
            last_push_at=None,
            days_since_push=None,
            open_issues=issues,
            archived=False,
            reasons=("缺少最后提交时间，无法判断活跃度",),
        )

    if days <= active:
        status = STATUS_ACTIVE
        score = 100
    elif days <= attention:
        status = STATUS_ATTENTION
        score = 70
    elif days <= stale:
        status = STATUS_STALE
        score = 45
    else:
        status = STATUS_STALE
        score = 20

    if issues <= 0:
        score += 5
        issue_reason = "当前没有未关闭 issue"
    else:
        ratio = issues / max(1, int(stars or 0))
        if ratio >= 0.5:
            score -= 20
            issue_reason = f"存在 {issues} 个未关闭 issue / PR（占 Star {ratio:.0%}），需关注维护压力"
        elif ratio >= 0.2:
            score -= 10
            issue_reason = f"存在 {issues} 个未关闭 issue / PR（占 Star {ratio:.0%}）"
        else:
            issue_reason = f"存在 {issues} 个未关闭 issue / PR"

    reasons: list[str] = [f"最后提交于 {days} 天前"]
    if disabled:
        score = min(score, 30)
        status = STATUS_STALE
        reasons.append("仓库已被 GitHub 禁用")
    if days > attention:
        reasons.append(f"超过 {attention} 天无提交，建议评估是否仍在使用")
    reasons.append(issue_reason)

    return HealthSnapshot(
        status=status,
        score=_clamp(score),
        label=STATUS_LABELS[status],
        last_push_at=pushed_at,
        days_since_push=days,
        open_issues=issues,
        archived=False,
        reasons=tuple(reasons),
    )


def snapshot_for_row(row: MyRepository, *, now: datetime | None = None) -> HealthSnapshot:
    """从本地镜像行计算健康度（读取已落库的 GitHub 元数据）。"""
    return evaluate_health(
        pushed_at=row.pushed_at,
        open_issues_count=row.open_issues_count or 0,
        archived=bool(row.archived),
        disabled=bool(row.disabled),
        stars=row.stars or 0,
        now=now,
    )


def summarize_health(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """汇总健康度条目：各状态计数 + 平均分。"""
    rows = list(items)
    summary: dict[str, Any] = {
        "total": len(rows),
        STATUS_ACTIVE: 0,
        STATUS_ATTENTION: 0,
        STATUS_STALE: 0,
        STATUS_ARCHIVED: 0,
        STATUS_UNKNOWN: 0,
        "averageScore": 0.0,
    }
    scores: list[int] = []
    for item in rows:
        status = normalize_status(item.get("status"))
        summary[status] = int(summary.get(status, 0)) + 1
        if item.get("score") is not None:
            scores.append(int(item["score"]))
    if scores:
        summary["averageScore"] = round(sum(scores) / len(scores), 1)
    return summary


def _apply_metadata(row: MyRepository, meta: dict[str, Any]) -> None:
    """把 GitHub 标准化结构写回本地镜像行（只覆盖存在的字段）。"""
    if meta.get("name"):
        row.name = str(meta["name"])
    if "description" in meta:
        row.description = meta.get("description") or ""
    if meta.get("html_url"):
        row.html_url = str(meta["html_url"])
    if meta.get("stars") is not None:
        row.stars = int(meta.get("stars") or 0)
    if "language" in meta:
        row.language = meta.get("language") or None
    if "pushed_at" in meta:
        row.pushed_at = meta.get("pushed_at")
    if "updated_at" in meta:
        row.updated_at = meta.get("updated_at")
    if meta.get("open_issues_count") is not None:
        row.open_issues_count = int(meta.get("open_issues_count") or 0)
    if "archived" in meta:
        row.archived = bool(meta.get("archived"))
    if "disabled" in meta:
        row.disabled = bool(meta.get("disabled"))


def _load_rows(
    db: Session,
    repo_ids: list[str] | None,
    limit: int,
) -> list[MyRepository]:
    """按 id 批量读取（SQLite 变量上限内分块）或读取最久未检查的仓库。"""
    if not repo_ids:
        stmt = (
            select(MyRepository)
            .order_by(MyRepository.health_checked_at.is_(None).desc(), MyRepository.stars.desc())
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    rows: list[MyRepository] = []
    for start in range(0, len(repo_ids), 100):
        chunk = repo_ids[start : start + 100]
        stmt = select(MyRepository).where(MyRepository.id.in_(chunk))
        rows.extend(db.execute(stmt).scalars().all())
    return rows[:limit]


async def refresh_repositories(
    db: Session,
    repo_ids: list[str] | None = None,
    *,
    token: str = "",
    fetcher: RepoFetcher | None = None,
    now: datetime | None = None,
    max_count: int = DEFAULT_MAX_PER_RUN,
) -> dict[str, Any]:
    """刷新仓库元数据并重算健康度。

    `fetcher` 注入时优先使用（测试 / 自定义数据源）；否则用 `GITHUB_TOKEN` 调 GitHub REST。
    """
    requested: list[str] | None = None
    if repo_ids:
        requested = list(dict.fromkeys(str(item).strip() for item in repo_ids if str(item).strip()))
    rows = _load_rows(db, requested, max(1, int(max_count)))
    found = {row.id for row in rows}
    missing = [repo_id for repo_id in (requested or []) if repo_id not in found]

    checked = 0
    skipped = 0
    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            if fetcher is not None:
                meta = await fetcher(row.id)
            elif token:
                from app.services.github_service import get_repo

                meta = await get_repo(token, row.id)
            else:
                meta = None
        except Exception:  # noqa: BLE001 - 单个仓库失败不影响整批
            logger.warning("刷新仓库健康度失败: %s", row.id, exc_info=True)
            meta = None
        if not isinstance(meta, dict):
            skipped += 1
            continue
        _apply_metadata(row, meta)
        snapshot = snapshot_for_row(row, now=now)
        checked_at = now or utcnow()
        row.health_status = snapshot.status
        row.health_score = snapshot.score
        row.health_checked_at = checked_at
        items.append(
            snapshot.to_dict(
                repo_id=row.id,
                name=row.name,
                html_url=row.html_url,
                language=row.language,
                stars=row.stars,
                checked_at=checked_at,
            )
        )
        checked += 1

    db.commit()
    return {
        "checked": checked,
        "skipped": skipped,
        "missing": missing,
        "items": items,
    }


async def push_health_to_edge(
    items: list[dict[str, Any]],
    *,
    edge_base_url: str,
    internal_token: str = "",
    timeout: float = 15.0,
) -> dict[str, Any]:
    """把健康度快照批量回写 D1；edge 未配置或失败时返回结构化降级结果。"""
    base = (edge_base_url or "").strip().rstrip("/")
    if not base:
        return {"status": "skipped", "reason": "EDGE_BASE_URL 未配置"}
    if not items:
        return {"status": "skipped", "reason": "没有可回写的健康度数据"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base}/api/repos/health",
                headers={"X-Internal-Token": internal_token or ""},
                json={"items": items},
            )
    except httpx.HTTPError as exc:
        logger.warning("健康度回写 edge 失败: %s", exc)
        return {"status": "error", "error": str(exc)[:300]}
    if resp.status_code >= 400:
        return {"status": "error", "httpStatus": resp.status_code}
    try:
        body = resp.json()
    except ValueError:
        body = {}
    return {"status": "ok", "updated": int(body.get("updated") or 0)}


async def refresh_and_push(
    db: Session,
    repo_ids: list[str] | None = None,
    *,
    token: str = "",
    fetcher: RepoFetcher | None = None,
    now: datetime | None = None,
    max_count: int = DEFAULT_MAX_PER_RUN,
    edge_base_url: str = "",
    internal_token: str = "",
) -> dict[str, Any]:
    """刷新 + 回写 edge，返回任务可序列化的摘要。"""
    result = await refresh_repositories(
        db,
        repo_ids,
        token=token,
        fetcher=fetcher,
        now=now,
        max_count=max_count,
    )
    items = result.pop("items", [])
    result["edge"] = await push_health_to_edge(
        items,
        edge_base_url=edge_base_url,
        internal_token=internal_token,
    )
    result["status"] = "ok"
    return result
