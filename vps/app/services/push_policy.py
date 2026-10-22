"""推送去重与静默策略（M4-07）。

职责：

- 统一维护推送事件账本 `push_events`，按「用户 + 仓库」做跨通道、跨天去重；
- 提供静默时段（免打扰）判定与下次可推送时间计算；
- 提供单用户每日推送上限与批量预演；
- 为 `daily_push`、各推送通道与运维接口提供同一套判定口径。

所有函数均为本地规则 / 数据库查询，不访问网络；时间统一以 UTC 无时区写入 SQLite，
静默窗口按 `PUSH_TIMEZONE` 解释为本地时间。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional, Sequence
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import PushEvent, Recommendation

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_QUIET_START = "22:00"
DEFAULT_QUIET_END = "08:00"
VALID_CHANNELS: tuple[str, ...] = ("inapp", "bark", "telegram", "email")
VALID_STATUSES: tuple[str, ...] = ("prepared", "sent", "failed", "skipped")
# 状态只升不降：同一 event_key 重放时避免 sent 被后续 failed / skipped 覆盖。
_STATUS_RANK: dict[str, int] = {"skipped": 0, "prepared": 1, "failed": 2, "sent": 3}
_ACTIVE_STATUSES: tuple[str, ...] = ("prepared", "sent")


@dataclass(frozen=True)
class QuietWindow:
    """归一化后的静默窗口。"""

    start: Optional[time]
    end: Optional[time]
    timezone_name: str

    @property
    def enabled(self) -> bool:
        return self.start is not None and self.end is not None and self.start != self.end


def _utcnow() -> datetime:
    """统一使用无时区 UTC 时间（与模型默认值一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc_naive(value: Optional[datetime]) -> datetime:
    """把任意时间归一化为 UTC 无时区；无时区输入按 UTC 解释。"""
    if value is None:
        return _utcnow()
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def parse_clock(raw: Any, default: Optional[time] = None) -> Optional[time]:
    """解析 `HH:MM` / `HH:MM:SS`；空值返回默认值，非法值同样回退默认。"""
    text = str(raw or "").strip()
    if not text:
        return default
    parts = text.split(":")
    if len(parts) not in (2, 3):
        return default
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (TypeError, ValueError):
        return default
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default
    return time(hour, minute)


def resolve_timezone(name: Any) -> ZoneInfo:
    """解析 IANA 时区；非法 / 缺失回退 `Asia/Shanghai`。"""
    text = str(name or "").strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("非法 PUSH_TIMEZONE=%s，回退 %s", text, DEFAULT_TIMEZONE)
        return ZoneInfo(DEFAULT_TIMEZONE)


