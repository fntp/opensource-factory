"""README 摘要批量管线（REQ-202610-0905 / M1-13）。

职责：
1. 为同步入库的仓库抓取 README、清洗并生成中文摘要（Ollama → DeepSeek → 截断降级）；
2. 按批处理并逐批提交，控制单次任务的内存与推理预算；
3. 可选把摘要批量回写 edge / D1（配置 `EDGE_BASE_URL` 时）。

设计约束：任何外部依赖失败都不抛异常，返回结构化统计，保证 Celery 任务可重试。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import MyRepository
from app.services.github_service import get_readme
from app.services.readme import clean_readme
from app.services.summarizer import SummaryResult, summarize_with_source

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass
class RepoSummaryOutcome:
    """单个仓库的摘要结果。"""

    repo_id: str
    summary: str = ""
    source: str = "empty"  # ollama | deepseek | truncated | empty | error
    model: str = ""
    error: str = ""


def _run_async(coro: Any) -> Any:
    """在同步 Celery 任务中执行协程；若已处于事件循环，另起线程执行。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def summarize_one(repo_id: str, *, token: str = "", max_chars: int = 800) -> RepoSummaryOutcome:
    """抓取并摘要单个仓库；README 不可用时返回 skipped 语义。"""
    try:
        raw = _run_async(get_readme(token, repo_id))
    except Exception as exc:  # noqa: BLE001 - 网络失败降级为单条失败，不阻塞整批
        logger.warning("读取 README 失败 %s: %s", repo_id, exc)
        return RepoSummaryOutcome(repo_id=repo_id, source="error", error=str(exc)[:300])

    cleaned = clean_readme(raw)
    if not cleaned:
        return RepoSummaryOutcome(repo_id=repo_id, source="empty", error="README 为空或不可用")

    result: SummaryResult = summarize_with_source(cleaned, max_chars=max_chars)
    return RepoSummaryOutcome(
        repo_id=repo_id,
        summary=result.text,
        source=result.source,
        model=result.model,
    )


def _select_repositories(
    db: Session,
    *,
    repo_ids: Optional[Iterable[str]],
    limit: int,
    force: bool,
) -> list[MyRepository]:
    """选择待摘要仓库：默认只选摘要为空的，按 Star 降序。"""
    stmt = select(MyRepository).order_by(MyRepository.stars.desc(), MyRepository.id.asc())
    if repo_ids:
        ids = [str(item).strip() for item in repo_ids if str(item).strip()]
        if not ids:
            return []
        stmt = stmt.where(MyRepository.id.in_(ids))
    if not force:
        stmt = stmt.where(
            or_(MyRepository.readme_summary.is_(None), func.trim(MyRepository.readme_summary) == "")
        )
    return list(db.execute(stmt.limit(max(1, int(limit)))).scalars().all())


def writeback_summaries(items: list[dict[str, str]], *, batch_size: int = 100) -> dict[str, Any]:
    """把摘要批量回写 edge（D1）；未配置 `EDGE_BASE_URL` 时跳过。"""
    settings = get_settings()
    base = (settings.EDGE_BASE_URL or "").strip().rstrip("/")
    if not base:
        return {"status": "skipped", "reason": "EDGE_BASE_URL 未配置"}
    if not items:
        return {"status": "skipped", "reason": "无摘要可回写"}

    headers = {"Content-Type": "application/json"}
    token = (settings.INTERNAL_TOKEN or "").strip()
    if token:
        headers["X-Internal-Token"] = token

    updated = 0
    batches = 0
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            for start in range(0, len(items), batch_size):
                chunk = items[start : start + batch_size]
                resp = client.post(f"{base}/api/repos/summaries", json={"items": chunk}, headers=headers)
                if resp.status_code != 200:
                    logger.warning("摘要回写 edge 失败：HTTP %s", resp.status_code)
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
    except Exception as exc:  # noqa: BLE001 - 回写失败不影响本地摘要落库
        logger.warning("摘要回写 edge 异常：%s", exc)
        return {"status": "error", "error": str(exc)[:200], "updated": updated, "batches": batches}


def summarize_repositories(
    *,
    repo_ids: Optional[Iterable[str]] = None,
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
    force: bool = False,
    max_chars: Optional[int] = None,
    progress: Optional[ProgressCallback] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """批量生成 README 摘要并落库；返回可直接作为 Celery 结果的统计字典。"""
    settings = get_settings()
    limit_value = max(1, int(limit if limit is not None else settings.SUMMARY_MAX_PER_RUN))
    batch_value = max(1, int(batch_size if batch_size is not None else settings.SUMMARY_BATCH_SIZE))
    max_chars_value = max(200, int(max_chars if max_chars is not None else settings.SUMMARY_MAX_CHARS))
    delay_seconds = max(0, int(settings.SUMMARY_DELAY_MS)) / 1000.0
    token = (settings.GITHUB_TOKEN or "").strip()

    stats: dict[str, Any] = {
        "status": "ok",
        "total": 0,
        "processed": 0,
        "summarized": 0,
        "skipped": 0,
        "failed": 0,
        "sources": {},
        "writeback": {"status": "skipped", "reason": "未执行"},
    }
    items: list[dict[str, str]] = []
    db = SessionLocal()
    try:
        rows = _select_repositories(db, repo_ids=repo_ids, limit=limit_value, force=force)
        stats["total"] = len(rows)
        if not rows:
            return stats

        for index, row in enumerate(rows, start=1):
            outcome = summarize_one(row.id, token=token, max_chars=max_chars_value)
            stats["processed"] += 1

            if outcome.summary:
                row.readme_summary = outcome.summary
                stats["summarized"] += 1
                stats["sources"][outcome.source] = stats["sources"].get(outcome.source, 0) + 1
                items.append({"repoId": row.id, "summary": outcome.summary})
            elif outcome.source == "empty":
                stats["skipped"] += 1
            else:
                stats["failed"] += 1
                stats.setdefault("errors", []).append(
                    {"repoId": row.id, "error": outcome.error or "unknown"}
                )

            if progress is not None:
                try:
                    progress(
                        {
                            "phase": "summarizing",
                            "processed": stats["processed"],
                            "total": stats["total"],
                            "percent": round(stats["processed"] * 100 / stats["total"]),
                            "current": row.id,
                        }
                    )
                except Exception:  # noqa: BLE001 - 进度上报失败不影响主流程
                    logger.debug("摘要进度回调失败", exc_info=True)

            if delay_seconds and index < len(rows):
                sleep_fn(delay_seconds)

            # 每批提交一次，避免长事务与内存峰值
            if index % batch_value == 0:
                db.commit()

        db.commit()
        stats["writeback"] = writeback_summaries(items)
        return stats
    except Exception as exc:  # noqa: BLE001 - 批量任务整体失败时回滚并返回结构化错误
        db.rollback()
        logger.exception("README 摘要批量任务失败")
        stats["status"] = "error"
        stats["error"] = str(exc)[:300]
        return stats
    finally:
        db.close()
