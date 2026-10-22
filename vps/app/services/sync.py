"""Starred 仓库同步编排（REQ-202610-0897）。

职责：
- 调用 `GitHubClient` 全量抓取 Starred（分页 / 限流 / 重试在客户端层）；
- 批量 upsert 到本地镜像表 `my_repositories`；
- 逐页回调进度，供 Celery 任务转成 `PROGRESS` 状态；
- 抓取中断时保留并落库已抓取部分，返回结构化错误而不是抛出。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MyRepository
from app.services.github_service import (
    GitHubClient,
    GitHubServiceError,
    SyncProgress,
    list_starred_repos,
    normalize_starred,
)

logger = logging.getLogger(__name__)

# SQLite 单条 SQL 的变量上限为 999，按 500 分块查询已有行。
_UPSERT_CHUNK = 500


def upsert_repositories(db: Session, items: list[dict[str, Any]]) -> dict[str, int]:
    """批量 upsert 仓库，返回 `{total, created, updated, unchanged}`。

    - 以 `id`（`owner/repo`）为主键；重复条目按最后一次为准；
    - 只有字段实际变化才计入 `updated`，避免每次同步都写库。
    """
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        repo_id = str(item.get("id") or "").strip()
        if repo_id:
            deduped[repo_id] = item

    if not deduped:
        return {"total": 0, "created": 0, "updated": 0, "unchanged": 0}

    existing: dict[str, MyRepository] = {}
    ids = list(deduped)
    for start in range(0, len(ids), _UPSERT_CHUNK):
        chunk = ids[start : start + _UPSERT_CHUNK]
        rows = db.execute(select(MyRepository).where(MyRepository.id.in_(chunk))).scalars()
        for row in rows:
            existing[row.id] = row

    created = updated = unchanged = 0
    for repo_id, item in deduped.items():
        values: dict[str, Any] = {
            "platform": item.get("platform") or "github",
            "name": item.get("name") or repo_id.split("/")[-1],
            "description": item.get("description") or "",
            "html_url": item.get("html_url") or f"https://github.com/{repo_id}",
            "stars": int(item.get("stars") or 0),
            "language": item.get("language") or None,
        }
        row = existing.get(repo_id)
        if row is None:
            db.add(MyRepository(id=repo_id, **values))
            created += 1
            continue
        changed = any(getattr(row, field) != value for field, value in values.items())
        if changed:
            for field, value in values.items():
                setattr(row, field, value)
            updated += 1
        else:
            unchanged += 1

    db.commit()
    return {"total": len(deduped), "created": created, "updated": updated, "unchanged": unchanged}


async def sync_starred_to_db(
    db: Session,
    token: str,
    *,
    per_page: int = 100,
    max_pages: int | None = None,
    on_progress: Callable[[SyncProgress], None] | None = None,
    client: GitHubClient | None = None,
) -> dict[str, Any]:
    """全量同步 Starred 到本地镜像表。

    返回：`{status, source, pages, durationMs, total, created, updated, unchanged}`；
    抓取失败时额外带 `error` 与 `partial: true`，已抓取部分仍会落库。
    """
    started = time.monotonic()
    last_page = 0

    def _on_progress(progress: SyncProgress) -> None:
        nonlocal last_page
        last_page = max(last_page, progress.page)
        if on_progress is not None:
            on_progress(progress)

    items: list[dict[str, Any]] = []
    error: str | None = None
    try:
        items = await list_starred_repos(
            token,
            per_page=per_page,
            max_pages=max_pages,
            on_progress=_on_progress,
            client=client,
        )
    except GitHubServiceError as exc:
        error = str(exc)[:300]
        logger.warning("Starred 抓取中断（已抓取 %d 条）: %s", len(exc.partial_items), error)
        # 原始条目可能是 `{starred_at, repo}` 包装，复用服务层标准化逻辑。
        items = normalize_starred(exc.partial_items)

    if on_progress is not None:
        on_progress(
            SyncProgress(
                phase="save",
                page=last_page,
                pages_total=last_page or None,
                fetched=len(items),
                total=len(items),
            )
        )

    counts = upsert_repositories(db, items)
    duration_ms = int((time.monotonic() - started) * 1000)
    result: dict[str, Any] = {
        "status": "error" if error else "ok",
        "source": "starred",
        "pages": last_page,
        "durationMs": duration_ms,
        **counts,
    }
    if error:
        result["error"] = error
        result["partial"] = True

    if on_progress is not None:
        on_progress(
            SyncProgress(
                phase="done",
                page=last_page,
                pages_total=last_page or None,
                fetched=len(items),
                total=len(items),
                done=True,
            )
        )
    logger.info(
        "Starred 同步完成: 共 %d 条（新增 %d / 更新 %d / 未变化 %d），耗时 %dms",
        counts["total"],
        counts["created"],
        counts["updated"],
        counts["unchanged"],
        duration_ms,
    )
    return result

