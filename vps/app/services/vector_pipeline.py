"""向量化管线：收藏库 + 热榜的批量 / 增量 / 断点续跑。

设计要点：

- 向量持久化在本地 `repo_vectors`（source + repo_id 唯一），不依赖任何外部服务；
- 增量判断：文本 SHA-256 + 模型名 + 编码后端，三者一致才跳过；
- 批量：keyset 分页逐批读取，每批编码 / upsert / 提交，内存占用与批量大小成正比；
- 断点续跑：`vectorization_runs` 记录游标（source + repo_id），失败后用同一 runId 继续；
- 编码统一走 `EmbeddingService`，模型缺失时自动降级为确定性 hash 向量。
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import MyRepository, RepoVector, TrendingRepository, VectorizationRun
from app.services.embedding import EmbeddingService, get_embedding_service

logger = logging.getLogger(__name__)

SOURCES: tuple[str, ...] = ("my", "trending")
SCOPES: tuple[str, ...] = ("my", "trending", "all")
MAX_BATCH_SIZE = 256
ProgressCallback = Callable[[dict[str, Any]], None]


class VectorRunError(RuntimeError):
    """向量化运行参数 / 状态错误。"""


class RunNotFound(VectorRunError):
    """运行 id 不存在。"""


class RunFinished(VectorRunError):
    """运行已完成，不能重复执行。"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_scope(scope: str) -> str:
    value = (scope or "all").strip().lower()
    if value not in SCOPES:
        raise VectorRunError(f"非法 scope：{scope}（可选 my / trending / all）")
    return value


def sources_for(scope: str) -> list[str]:
    normalized = normalize_scope(scope)
    return list(SOURCES) if normalized == "all" else [normalized]


def _model_class(source: str):
    return MyRepository if source == "my" else TrendingRepository


def _build_text_values(
    source: str,
    repo_id: str,
    name: Any,
    description: Any,
    extra1: Any = None,
    extra2: Any = None,
) -> str:
    """按来源拼接文本；空白归一化，保证增量哈希稳定。"""
    if source == "my":
        parts = [name, description, extra1, extra2]
    else:
        parts = [name, description, extra1]
    text = " ".join(str(part).strip() for part in parts if part is not None and str(part).strip())
    text = " ".join(text.split())
    return text or str(repo_id)


def build_repo_text(source: str, row: Any) -> str:
    if source == "my":
        return _build_text_values(
            source, row.id, row.name, row.description, row.readme_summary, row.language
        )
    return _build_text_values(source, row.id, row.name, row.description, row.tech_stack)


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _count_pending(
    db: Session,
    scope: str,
    limit: int,
    model: str,
    backend: str,
    force: bool,
) -> tuple[int, int]:
    """统计待处理（缺失 / 内容或模型变化）的仓库数，返回 (pending, unchanged)。

    `limit` 只限制待处理条数，已向量化且未变化的仓库只计入 unchanged，不占预算，
    避免大库场景下每轮都只扫描前 N 条、永远轮不到后面的仓库。
    """
    pending = 0
    unchanged = 0
    for source in sources_for(scope):
        model_class = _model_class(source)
        existing = {
            repo_id: (text_hash, item_model, item_backend)
            for repo_id, text_hash, item_model, item_backend in db.execute(
                select(
                    RepoVector.repo_id,
                    RepoVector.text_hash,
                    RepoVector.model,
                    RepoVector.backend,
                ).where(RepoVector.source == source)
            ).all()
        }

        if source == "my":
            columns = (
                model_class.id,
                model_class.name,
                model_class.description,
                model_class.readme_summary,
                model_class.language,
            )
        else:
            columns = (
                model_class.id,
                model_class.name,
                model_class.description,
                model_class.tech_stack,
            )

        stmt = select(*columns).order_by(model_class.id)
        for row in db.execute(stmt).yield_per(500):
            repo_id = row[0]
            text = _build_text_values(
                source,
                repo_id,
                row[1],
                row[2],
                row[3] if len(row) > 3 else None,
                row[4] if len(row) > 4 else None,
            )
            digest = text_digest(text)
            previous = existing.get(repo_id)
            if (
                not force
                and previous is not None
                and previous[0] == digest
                and previous[1] == model
                and previous[2] == backend
            ):
                unchanged += 1
                continue
            pending += 1
            if pending >= limit:
                return pending, unchanged
    return pending, unchanged


