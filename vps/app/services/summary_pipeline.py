"""README 摘要批量管线（REQ-202610-0905 / M1-13，REQ-202610-0912 / M2-04 扩展）。

职责：
1. 为同步入库的仓库 / 热榜仓库抓取 README、清洗并生成中文摘要
   （Ollama → DeepSeek → 截断降级）；
2. 按批处理并逐批提交，控制单次任务的内存与推理预算；
3. 对每条摘要做质量评分，按比例留存抽检样本（低质量强制留存）；
4. 可选把摘要批量回写 edge / D1（配置 `EDGE_BASE_URL` 时）。

设计约束：任何外部依赖失败都不抛异常，返回结构化统计，保证 Celery 任务可重试。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional
from uuid import uuid4

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import MyRepository, TrendingRepository
from app.services.fulltext import save_readme
from app.services.github_service import get_readme
from app.services.readme import clean_readme
from app.services.summarizer import SummaryResult, summarize_with_source
from app.services.summary_quality import (
    evaluate_summary,
    record_quality_sample,
    should_sample,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]

SUPPORTED_SOURCES = ("my", "trending")
SUMMARY_SOURCES = ("my", "trending", "all")


@dataclass
class RepoSummaryOutcome:
    """单个仓库的摘要结果。"""

    repo_id: str
    summary: str = ""
    source: str = "empty"  # ollama | deepseek | truncated | empty | error
    model: str = ""
    error: str = ""
    readme: str = ""  # 清洗后的 README 全文（M6-01 落全文镜像）


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
        readme=cleaned,
    )


def _select_repositories(
    db: Session,
    *,
    source: str,
    repo_ids: Optional[Iterable[str]],
    limit: int,
    force: bool,
) -> list[Any]:
    """按来源选择待摘要仓库：默认只选摘要为空的，按热度降序。"""
    if source == "my":
        model = MyRepository
        order = (MyRepository.stars.desc(), MyRepository.id.asc())
    elif source == "trending":
        model = TrendingRepository
        order = (TrendingRepository.stars_today.desc(), TrendingRepository.id.asc())
    else:
        raise ValueError(f"unsupported summary source: {source}")

    stmt = select(model).order_by(*order)
    if repo_ids:
        ids = [str(item).strip() for item in repo_ids if str(item).strip()]
        if not ids:
            return []
        stmt = stmt.where(model.id.in_(ids))
    if not force:
        stmt = stmt.where(or_(model.readme_summary.is_(None), func.trim(model.readme_summary) == ""))
    return list(db.execute(stmt.limit(max(1, int(limit)))).scalars().all())


def writeback_summaries(
    items: list[dict[str, str]], *, batch_size: int = 100, source: str = "my"
) -> dict[str, Any]:
    """把摘要批量回写 edge（D1）；未配置 `EDGE_BASE_URL` 时跳过。"""
    settings = get_settings()
    base = (settings.EDGE_BASE_URL or "").strip().rstrip("/")
    if not base:
        return {"status": "skipped", "reason": "EDGE_BASE_URL 未配置"}
    if not items:
        return {"status": "skipped", "reason": "无摘要可回写"}

    path = "/api/repos/summaries" if source == "my" else "/api/trending/summaries"
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
                resp = client.post(f"{base}{path}", json={"items": chunk}, headers=headers)
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


def _empty_stats(source: str, batch_id: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "source": source,
        "batchId": batch_id,
        "total": 0,
        "processed": 0,
        "summarized": 0,
        "skipped": 0,
        "failed": 0,
        "readmeIndexed": 0,
        "sources": {},
        "sampled": 0,
        "samples": [],
        "quality": {
            "evaluated": 0,
            "avgScore": 0.0,
            "passed": 0,
            "failed": 0,
            "pending": 0,
        },
        "writeback": {"status": "skipped", "reason": "未执行"},
    }


def _summarize_source(
    *,
    source: str,
    repo_ids: Optional[Iterable[str]],
    limit_value: int,
    batch_value: int,
    force: bool,
    max_chars_value: int,
    delay_seconds: float,
    token: str,
    batch_id: str,
    progress: Optional[ProgressCallback],
    sleep_fn: Callable[[float], None],
) -> dict[str, Any]:
    """单来源批量摘要（my / trending），返回结构化统计。"""
    settings = get_settings()
    max_samples = max(0, int(settings.SUMMARY_SAMPLE_MAX_PER_RUN))
    stats = _empty_stats(source, batch_id)
    items: list[dict[str, str]] = []
    quality_scores: list[float] = []
    db = SessionLocal()
    try:
        rows = _select_repositories(
            db, source=source, repo_ids=repo_ids, limit=limit_value, force=force
        )
        stats["total"] = len(rows)
        if not rows:
            return stats

        for index, row in enumerate(rows, start=1):
            outcome = summarize_one(row.id, token=token, max_chars=max_chars_value)
            stats["processed"] += 1

            # M6-01：摘要管线已抓到 README，顺带落全文镜像，避免二次请求 GitHub
            if settings.FTS_AUTO_INDEX and outcome.readme:
                try:
                    save_readme(
                        db,
                        source=source,
                        repo_id=row.id,
                        content=outcome.readme,
                        commit=False,
                    )
                    stats["readmeIndexed"] += 1
                except Exception:  # noqa: BLE001 - 索引失败不影响摘要主流程
                    logger.warning("README 全文镜像写入失败：%s", row.id, exc_info=True)

            if outcome.summary:
                row.readme_summary = outcome.summary
                stats["summarized"] += 1
                stats["sources"][outcome.source] = stats["sources"].get(outcome.source, 0) + 1
                items.append({"repoId": row.id, "summary": outcome.summary})

                # 每条摘要都做质量评估；按比例抽样，低质量强制留存
                report = evaluate_summary(
                    outcome.summary, max_chars=max_chars_value, source=outcome.source
                )
                quality_scores.append(report.score)
                stats["quality"]["evaluated"] += 1
                if report.verdict == "pass":
                    stats["quality"]["passed"] += 1
                else:
                    stats["quality"]["failed"] += 1

                if stats["sampled"] < max_samples and should_sample(
                    batch_id=batch_id,
                    repo_source=source,
                    repo_id=row.id,
                    score=report.score,
                ):
                    sample = record_quality_sample(
                        db,
                        batch_id=batch_id,
                        repo_id=row.id,
                        repo_source=source,
                        summary=outcome.summary,
                        source=outcome.source,
                        model=outcome.model,
                        max_chars=max_chars_value,
                        report=report,
                    )
                    stats["sampled"] += 1
                    stats["quality"]["pending"] += 1
                    stats["samples"].append(sample.id)
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
                            "source": source,
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
        if quality_scores:
            stats["quality"]["avgScore"] = round(
                sum(quality_scores) / len(quality_scores), 1
            )
        stats["writeback"] = writeback_summaries(items, source=source)
        return stats
    except Exception as exc:  # noqa: BLE001 - 批量任务整体失败时回滚并返回结构化错误
        db.rollback()
        logger.exception("README 摘要批量任务失败（source=%s）", source)
        stats["status"] = "error"
        stats["error"] = str(exc)[:300]
        return stats
    finally:
        db.close()


def _merge_stats(parts: dict[str, dict[str, Any]], batch_id: str) -> dict[str, Any]:
    """合并多来源统计（source=all）。"""
    merged = _empty_stats("all", batch_id)
    merged["writeback"] = {}
    merged["bySource"] = {}
    quality_weight = 0.0
    quality_evaluated = 0
    statuses = []
    for source, stats in parts.items():
        statuses.append(stats.get("status", "ok"))
        merged["bySource"][source] = {
            key: stats.get(key)
            for key in (
                "total",
                "processed",
                "summarized",
                "skipped",
                "failed",
                "readmeIndexed",
                "sampled",
                "writeback",
            )
        }
        for key in (
            "total",
            "processed",
            "summarized",
            "skipped",
            "failed",
            "readmeIndexed",
            "sampled",
        ):
            merged[key] += int(stats.get(key) or 0)
        merged["samples"].extend(stats.get("samples") or [])
        for src, count in (stats.get("sources") or {}).items():
            merged["sources"][src] = merged["sources"].get(src, 0) + int(count)
        quality = stats.get("quality") or {}
        evaluated = int(quality.get("evaluated") or 0)
        if evaluated:
            quality_weight += float(quality.get("avgScore") or 0) * evaluated
            quality_evaluated += evaluated
        for key in ("evaluated", "passed", "failed", "pending"):
            merged["quality"][key] += int(quality.get(key) or 0)
        merged["writeback"][source] = stats.get("writeback")
        if stats.get("errors"):
            merged.setdefault("errors", []).extend(stats["errors"])
    if quality_evaluated:
        merged["quality"]["avgScore"] = round(quality_weight / quality_evaluated, 1)
    if all(status == "error" for status in statuses):
        merged["status"] = "error"
    elif any(status == "error" for status in statuses):
        merged["status"] = "partial"
    return merged


def summarize_repositories(
    *,
    repo_ids: Optional[Iterable[str]] = None,
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
    force: bool = False,
    max_chars: Optional[int] = None,
    source: str = "my",
    batch_id: Optional[str] = None,
    progress: Optional[ProgressCallback] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """批量生成 README 摘要并落库；返回可直接作为 Celery 结果的统计字典。

    `source`：`my`（我的仓库）/ `trending`（热榜）/ `all`（两者串行）。
    """
    settings = get_settings()
    source_value = (source or "my").strip().lower()
    if source_value not in SUMMARY_SOURCES:
        source_value = "my"
    limit_value = max(1, int(limit if limit is not None else settings.SUMMARY_MAX_PER_RUN))
    batch_value = max(1, int(batch_size if batch_size is not None else settings.SUMMARY_BATCH_SIZE))
    max_chars_value = max(200, int(max_chars if max_chars is not None else settings.SUMMARY_MAX_CHARS))
    delay_seconds = max(0, int(settings.SUMMARY_DELAY_MS)) / 1000.0
    token = (settings.GITHUB_TOKEN or "").strip()
    batch_value_id = (batch_id or uuid4().hex).strip()

    if source_value == "all":
        parts: dict[str, dict[str, Any]] = {}
        for item_source in SUPPORTED_SOURCES:
            parts[item_source] = _summarize_source(
                source=item_source,
                repo_ids=repo_ids,
                limit_value=limit_value,
                batch_value=batch_value,
                force=force,
                max_chars_value=max_chars_value,
                delay_seconds=delay_seconds,
                token=token,
                batch_id=batch_value_id,
                progress=progress,
                sleep_fn=sleep_fn,
            )
        return _merge_stats(parts, batch_value_id)

    return _summarize_source(
        source=source_value,
        repo_ids=repo_ids,
        limit_value=limit_value,
        batch_value=batch_value,
        force=force,
        max_chars_value=max_chars_value,
        delay_seconds=delay_seconds,
        token=token,
        batch_id=batch_value_id,
        progress=progress,
        sleep_fn=sleep_fn,
    )
