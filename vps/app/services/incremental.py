"""增量同步策略（REQ-202610-0899 / M1-07）。

核心原则：

1. **自有仓库**：用 GitHub `/user/repos?since=<checkpoint>` 服务端过滤，只拉取
   `updated_at` 晚于上次成功同步水位线的仓库；
2. **Starred**：`/user/starred` 不支持 `since`，按 `updated` 倒序分页扫描（每页 100 条），
   但只对 `pushed_at` / `stars` / 元数据发生变化的行写库，避免全量 UPDATE；
3. **全量对账**：首次同步、距上次全量超过 `FULL_SYNC_INTERVAL_DAYS`（默认 7 天）或手动
   `mode=full` 时，忽略水位线扫描全部页，补偿 Star 变化、取消 Star 等情况；
4. **水位线只在成功后推进**：抓取或写库失败保留旧水位，下一次自动重试。

本模块不直接访问网络：拉取函数可通过参数注入，单测使用假实现。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MyRepository, SyncState
from app.services.github_service import list_own_repos, list_starred_repos_for_sync

logger = logging.getLogger(__name__)

SYNC_SOURCE_OWN = "github:own"
SYNC_SOURCE_STARRED = "github:starred"
FULL_SYNC_INTERVAL_DAYS = 7

# SQLite 单条 SQL 的变量上限为 999，按 500 分块查询已有行。
_QUERY_CHUNK = 500

# 参与「是否有变化」判定的字段；只有任一字段不同才写库。
_COMPARE_FIELDS = (
    "platform",
    "name",
    "description",
    "html_url",
    "stars",
    "language",
    "owner",
    "forks",
    "pushed_at",
    "updated_at",
)

FetchFunc = Callable[..., Awaitable[list[dict[str, Any]]]]


@dataclass
class ChangePlan:
    """一次同步的变化清单（纯计算结果，尚未写库）。"""

    new_items: list[dict[str, Any]] = field(default_factory=list)
    changed: list[tuple[MyRepository, dict[str, Any]]] = field(default_factory=list)
    unchanged: int = 0
    total: int = 0


@dataclass
class SourceResult:
    """单个数据源的同步结果。"""

    source: str
    mode: str
    since: str | None
    total: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    checkpoint: str | None = None
    duration_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source,
            "mode": self.mode,
            "since": self.since,
            "total": self.total,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "checkpoint": self.checkpoint,
            "durationMs": self.duration_ms,
        }
        if self.error:
            payload["error"] = self.error
        return payload


def _parse_iso(value: str | None) -> datetime | None:
    """解析 GitHub 的 ISO 8601 时间；失败返回 None（按无水位线处理）。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_now(moment: datetime) -> str:
    """输出与 GitHub 一致的 UTC ISO 8601（秒精度、Z 结尾）。"""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def max_updated_at(items: list[dict[str, Any]]) -> str | None:
    """返回一批仓库中最大的 `updated_at`，作为下次增量同步的 `since` 水位。"""
    best: str | None = None
    best_dt: datetime | None = None
    for item in items:
        raw = str(item.get("updated_at") or "")
        parsed = _parse_iso(raw)
        if parsed is not None and (best_dt is None or parsed > best_dt):
            best, best_dt = raw, parsed
    return best


def _newer_checkpoint(previous: str | None, candidate: str | None) -> str | None:
    """取新旧水位线中较晚的一个，避免异常响应把水位线回退。"""
    if not candidate:
        return previous
    if not previous:
        return candidate
    prev_dt, cand_dt = _parse_iso(previous), _parse_iso(candidate)
    if prev_dt is not None and cand_dt is not None and cand_dt < prev_dt:
        return previous
    return candidate


def _since_with_overlap(checkpoint: str | None, seconds: int = 60) -> str | None:
    """给 `since` 留出重叠窗口，避免同一秒内更新的仓库被边界条件漏掉。"""
    parsed = _parse_iso(checkpoint)
    if parsed is None:
        return checkpoint
    return _iso_now(parsed - timedelta(seconds=max(0, seconds)))