def create_run(
    db: Session,
    *,
    scope: str = "all",
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
    force: bool = False,
    run_id: Optional[str] = None,
) -> VectorizationRun:
    """创建（或恢复）一条运行记录；恢复时保留已有计数与游标。"""
    settings = get_settings()
    normalized = normalize_scope(scope)
    effective_limit = max(1, int(limit or settings.VECTORIZE_MAX_PER_RUN))
    effective_batch = max(1, min(MAX_BATCH_SIZE, int(batch_size or settings.VECTORIZE_BATCH_SIZE)))

    if run_id:
        run = db.get(VectorizationRun, run_id)
        if run is None:
            raise RunNotFound(f"运行不存在：{run_id}")
        if run.status == "completed":
            raise RunFinished(f"运行已完成，不能重复执行：{run_id}")
        run.status = "running"
        run.error = None
        run.finished_at = None
        db.commit()
        return run

    run = VectorizationRun(
        id=uuid4().hex,
        scope=normalized,
        status="running",
        model=settings.EMBEDDING_MODEL,
        backend="",
        dim=0,
        force=bool(force),
        limit=effective_limit,
        batch_size=effective_batch,
        total=0,  # 待处理数量在任务开始时统计（需要已知 model / backend）
    )
    db.add(run)
    db.commit()
    return run


def _progress_meta(run: VectorizationRun, source: Optional[str] = None) -> dict[str, Any]:
    percent = round((run.processed / run.total) * 100, 1) if run.total else 100.0
    return {
        "runId": run.id,
        "scope": run.scope,
        "status": run.status,
        "source": source or run.cursor_source,
        "total": run.total,
        "processed": run.processed,
        "percent": percent,
        "vectorized": run.vectorized,
        "skipped": run.skipped,
        "failed": run.failed,
    }


def _notify(progress: Optional[ProgressCallback], meta: dict[str, Any]) -> None:
    if progress is not None:
        progress(meta)


def _process_batch(
    db: Session,
    run: VectorizationRun,
    source: str,
    rows: list[Any],
    service: EmbeddingService,
    model: str,
    backend: str,
) -> int:
    """处理一批仓库：跳过未变化项，其余批量编码并 upsert。

    返回本批实际尝试编码的条数（含编码失败项），供调用方推进 processed 计数。
    """
    ids = [row.id for row in rows]
    existing_rows = (
        db.execute(
            select(RepoVector).where(RepoVector.source == source, RepoVector.repo_id.in_(ids))
        )
        .scalars()
        .all()
    )
    existing = {item.repo_id: item for item in existing_rows}

    pending: list[tuple[Any, str, str, Optional[RepoVector]]] = []
    for row in rows:
        text = build_repo_text(source, row)
        digest = text_digest(text)
        previous = existing.get(row.id)
        if (
            not run.force
            and previous is not None
            and previous.text_hash == digest
            and previous.model == model
            and previous.backend == backend
        ):
            run.skipped += 1
            if run.dim == 0 and previous.dim:
                run.dim = previous.dim
            continue
        pending.append((row, text, digest, previous))

    if not pending:
        return 0

    try:
        vectors = service.encode([item[1] for item in pending])
    except Exception as exc:  # noqa: BLE001 - 单批编码失败不拖垮整个运行
        logger.exception("向量编码失败（source=%s, batch=%d）：%s", source, len(pending), exc)
        run.failed += len(pending)
        return len(pending)

    if len(vectors) != len(pending):
        logger.warning(
            "向量返回数量不匹配（source=%s, 期望 %d, 实际 %d）", source, len(pending), len(vectors)
        )

    for index, (row, _text, digest, previous) in enumerate(pending):
        vector = vectors[index] if index < len(vectors) else []
        if not vector:
            run.failed += 1
            continue
        payload = json.dumps([round(float(value), 6) for value in vector], separators=(",", ":"))
        if previous is None:
            db.add(
                RepoVector(
                    source=source,
                    repo_id=row.id,
                    model=model,
                    backend=backend,
                    dim=len(vector),
                    text_hash=digest,
                    vector=payload,
                )
            )
        else:
            previous.model = model
            previous.backend = backend
            previous.dim = len(vector)
            previous.text_hash = digest
            previous.vector = payload
            previous.updated_at = _utcnow()
        run.vectorized += 1
        run.dim = len(vector)
    return len(pending)


