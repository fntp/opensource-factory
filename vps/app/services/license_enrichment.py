"""License 异步补全服务（M6-06）。

GitHub Trending HTML 不含 License，收藏库也可能在早期同步时缺失元数据；
本服务按来源批量补全：GitHub API `license` 对象优先，缺失时回退 README 启发式。
补全结果写入 VPS SQLite，并在配置 `EDGE_BASE_URL` 时批量回写 edge / D1。

所有外部调用都可注入（`fetch_repo` / `fetch_readme`），测试不访问网络。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MyRepository, TrendingRepository
from app.services.license import detect_license_from_readme

logger = logging.getLogger(__name__)

RepoFetcher = Callable[[Optional[str], str], Optional[dict[str, Any]]]
ReadmeFetcher = Callable[[Optional[str], str], str]

SUPPORTED_SCOPES = ("my", "trending", "all")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _run_async(coro: Any) -> Any:
    """在同步任务中执行协程；已处于事件循环时另起线程。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _default_fetch_repo(token: Optional[str], repo_id: str) -> Optional[dict[str, Any]]:
    from app.services.github_service import get_repo

    return _run_async(get_repo(token, repo_id))


def _default_fetch_readme(token: Optional[str], repo_id: str) -> str:
    from app.services.github_service import get_readme

    return _run_async(get_readme(token, repo_id))


def _select_rows(
    db: Session,
    model: type[MyRepository] | type[TrendingRepository],
    *,
    limit: int,
    force: bool,
) -> list[Any]:
    if model is MyRepository:
        order = (MyRepository.stars.desc(), MyRepository.id.asc())
    else:
        order = (TrendingRepository.stars_today.desc(), TrendingRepository.id.asc())
    stmt = select(model).order_by(*order).limit(max(1, int(limit)))
    if not force:
        stmt = stmt.where(
            or_(model.license_checked_at.is_(None), model.license_source.is_(None))
        )
    return list(db.execute(stmt).scalars().all())


def _enrich_scope(
    db: Session,
    model: type[MyRepository] | type[TrendingRepository],
    scope: str,
    *,
    limit: int,
    force: bool,
    token: Optional[str],
    fetch_repo: RepoFetcher,
    fetch_readme: ReadmeFetcher,
) -> dict[str, Any]:
    rows = _select_rows(db, model, limit=limit, force=force)
    now = _utcnow()
    items: list[dict[str, Any]] = []
    detected = 0
    unknown = 0
    failed = 0

    for row in rows:
        try:
            repo_data = fetch_repo(token, row.id)
        except Exception as exc:  # noqa: BLE001 - 单个仓库失败不阻断整批
            logger.warning("License 补全失败 %s: %s", row.id, exc)
            failed += 1
            continue
        if not repo_data:
            failed += 1
            continue

        spdx = str(repo_data.get("license_spdx") or "").strip()
        name = str(repo_data.get("license_name") or "").strip()
        source = str(repo_data.get("license_source") or "none").strip() or "none"

        if not spdx:
            try:
                readme = fetch_readme(token, row.id) or ""
            except Exception as exc:  # noqa: BLE001 - README 失败按无许可证处理
                logger.info("License README 回退失败 %s: %s", row.id, exc)
                readme = ""
            hint = detect_license_from_readme(readme)
            if hint:
                spdx = hint["spdxId"]
                name = hint["name"]
                source = "readme"

        row.license_spdx = spdx or None
        row.license_name = name or None
        row.license_source = source
        row.license_checked_at = now
        if spdx:
            detected += 1
        else:
            unknown += 1
        items.append(
            {
                "repoId": row.id,
                "spdxId": spdx or None,
                "name": name or None,
                "source": source,
                "checkedAt": now.isoformat(),
            }
        )

    db.commit()
    return {
        "scope": scope,
        "scanned": len(rows),
        "detected": detected,
        "unknown": unknown,
        "failed": failed,
        "items": items,
    }


def enrich_licenses(
    db: Session,
    *,
    scope: str = "all",
    limit: int = 200,
    force: bool = False,
    token: Optional[str] = None,
    fetch_repo: Optional[RepoFetcher] = None,
    fetch_readme: Optional[ReadmeFetcher] = None,
) -> dict[str, Any]:
    """补全指定范围的 License，返回统计与待回写条目。"""
    if scope not in SUPPORTED_SCOPES:
        raise ValueError(f"unsupported scope: {scope}")
    repo_fetcher = fetch_repo or _default_fetch_repo
    readme_fetcher = fetch_readme or _default_fetch_readme

    parts: list[dict[str, Any]] = []
    if scope in ("my", "all"):
        parts.append(
            _enrich_scope(
                db,
                MyRepository,
                "my",
                limit=limit,
                force=force,
                token=token,
                fetch_repo=repo_fetcher,
                fetch_readme=readme_fetcher,
            )
        )
    if scope in ("trending", "all"):
        parts.append(
            _enrich_scope(
                db,
                TrendingRepository,
                "trending",
                limit=limit,
                force=force,
                token=token,
                fetch_repo=repo_fetcher,
                fetch_readme=readme_fetcher,
            )
        )

    return {
        "scope": scope,
        "scanned": sum(part["scanned"] for part in parts),
        "detected": sum(part["detected"] for part in parts),
        "unknown": sum(part["unknown"] for part in parts),
        "failed": sum(part["failed"] for part in parts),
        "scopes": parts,
    }


def writeback_licenses(scope: str, items: list[dict[str, Any]], *, batch_size: int = 100) -> dict[str, Any]:
    """把补全结果批量回写 edge / D1；未配置 `EDGE_BASE_URL` 时跳过。"""
    settings = get_settings()
    base = (settings.EDGE_BASE_URL or "").strip().rstrip("/")
    if not base:
        return {"status": "skipped", "reason": "EDGE_BASE_URL 未配置"}
    if not items:
        return {"status": "skipped", "reason": "无 License 可回写"}

    headers = {"Content-Type": "application/json"}
    token = (settings.INTERNAL_TOKEN or "").strip()
    if token:
        headers["X-Internal-Token"] = token

    updated = 0
    batches = 0
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            for start in range(0, len(items), max(1, batch_size)):
                chunk = items[start : start + batch_size]
                resp = client.post(
                    f"{base}/api/internal/licenses",
                    json={"scope": scope, "items": chunk},
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.warning("License 回写 edge 失败：HTTP %s", resp.status_code)
                    return {
                        "status": "error",
                        "error": f"edge HTTP {resp.status_code}",
                        "updated": updated,
                        "batches": batches,
                    }
                data = resp.json() or {}
                updated += int(data.get("updated") or 0)
                batches += 1
        return {"status": "ok", "updated": updated, "batches": batches}
    except Exception as exc:  # noqa: BLE001 - 回写失败不影响本地落库
        logger.warning("License 回写 edge 异常：%s", exc)
        return {
            "status": "error",
            "error": str(exc)[:200],
            "updated": updated,
            "batches": batches,
        }
