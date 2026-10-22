"""热榜按日快照（M2-05）。

职责：
- `build_snapshot_rows`：把一轮抓取结果去重、排名并计算趋势字段（纯函数，便于离线测试）；
- `save_trending_snapshots`：按 `(snapshot_date, repo_id)` 幂等 upsert 到本地镜像库；
- `push_trending_snapshots`：配置边缘地址与内部令牌时，把快照批量写回 D1。

趋势口径（详见 docs/planning/plan-req-202610-0913-trending-snapshots.md）：
- 基线取同一仓库在快照日之前最近一条快照，最多回看 `LOOKBACK_DAYS` 天；
- `star_delta = 当前总 Star - 基线总 Star`；
- `rank_delta = 基线排名 - 当前排名`（正数表示排名上升）；
- `appearances` 仅在基线日期与当前日期相差 1 天时累加，否则重置为 1；
- `trend`：无基线 → `new`；`rank_delta >= 3` → `up`；`rank_delta <= -3` → `down`；其余 `steady`。
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Optional, Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import TrendingSnapshot

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 7
TREND_UP_THRESHOLD = 3
TREND_DOWN_THRESHOLD = -3
PUSH_BATCH_SIZE = 200
PUSH_TIMEOUT_SECONDS = 10.0


def _to_int(value: Any) -> int:
    """把抓取结果中的数字安全转为 int（空值 / 脏数据归零）。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _merge_items(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """同一轮抓取内按 `repo_id` 去重合并：数值取大、空字段互补、来源页并集。"""
    merged: dict[str, dict[str, Any]] = {}
    for raw in items:
        repo_id = _clean_text(raw.get("id"))
        if not repo_id:
            continue
        item = dict(raw)
        item["id"] = repo_id
        item["stars"] = _to_int(item.get("stars"))
        item["stars_today"] = _to_int(item.get("stars_today"))
        pages = [_clean_text(p) for p in (item.get("trending_pages") or []) if _clean_text(p)]
        item["trending_pages"] = pages

        existing = merged.get(repo_id)
        if existing is None:
            merged[repo_id] = item
            continue

        # 描述取更长的一份；其余文本字段空值互补
        if len(_clean_text(item.get("description"))) > len(_clean_text(existing.get("description"))):
            existing["description"] = item.get("description") or ""
        for key in ("platform", "owner", "name", "html_url", "language"):
            if not _clean_text(existing.get(key)) and _clean_text(item.get(key)):
                existing[key] = item[key]
        existing["stars"] = max(_to_int(existing.get("stars")), item["stars"])
        existing["stars_today"] = max(_to_int(existing.get("stars_today")), item["stars_today"])
        for page_name in item["trending_pages"]:
            if page_name not in existing["trending_pages"]:
                existing["trending_pages"].append(page_name)

    return list(merged.values())


def _previous_value(previous: Any, key: str, default: Any = None) -> Any:
    """兼容 ORM 对象与 dict 的基线字段读取。"""
    if previous is None:
        return default
    if isinstance(previous, Mapping):
        return previous.get(key, default)
    return getattr(previous, key, default)


def _previous_date(previous: Any) -> Optional[date]:
    value = _previous_value(previous, "snapshot_date")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _trend_label(rank_delta: int, is_new: bool) -> str:
    if is_new:
        return "new"
    if rank_delta >= TREND_UP_THRESHOLD:
        return "up"
    if rank_delta <= TREND_DOWN_THRESHOLD:
        return "down"
    return "steady"


def build_snapshot_rows(
    items: Sequence[Mapping[str, Any]],
    snapshot_date: date,
    previous: Optional[Mapping[str, Any]] = None,
    *,
    lookback_days: int = LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """把抓取条目转换为待入库的快照行（含排名与趋势字段）。

    `previous` 为 `repo_id -> 最近一条快照（ORM 对象或 dict）` 的映射。
    返回按综合排名升序排列的 dict 列表，字段名与 `TrendingSnapshot` 对齐。
    """
    merged = _merge_items(items)
    merged.sort(key=lambda item: (-_to_int(item.get("stars_today")), -_to_int(item.get("stars")), item["id"]))

    # 语言内排名：按语言分组后沿用综合排序（稳定排序保证同分顺序一致）
    language_counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    previous = previous or {}

    for index, item in enumerate(merged, start=1):
        repo_id = item["id"]
        language = _clean_text(item.get("language")) or ""
        if language:
            language_key = language.lower()
            language_rank = language_counts.get(language_key, 0) + 1
            language_counts[language_key] = language_rank
        else:
            # 无语言的条目不计入语言榜
            language_rank = 0

        prev = previous.get(repo_id)
        prev_date = _previous_date(prev)
        has_baseline = prev is not None and prev_date is not None and 0 <= (snapshot_date - prev_date).days <= lookback_days
        if has_baseline:
            prev_stars = _to_int(_previous_value(prev, "stars"))
            stars = _to_int(item.get("stars"))
            star_delta = stars - prev_stars if stars > 0 and prev_stars > 0 else 0
            prev_rank = _to_int(_previous_value(prev, "rank"))
            rank_delta = prev_rank - index if prev_rank > 0 else 0
            gap_days = (snapshot_date - prev_date).days
            appearances = _to_int(_previous_value(prev, "appearances", 1)) + 1 if gap_days == 1 else 1
            is_new = 0
        else:
            star_delta = 0
            rank_delta = 0
            appearances = 1
            is_new = 1

        rows.append(
            {
                "snapshot_date": snapshot_date,
                "repo_id": repo_id,
                "platform": _clean_text(item.get("platform")) or "github",
                "owner": _clean_text(item.get("owner")) or repo_id.split("/")[0],
                "name": _clean_text(item.get("name")) or repo_id.split("/")[-1],
                "html_url": _clean_text(item.get("html_url")),
                "description": _clean_text(item.get("description")),
                "language": language or None,
                "tech_stack": _clean_text(item.get("tech_stack")) or None,
                "stars": _to_int(item.get("stars")),
                "stars_today": _to_int(item.get("stars_today")),
                "rank": index,
                "language_rank": language_rank,
                "star_delta": star_delta,
                "rank_delta": rank_delta,
                "appearances": appearances,
                "is_new": is_new,
                "trend": _trend_label(rank_delta, bool(is_new)),
                "trending_pages": json.dumps(item.get("trending_pages") or [], ensure_ascii=False),
            }
        )
    return rows


def _load_previous(db: Session, snapshot_date: date, lookback_days: int = LOOKBACK_DAYS) -> dict[str, TrendingSnapshot]:
    """取每个仓库在快照日之前最近一条快照（最多回看 lookback_days 天）。"""
    earliest = snapshot_date - timedelta(days=lookback_days)
    stmt = (
        select(TrendingSnapshot)
        .where(
            TrendingSnapshot.snapshot_date < snapshot_date,
            TrendingSnapshot.snapshot_date >= earliest,
        )
        .order_by(TrendingSnapshot.snapshot_date.asc())
    )
    latest: dict[str, TrendingSnapshot] = {}
    for row in db.execute(stmt).scalars().all():
        latest[row.repo_id] = row  # 按日期升序遍历，后写入的即最近一条
    return latest


def save_trending_snapshots(
    db: Session,
    items: Sequence[Mapping[str, Any]],
    snapshot_date: Optional[date] = None,
    *,
    lookback_days: int = LOOKBACK_DAYS,
) -> dict[str, Any]:
    """把一轮抓取结果写入按日快照；重复执行同一日期幂等。

    返回 `{date, total, created, updated, rows}`，`rows` 供边缘同步使用。
    """
    target_date = snapshot_date or date.today()
    previous = _load_previous(db, target_date, lookback_days)
    rows = build_snapshot_rows(items, target_date, previous, lookback_days=lookback_days)

    existing_rows = {
        row.repo_id: row
        for row in db.execute(
            select(TrendingSnapshot).where(TrendingSnapshot.snapshot_date == target_date)
        )
        .scalars()
        .all()
    }

    created = 0
    updated = 0
    for row in rows:
        current = existing_rows.get(row["repo_id"])
        if current is None:
            db.add(TrendingSnapshot(**row))
            created += 1
            continue
        for key, value in row.items():
            if key in ("snapshot_date", "repo_id"):
                continue
            setattr(current, key, value)
        updated += 1

    db.commit()
    logger.info(
        "热榜快照入库完成: %s 共 %d 条（新增 %d / 更新 %d）",
        target_date.isoformat(),
        len(rows),
        created,
        updated,
    )
    return {
        "date": target_date.isoformat(),
        "total": len(rows),
        "created": created,
        "updated": updated,
        "rows": rows,
    }


def _snapshot_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """本地行 → 边缘内部接口的 camelCase 载荷。"""
    return {
        "repoId": row["repo_id"],
        "platform": row["platform"],
        "owner": row.get("owner"),
        "name": row["name"],
        "htmlUrl": row.get("html_url") or "",
        "description": row.get("description") or "",
        "language": row.get("language"),
        "techStack": row.get("tech_stack"),
        "stars": row.get("stars", 0),
        "starsToday": row.get("stars_today", 0),
        "rank": row.get("rank", 0),
        "languageRank": row.get("language_rank", 0),
        "starDelta": row.get("star_delta", 0),
        "rankDelta": row.get("rank_delta", 0),
        "appearances": row.get("appearances", 1),
        "isNew": bool(row.get("is_new", 0)),
        "trend": row.get("trend", "steady"),
        "trendingPages": json.loads(row.get("trending_pages") or "[]"),
    }


def push_trending_snapshots(
    rows: Sequence[Mapping[str, Any]],
    snapshot_date: date,
    *,
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    batch_size: int = PUSH_BATCH_SIZE,
    client: Optional[httpx.Client] = None,
) -> dict[str, Any]:
    """把快照批量写回边缘 D1；未配置地址 / 令牌时跳过，失败只记录不抛异常。"""
    settings = get_settings()
    edge_base = (base_url if base_url is not None else settings.EDGE_BASE_URL).strip()
    internal_token = (token if token is not None else settings.INTERNAL_TOKEN).strip()
    if not edge_base or not internal_token or not rows:
        return {"skipped": True, "pushed": 0, "failed": 0, "batches": 0}

    endpoint = f"{edge_base.rstrip('/')}/api/internal/trending/snapshots"
    headers = {"Content-Type": "application/json", "X-Internal-Token": internal_token}
    owns_client = client is None
    http_client = client or httpx.Client(timeout=PUSH_TIMEOUT_SECONDS)
    pushed = 0
    failed = 0
    batches = 0
    try:
        for start in range(0, len(rows), max(1, batch_size)):
            batch = rows[start : start + max(1, batch_size)]
            payload = {
                "snapshotDate": snapshot_date.isoformat(),
                "items": [_snapshot_payload(row) for row in batch],
            }
            batches += 1
            try:
                response = http_client.post(endpoint, json=payload, headers=headers)
                if response.status_code >= 400:
                    failed += len(batch)
                    logger.warning("热榜快照回写失败: HTTP %s", response.status_code)
                else:
                    pushed += len(batch)
            except httpx.HTTPError as exc:
                failed += len(batch)
                logger.warning("热榜快照回写异常: %s", exc)
    finally:
        if owns_client:
            http_client.close()

    return {"skipped": False, "pushed": pushed, "failed": failed, "batches": batches}