def run_vectorization(
    run_id: str,
    *,
    service: Optional[EmbeddingService] = None,
    progress: Optional[ProgressCallback] = None,
) -> dict[str, Any]:
    """执行（或续跑）一条运行记录；失败时标记 failed 并抛出异常。"""
    db = SessionLocal()
    try:
        run = db.get(VectorizationRun, run_id)
        if run is None:
            raise RunNotFound(f"运行不存在：{run_id}")
        if run.status == "completed":
            raise RunFinished(f"运行已完成，不能重复执行：{run_id}")

        embedding = service or get_embedding_service()
        backend = embedding.backend
        model = embedding.model_name
        if run.processed > 0:
            if run.model and run.model != model:
                raise VectorRunError(
                    f"运行使用的模型已变更（{run.model} → {model}），请新建运行"
                )
            if run.backend and run.backend != backend:
                raise VectorRunError(
                    f"运行使用的编码后端已变更（{run.backend} → {backend}），请新建运行"
                )

        run.status = "running"
        run.model = model
        run.backend = backend
        run.error = None
        run.finished_at = None
        db.commit()

        # 新运行在真正开始时统计待处理量（增量下 skipped 不计入 total，也不占 limit 预算）。
        if run.processed == 0 and run.total == 0:
            pending, unchanged = _count_pending(
                db, run.scope, run.limit, model, backend, run.force
            )
            run.total = pending
            if pending == 0:
                run.skipped = unchanged
            db.commit()

        _notify(progress, _progress_meta(run))

        for source in sources_for(run.scope):
            if run.cursor_source and source < run.cursor_source:
                continue
            after = run.cursor_repo_id if source == run.cursor_source else None
            model_class = _model_class(source)
            while run.processed < run.total:
                stmt = select(model_class).order_by(model_class.id).limit(run.batch_size)
                if after:
                    stmt = stmt.where(model_class.id > after)
                rows = list(db.execute(stmt).scalars().all())
                if not rows:
                    break

                attempted = _process_batch(db, run, source, rows, embedding, model, backend)
                run.cursor_source = source
                run.cursor_repo_id = rows[-1].id
                run.processed += attempted
                db.commit()
                _notify(progress, _progress_meta(run, source))
                after = rows[-1].id
            if run.processed >= run.total:
                break

        # 运行期间数据被删除时，避免留下 processed < total 的假象。
        if run.processed < run.total:
            run.total = run.processed
        run.status = "completed"
        run.finished_at = _utcnow()
        db.commit()
        _notify(progress, _progress_meta(run))
        logger.info(
            "向量化完成: run=%s scope=%s processed=%d vectorized=%d skipped=%d failed=%d",
            run.id,
            run.scope,
            run.processed,
            run.vectorized,
            run.skipped,
            run.failed,
        )
        return run_to_dict(run)
    except Exception as exc:
        db.rollback()
        failed = db.get(VectorizationRun, run_id)
        if failed is not None:
            failed.status = "failed"
            failed.error = str(exc)[:500]
            failed.finished_at = _utcnow()
            db.commit()
        raise
    finally:
        db.close()