def should_full_sync(
    state: SyncState | None,
    now: datetime,
    *,
    interval_days: int = FULL_SYNC_INTERVAL_DAYS,
) -> bool:
    """判断本次是否必须做全量对账：无历史全量、或距上次全量超过阈值。"""
    if state is None or not state.last_full_synced_at:
        return True
    last_full = _parse_iso(state.last_full_synced_at)
    if last_full is None:
        return True
    return now - last_full >= timedelta(days=max(1, int(interval_days)))


def _repo_values(item: dict[str, Any]) -> dict[str, Any]:
    """把标准化条目映射为 `my_repositories` 的可写字段。"""
    repo_id = str(item.get("id") or "").strip()
    return {
        "platform": item.get("platform") or "github",
        "name": item.get("name") or (repo_id.split("/")[-1] if repo_id else ""),
        "description": item.get("description") or "",
        "html_url": item.get("html_url") or (f"https://github.com/{repo_id}" if repo_id else ""),
        "stars": int(item.get("stars") or 0),
        "language": item.get("language") or None,
        "owner": item.get("owner") or (repo_id.split("/")[0] if repo_id else None),
        "forks": int(item.get("forks") or 0),
        "pushed_at": item.get("pushed_at") or None,
        "updated_at": item.get("updated_at") or None,
    }


def _row_differs(row: MyRepository, values: dict[str, Any]) -> bool:
    """比较本地行与远端字段；空字符串 / None 视为等价。"""
    for field_name in _COMPARE_FIELDS:
        current = getattr(row, field_name, None)
        incoming = values.get(field_name)
        if isinstance(incoming, str):
            current = current or ""
        if current != incoming:
            return True
    return False


def build_change_plan(
    existing: dict[str, MyRepository],
    items: list[dict[str, Any]],
) -> ChangePlan:
    """对比远端条目与本地行，生成新增 / 变化 / 未变化清单（纯函数）。"""
    plan = ChangePlan()
    seen: set[str] = set()
    for item in items:
        repo_id = str(item.get("id") or "").strip()
        if not repo_id or repo_id in seen:
            continue
        seen.add(repo_id)
        values = _repo_values(item)
        row = existing.get(repo_id)
        if row is None:
            plan.new_items.append({"id": repo_id, **values})
        elif _row_differs(row, values):
            plan.changed.append((row, values))
        else:
            plan.unchanged += 1
    plan.total = len(seen)
    return plan


def _load_existing(db: Session, repo_ids: list[str]) -> dict[str, MyRepository]:
    """按主键批量加载已有仓库行。"""
    existing: dict[str, MyRepository] = {}
    for start in range(0, len(repo_ids), _QUERY_CHUNK):
        chunk = repo_ids[start : start + _QUERY_CHUNK]
        rows = db.execute(select(MyRepository).where(MyRepository.id.in_(chunk))).scalars()
        for row in rows:
            existing[row.id] = row
    return existing


def apply_change_plan(db: Session, plan: ChangePlan, synced_at: str) -> dict[str, int]:
    """把变化清单写入数据库并提交，返回计数。"""
    for item in plan.new_items:
        values = dict(item)
        repo_id = values.pop("id")
        db.add(MyRepository(id=repo_id, synced_at=synced_at, **values))
    for row, values in plan.changed:
        for field_name, value in values.items():
            setattr(row, field_name, value)
        row.synced_at = synced_at
    db.commit()
    return {
        "total": plan.total,
        "created": len(plan.new_items),
        "updated": len(plan.changed),
        "unchanged": plan.unchanged,
    }


def get_or_create_sync_state(db: Session, source: str) -> SyncState:
    """读取（必要时创建）同步水位线记录。"""
    state = db.get(SyncState, source)
    if state is None:
        state = SyncState(source=source, last_status="never")
        db.add(state)
        db.flush()
    return state


def record_sync_state(
    db: Session,
    state: SyncState,
    *,
    status: str,
    checkpoint: str | None,
    full: bool,
    result: dict[str, Any],
    now_iso: str,
) -> None:
    """更新水位线；仅在成功时推进 `last_synced_at` / `last_full_synced_at`。"""
    if status == "ok":
        state.last_synced_at = _newer_checkpoint(state.last_synced_at, checkpoint)
        if full:
            state.last_full_synced_at = now_iso
    state.last_run_at = now_iso
    state.last_status = status
    state.last_result = json.dumps(result, ensure_ascii=False)
    db.commit()