def resolve_quiet_window(settings: Optional[Settings] = None) -> QuietWindow:
    """从配置解析静默窗口；开始 / 结束为空或相同表示不静默。"""
    cfg = settings or get_settings()
    raw_start = str(getattr(cfg, "PUSH_QUIET_HOURS_START", DEFAULT_QUIET_START) or "").strip()
    raw_end = str(getattr(cfg, "PUSH_QUIET_HOURS_END", DEFAULT_QUIET_END) or "").strip()
    timezone_name = str(getattr(cfg, "PUSH_TIMEZONE", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE)
    if not raw_start or not raw_end:
        return QuietWindow(None, None, timezone_name)
    start = parse_clock(raw_start, time(22, 0))
    end = parse_clock(raw_end, time(8, 0))
    if start is None or end is None or start == end:
        return QuietWindow(None, None, timezone_name)
    return QuietWindow(start, end, timezone_name)


def _local_now(now: datetime, timezone_name: str) -> datetime:
    """把 UTC 无时区时间转为指定时区的本地时间。"""
    return _as_utc_naive(now).replace(tzinfo=timezone.utc).astimezone(
        resolve_timezone(timezone_name)
    )


def is_quiet_hours(
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
) -> bool:
    """判断当前时刻是否处于静默窗口（支持跨午夜）。"""
    window = resolve_quiet_window(settings)
    if not window.enabled:
        return False
    local = _local_now(now or _utcnow(), window.timezone_name)
    current = local.time()
    assert window.start is not None and window.end is not None
    if window.start < window.end:
        return window.start <= current < window.end
    return current >= window.start or current < window.end


def next_allowed_at(
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
) -> Optional[datetime]:
    """返回静默结束后的首个可推送时间（UTC 无时区）；非静默时返回 None。"""
    window = resolve_quiet_window(settings)
    if not window.enabled or not is_quiet_hours(now, settings):
        return None
    assert window.start is not None and window.end is not None
    current_utc = _as_utc_naive(now)
    tz = resolve_timezone(window.timezone_name)
    local = current_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    candidate = datetime.combine(local.date(), window.end, tzinfo=tz)
    if candidate <= local:
        candidate = datetime.combine(local.date() + timedelta(days=1), window.end, tzinfo=tz)
    return candidate.astimezone(timezone.utc).replace(tzinfo=None)


def day_bounds(
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
) -> tuple[datetime, datetime]:
    """返回用户时区「今天」对应的 UTC 起止时间（左闭右开）。"""
    window = resolve_quiet_window(settings)
    tz = resolve_timezone(window.timezone_name)
    local = _as_utc_naive(now).replace(tzinfo=timezone.utc).astimezone(tz)
    start_local = datetime.combine(local.date(), time(0, 0), tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


def build_dedupe_key(user_id: str, repo_id: str) -> str:
    """跨通道去重键：同一用户 + 仓库固定一个值。"""
    return f"{str(user_id or '').strip()}:{str(repo_id or '').strip()}"


def build_event_key(
    user_id: str,
    repo_id: str,
    channel: str,
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
) -> str:
    """当日幂等键：用户 + 仓库 + 通道 + 用户本地自然日。"""
    window = resolve_quiet_window(settings)
    local = _local_now(now or _utcnow(), window.timezone_name)
    return (
        f"{str(user_id or '').strip()}:{str(repo_id or '').strip()}:"
        f"{normalize_channel(channel)}:{local.date().isoformat()}"
    )


def normalize_channel(channel: Any) -> str:
    """归一化通道名，未知值回退 `inapp`。"""
    value = str(channel or "").strip().lower()
    return value if value in VALID_CHANNELS else "inapp"


def normalize_status(status: Any) -> str:
    """归一化事件状态，未知值回退 `prepared`。"""
    value = str(status or "").strip().lower()
    return value if value in VALID_STATUSES else "prepared"


def _recent_event(
    db: Session,
    *,
    user_id: str,
    repo_id: str,
    since: datetime,
    channel: str,
    cross_channel: bool,
) -> Optional[PushEvent]:
    """查询去重窗口内最近一条有效推送事件。"""
    stmt = select(PushEvent).where(
        PushEvent.user_id == user_id,
        PushEvent.repo_id == repo_id,
        PushEvent.status.in_(_ACTIVE_STATUSES),
        PushEvent.updated_at >= since,
    )
    if not cross_channel:
        stmt = stmt.where(PushEvent.channel == channel)
    stmt = stmt.order_by(PushEvent.updated_at.desc()).limit(1)
    return db.execute(stmt).scalars().first()


def _daily_used(db: Session, *, user_id: str, start: datetime, end: datetime) -> int:
    """统计用户当日已占用额度的去重仓库数。"""
    stmt = (
        select(func.count(func.distinct(PushEvent.repo_id)))
        .select_from(PushEvent)
        .where(
            PushEvent.user_id == user_id,
            PushEvent.status.in_(_ACTIVE_STATUSES),
            PushEvent.updated_at >= start,
            PushEvent.updated_at < end,
        )
    )
    return int(db.execute(stmt).scalar() or 0)


def evaluate_push(
    db: Session,
    *,
    user_id: str,
    repo_id: str,
    recommendation_id: Optional[str] = None,
    channel: str = "inapp",
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """判定一条推送是否允许发送（只读，不写库）。"""
    cfg = settings or get_settings()
    current = _as_utc_naive(now)
    normalized_channel = normalize_channel(channel)
    result: dict[str, Any] = {
        "allowed": True,
        "reason": "allowed",
        "userId": str(user_id or ""),
        "repoId": str(repo_id or ""),
        "recommendationId": recommendation_id,
        "channel": normalized_channel,
        "dedupeKey": build_dedupe_key(user_id, repo_id),
        "quietHours": False,
        "nextAllowedAt": None,
        "existingEventId": None,
        "dailyUsed": 0,
        "dailyLimit": max(0, int(getattr(cfg, "PUSH_DAILY_LIMIT", 3) or 0)),
    }

    if not bool(getattr(cfg, "PUSH_POLICY_ENABLED", True)):
        result["reason"] = "policy_disabled"
        return result

    if is_quiet_hours(current, cfg):
        result.update(
            allowed=False,
            reason="quiet_hours",
            quietHours=True,
            nextAllowedAt=next_allowed_at(current, cfg),
        )
        return result

    dedupe_days = max(0, int(getattr(cfg, "PUSH_DEDUPE_DAYS", 7) or 0))
    if dedupe_days:
        existing = _recent_event(
            db,
            user_id=result["userId"],
            repo_id=result["repoId"],
            since=current - timedelta(days=dedupe_days),
            channel=normalized_channel,
            cross_channel=bool(getattr(cfg, "PUSH_DEDUPE_CROSS_CHANNEL", True)),
        )
        if existing is not None:
            result.update(
                allowed=False,
                reason="duplicate_repo",
                existingEventId=existing.id,
            )
            return result

    limit = max(0, int(getattr(cfg, "PUSH_DAILY_LIMIT", 3) or 0))
    if limit:
        start, end = day_bounds(current, cfg)
        used = _daily_used(db, user_id=result["userId"], start=start, end=end)
        result["dailyUsed"] = used
        if used >= limit:
            result.update(allowed=False, reason="daily_limit")
            return result

    return result


def record_push_event(
    db: Session,
    *,
    user_id: str,
    repo_id: str,
    recommendation_id: Optional[str] = None,
    channel: str = "inapp",
    status: str = "prepared",
    reason: Optional[str] = None,
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """按 `event_key` 幂等写入 / 更新推送事件。

    状态只升不降（skipped < prepared < failed < sent）；`sent` 会补写 `sent_at`。
    """
    cfg = settings or get_settings()
    current = _as_utc_naive(now)
    normalized_channel = normalize_channel(channel)
    normalized_status = normalize_status(status)
    event_key = build_event_key(user_id, repo_id, normalized_channel, current, cfg)
    dedupe_key = build_dedupe_key(user_id, repo_id)

    existing = (
        db.execute(select(PushEvent).where(PushEvent.event_key == event_key))
        .scalars()
        .first()
    )
    if existing is not None:
        changed = False
        if _STATUS_RANK[normalized_status] >= _STATUS_RANK.get(existing.status, 1):
            if existing.status != normalized_status:
                existing.status = normalized_status
                changed = True
            if recommendation_id and existing.recommendation_id != recommendation_id:
                existing.recommendation_id = recommendation_id
                changed = True
            if reason is not None and existing.reason != reason:
                existing.reason = reason
                changed = True
            if normalized_status == "sent" and existing.sent_at is None:
                existing.sent_at = current
                changed = True
        if changed:
            existing.updated_at = current
        db.flush()
        return {
            "id": existing.id,
            "created": False,
            "updated": changed,
            "status": existing.status,
            "eventKey": event_key,
            "dedupeKey": dedupe_key,
            "sentAt": existing.sent_at,
        }

    row = PushEvent(
        id=uuid4().hex,
        user_id=str(user_id or ""),
        repo_id=str(repo_id or ""),
        recommendation_id=recommendation_id,
        channel=normalized_channel,
        status=normalized_status,
        dedupe_key=dedupe_key,
        event_key=event_key,
        reason=reason,
        created_at=current,
        updated_at=current,
        sent_at=current if normalized_status == "sent" else None,
    )
    db.add(row)
    db.flush()
    return {
        "id": row.id,
        "created": True,
        "updated": False,
        "status": row.status,
        "eventKey": event_key,
        "dedupeKey": dedupe_key,
        "sentAt": row.sent_at,
    }


def filter_push_candidates(
    db: Session,
    recommendations: Sequence[Recommendation],
    *,
    channel: str = "inapp",
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """批量预演：返回允许 / 跳过列表（不写库，计入批内去重与额度占用）。"""
    cfg = settings or get_settings()
    current = _as_utc_naive(now)
    normalized_channel = normalize_channel(channel)
    limit = max(0, int(getattr(cfg, "PUSH_DAILY_LIMIT", 3) or 0))
    start, end = day_bounds(current, cfg)
    used_by_user: dict[str, int] = {}
    seen_repos: set[tuple[str, str]] = set()
    allowed: list[Recommendation] = []
    skipped: list[dict[str, Any]] = []

    for row in recommendations:
        user_id = str(row.user_id or "")
        repo_id = str(row.repo_id or "")
        key = (user_id, repo_id)
        decision = evaluate_push(
            db,
            user_id=user_id,
            repo_id=repo_id,
            recommendation_id=row.id,
            channel=normalized_channel,
            now=current,
            settings=cfg,
        )
        if key in seen_repos:
            decision.update(allowed=False, reason="duplicate_repo")
        elif decision["allowed"] and limit:
            used = used_by_user.get(user_id)
            if used is None:
                used = _daily_used(db, user_id=user_id, start=start, end=end)
            if used >= limit:
                decision.update(allowed=False, reason="daily_limit", dailyUsed=used)
            else:
                used_by_user[user_id] = used + 1
        if decision["allowed"]:
            seen_repos.add(key)
            allowed.append(row)
        else:
            skipped.append(
                {
                    "recommendationId": row.id,
                    "userId": user_id,
                    "repoId": repo_id,
                    "reason": decision["reason"],
                    "nextAllowedAt": decision.get("nextAllowedAt"),
                }
            )
    return {"allowed": allowed, "skipped": skipped, "total": len(recommendations)}


def event_to_dict(event: PushEvent) -> dict[str, Any]:
    """把事件行转换为 API 输出（camelCase）。"""
    return {
        "id": event.id,
        "userId": event.user_id,
        "repoId": event.repo_id,
        "recommendationId": event.recommendation_id,
        "channel": event.channel,
        "status": event.status,
        "dedupeKey": event.dedupe_key,
        "eventKey": event.event_key,
        "reason": event.reason,
        "createdAt": event.created_at,
        "updatedAt": event.updated_at,
        "sentAt": event.sent_at,
    }


def list_events(
    db: Session,
    *,
    user_id: Optional[str] = None,
    channel: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """查询最近推送事件。"""
    stmt = select(PushEvent)
    if user_id:
        stmt = stmt.where(PushEvent.user_id == user_id)
    if channel:
        stmt = stmt.where(PushEvent.channel == normalize_channel(channel))
    if status:
        stmt = stmt.where(PushEvent.status == normalize_status(status))
    stmt = stmt.order_by(PushEvent.updated_at.desc()).limit(max(1, min(int(limit), 100)))
    return [event_to_dict(row) for row in db.execute(stmt).scalars().all()]


def policy_status(
    db: Session,
    *,
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """策略状态快照：配置、静默状态、今日计数与最近事件。"""
    cfg = settings or get_settings()
    current = _as_utc_naive(now)
    window = resolve_quiet_window(cfg)
    start, end = day_bounds(current, cfg)
    counts = {status: 0 for status in VALID_STATUSES}
    rows = db.execute(
        select(PushEvent.status, func.count())
        .where(PushEvent.updated_at >= start, PushEvent.updated_at < end)
        .group_by(PushEvent.status)
    ).all()
    for status, count in rows:
        counts[str(status)] = int(count)
    repos = int(
        db.execute(
            select(func.count(func.distinct(PushEvent.repo_id)))
            .select_from(PushEvent)
            .where(
                PushEvent.status.in_(_ACTIVE_STATUSES),
                PushEvent.updated_at >= start,
                PushEvent.updated_at < end,
            )
        ).scalar()
        or 0
    )
    return {
        "enabled": bool(getattr(cfg, "PUSH_POLICY_ENABLED", True)),
        "quietHours": {
            "start": window.start.strftime("%H:%M") if window.start else None,
            "end": window.end.strftime("%H:%M") if window.end else None,
            "timezone": window.timezone_name,
            "active": is_quiet_hours(current, cfg),
            "nextAllowedAt": next_allowed_at(current, cfg),
        },
        "limits": {
            "dailyLimit": max(0, int(getattr(cfg, "PUSH_DAILY_LIMIT", 3) or 0)),
            "dedupeDays": max(0, int(getattr(cfg, "PUSH_DEDUPE_DAYS", 7) or 0)),
            "crossChannel": bool(getattr(cfg, "PUSH_DEDUPE_CROSS_CHANNEL", True)),
            "retryIntervalMinutes": max(
                1, int(getattr(cfg, "PUSH_RETRY_INTERVAL_MINUTES", 30) or 30)
            ),
        },
        "today": {
            "prepared": counts.get("prepared", 0),
            "sent": counts.get("sent", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "repos": repos,
        },
        "recentEvents": list_events(db, limit=10),
    }