def vectorize(
    *,
    scope: str = "all",
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
    force: bool = False,
    service: Optional[EmbeddingService] = None,
    progress: Optional[ProgressCallback] = None,
) -> dict[str, Any]:
    """创建并立即执行一次运行（测试 / 脚本 / 同步调用的便捷入口）。"""
    db = SessionLocal()
    try:
        run = create_run(db, scope=scope, limit=limit, batch_size=batch_size, force=force)
        run_id = run.id
    finally:
        db.close()
    return run_vectorization(run_id, service=service, progress=progress)


def get_run(db: Session, run_id: str) -> VectorizationRun:
    run = db.get(VectorizationRun, run_id)
    if run is None:
        raise RunNotFound(f"运行不存在：{run_id}")
    return run


def list_runs(db: Session, limit: int = 20) -> list[VectorizationRun]:
    return list(
        db.execute(
            select(VectorizationRun)
            .order_by(VectorizationRun.created_at.desc())
            .limit(max(1, min(100, int(limit))))
        )
        .scalars()
        .all()
    )


def get_stats(db: Session) -> dict[str, Any]:
    """向量覆盖率与最近运行统计。"""
    total_vectors = int(db.scalar(select(func.count()).select_from(RepoVector)) or 0)

    by_source = {
        str(source): int(count)
        for source, count in db.execute(
            select(RepoVector.source, func.count()).group_by(RepoVector.source)
        ).all()
    }
    by_model = [
        {"model": str(model), "backend": str(backend), "count": int(count)}
        for model, backend, count in db.execute(
            select(RepoVector.model, RepoVector.backend, func.count())
            .group_by(RepoVector.model, RepoVector.backend)
            .order_by(func.count().desc())
        ).all()
    ]

    repositories: dict[str, Any] = {}
    for source in SOURCES:
        total_repos = int(db.scalar(select(func.count()).select_from(_model_class(source))) or 0)
        vectorized = int(
            db.scalar(
                select(func.count(func.distinct(RepoVector.repo_id))).where(
                    RepoVector.source == source
                )
            )
            or 0
        )
        repositories[source] = {
            "total": total_repos,
            "vectorized": vectorized,
            "pending": max(0, total_repos - vectorized),
        }

    return {
        "totalVectors": total_vectors,
        "bySource": by_source,
        "byModel": by_model,
        "repositories": repositories,
        "latestRuns": [run_to_dict(run) for run in list_runs(db, limit=5)],
    }


def get_vector(db: Session, source: str, repo_id: str) -> Optional[dict[str, Any]]:
    normalized = normalize_scope(source)
    if normalized == "all":
        raise VectorRunError("source 必须是 my 或 trending")
    row = db.get(RepoVector, (normalized, repo_id))
    if row is None:
        return None
    return {
        "source": row.source,
        "repoId": row.repo_id,
        "model": row.model,
        "backend": row.backend,
        "dim": row.dim,
        "textHash": row.text_hash,
        "vector": json.loads(row.vector),
        "updatedAt": row.updated_at,
    }


def run_to_dict(run: VectorizationRun) -> dict[str, Any]:
    return {
        "runId": run.id,
        "scope": run.scope,
        "status": run.status,
        "model": run.model,
        "backend": run.backend,
        "dim": run.dim,
        "force": bool(run.force),
        "limit": run.limit,
        "batchSize": run.batch_size,
        "total": run.total,
        "processed": run.processed,
        "vectorized": run.vectorized,
        "skipped": run.skipped,
        "failed": run.failed,
        "cursorSource": run.cursor_source,
        "cursorRepoId": run.cursor_repo_id,
        "error": run.error,
        "createdAt": run.created_at,
        "updatedAt": run.updated_at,
        "finishedAt": run.finished_at,
    }