async def run_incremental_sync(
    db: Session,
    token: str,
    *,
    include_starred: bool = True,
    mode: str = "incremental",
    per_page: int = 100,
    max_pages: int | None = None,
    now: datetime | None = None,
    interval_days: int = FULL_SYNC_INTERVAL_DAYS,
    fetch_own: FetchFunc | None = None,
    fetch_starred: FetchFunc | None = None,
) -> dict[str, Any]:
    """执行一次增量 / 全量同步。

    `mode="incremental"` 时按水位线增量拉取，并在需要时自动升级为全量对账；
    `mode="full"` 强制忽略水位线。单个数据源失败不影响另一个数据源。
    """
    if mode not in ("incremental", "full"):
        raise ValueError(f"不支持的同步模式: {mode}")

    started = time.monotonic()
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    now_iso = _iso_now(now_dt)

    own_fetch = fetch_own or list_own_repos
    starred_fetch = fetch_starred or list_starred_repos_for_sync

    results: list[SourceResult] = []
    sources: list[tuple[str, FetchFunc]] = [(SYNC_SOURCE_OWN, own_fetch)]
    if include_starred:
        sources.append((SYNC_SOURCE_STARRED, starred_fetch))

    for source, fetcher in sources:
        state = get_or_create_sync_state(db, source)
        effective_mode = mode
        if mode == "incremental" and should_full_sync(state, now_dt, interval_days=interval_days):
            effective_mode = "full"
        since = _since_with_overlap(state.last_synced_at) if effective_mode == "incremental" else None
        source_started = time.monotonic()
        result = SourceResult(source=source, mode=effective_mode, since=since)

        try:
            if source == SYNC_SOURCE_OWN:
                items = await fetcher(
                    token, since=since, per_page=per_page, max_pages=max_pages
                )
            else:
                items = await fetcher(token, per_page=per_page, max_pages=max_pages)

            existing = _load_existing(db, [str(i.get("id") or "") for i in items if i.get("id")])
            plan = build_change_plan(existing, items)
            counts = apply_change_plan(db, plan, now_iso)
            result.total = counts["total"]
            result.created = counts["created"]
            result.updated = counts["updated"]
            result.unchanged = counts["unchanged"]
            result.checkpoint = _newer_checkpoint(state.last_synced_at, max_updated_at(items))
            result.duration_ms = int((time.monotonic() - source_started) * 1000)
            record_sync_state(
                db,
                state,
                status="ok",
                checkpoint=result.checkpoint,
                full=effective_mode == "full",
                result=result.to_dict(),
                now_iso=now_iso,
            )
        except Exception as exc:  # noqa: BLE001 - 单源失败降级，保留旧水位等待重试
            db.rollback()
            logger.warning("增量同步失败 source=%s: %s", source, exc)
            result.error = str(exc)[:300]
            result.duration_ms = int((time.monotonic() - source_started) * 1000)
            state = get_or_create_sync_state(db, source)
            record_sync_state(
                db,
                state,
                status="error",
                checkpoint=None,
                full=False,
                result=result.to_dict(),
                now_iso=now_iso,
            )
        results.append(result)

    succeeded = [r for r in results if r.error is None]
    if not succeeded:
        status = "error"
    elif len(succeeded) != len(results):
        status = "partial"
    else:
        status = "ok"

    payload: dict[str, Any] = {
        "status": status,
        "mode": mode,
        "total": sum(r.total for r in results),
        "created": sum(r.created for r in results),
        "updated": sum(r.updated for r in results),
        "unchanged": sum(r.unchanged for r in results),
        "sources": [r.to_dict() for r in results],
        "durationMs": int((time.monotonic() - started) * 1000),
    }
    own = next((r for r in results if r.source == SYNC_SOURCE_OWN), None)
    if own is not None:
        payload["since"] = own.since
        payload["checkpoint"] = own.checkpoint
    logger.info(
        "增量同步结束: mode=%s status=%s 共 %d 条（新增 %d / 更新 %d / 未变化 %d），耗时 %dms",
        mode,
        status,
        payload["total"],
        payload["created"],
        payload["updated"],
        payload["unchanged"],
        payload["durationMs"],
    )
    return payload
