"""Vectorize 索引同步：批量 upsert / 失败重试 / 断点续跑 / 对账。

数据流：本地 `repo_vectors`（M3-02 向量化管线）→ edge 内部接口 → Cloudflare Vectorize。
VPS 不持有 Cloudflare 账号凭据，所有索引操作都经 edge Worker 的 Vectorize 绑定完成。

设计要点：

- 按 `(source, repo_id)` keyset 分页，每批提交后更新运行游标，可断点续跑；
- 以 `text_hash + model + backend + dim` 判断增量，未变化且已同步的向量直接跳过；
- 网络错误 / 429 / 5xx 按指数退避重试，单批最终失败只标记该批，不拖垮整个运行；
- 对账通过 `getByIds` 校验本地 id 是否存在，并可选修复缺失 / 清理孤儿。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional
from urllib import error, request
from uuid import uuid4

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import MyRepository, VectorIndexRun, VectorIndexState

logger = logging.getLogger(__name__)

MAX_BATCH = 1000
MAX_CHECK_BATCH = 100
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _utcnow() -> datetime:
    """统一使用无时区 UTC 时间（与 D1 CURRENT_TIMESTAMP 语义对齐）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EdgeNotConfigured(RuntimeError):
    """边缘地址 / 内部令牌未配置。"""


class EdgeRequestError(RuntimeError):
    """edge 内部接口返回错误。"""

    def __init__(self, message: str, *, status: int = 0, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.status == 0 or self.status in RETRYABLE_STATUS


def vector_id(source: str, repo_id: str) -> str:
    """生成稳定且长度固定的 Vectorize id（35 字符）。

    Vectorize 对 id 长度有限制；直接拼接 `source:repo_id` 在超长仓库名时可能越界，
    因此统一使用 `v1_` + sha256 前 32 位。元数据中保留原始 `repo_id` 供检索与排查。
    """
    digest = hashlib.sha256(f"{source}:{repo_id}".encode("utf-8")).hexdigest()[:32]
    return f"v1_{digest}"


def _clamp_batch(value: int | None, default: int) -> int:
    if value is None:
        return max(1, min(default, MAX_BATCH))
    return max(1, min(int(value), MAX_BATCH))


def _edge_request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    """调用 edge 内部接口；配置缺失时抛 EdgeNotConfigured。"""
    settings = get_settings()
    base = (settings.EDGE_BASE_URL or "").strip().rstrip("/")
    token = (settings.INTERNAL_TOKEN or "").strip()
    if not base or not token:
        raise EdgeNotConfigured("EDGE_BASE_URL / INTERNAL_TOKEN 未配置")

    data = None
    headers = {"X-Internal-Token": token, "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(f"{base}{path}", data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=float(settings.VECTORIZE_SYNC_TIMEOUT_SECONDS)) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:  # type: ignore[union-attr]
        body = ""
        try:
            body = exc.read().decode("utf-8")[:500]
        except Exception:  # noqa: BLE001 - 读取错误体失败不影响主错误
            pass
        retry_after: float | None = None
        header = exc.headers.get("Retry-After") if exc.headers else None
        if header:
            try:
                retry_after = max(0.0, float(header))
            except ValueError:
                retry_after = None
        raise EdgeRequestError(
            f"edge {method} {path} -> HTTP {exc.code}: {body or exc.reason}",
            status=exc.code,
            retry_after=retry_after,
        ) from exc
    except error.URLError as exc:
        raise EdgeRequestError(f"edge {method} {path} 网络错误: {exc.reason}") from exc
    except TimeoutError as exc:
        raise EdgeRequestError(f"edge {method} {path} 超时") from exc


def _with_retry(fn: Callable[[], Any], max_retries: int, base_ms: int) -> Any:
    """指数退避重试；4xx（除 429）不重试。"""
    attempts = max(0, int(max_retries)) + 1
    base = max(0.0, float(base_ms) / 1000.0)
    last: Exception | None = None
    for index in range(attempts):
        try:
            return fn()
        except EdgeRequestError as exc:
            last = exc
            if not exc.retryable or index >= attempts - 1:
                raise
            delay = exc.retry_after if exc.retry_after is not None else base * (2**index)
            time.sleep(min(delay, 8.0))
    raise last  # pragma: no cover - 循环内必然返回或抛出


def _has_repo_vectors(db: Session) -> bool:
    """检查 M3-02 的 repo_vectors 表是否已存在。"""
    try:
        return inspect(db.get_bind()).has_table("repo_vectors")
    except Exception:  # noqa: BLE001 - 检查失败按不存在处理
        return False


def _count_local_vectors(db: Session, scope: str) -> int:
    if not _has_repo_vectors(db):
        return 0
    sql = "SELECT COUNT(*) AS n FROM repo_vectors"
    params: dict[str, Any] = {}
    if scope in ("my", "trending"):
        sql += " WHERE source = :scope"
        params["scope"] = scope
    row = db.execute(text(sql), params).first()
    return int(row[0]) if row else 0


def _load_vector_rows(
    db: Session, scope: str, after_source: str, after_repo_id: str, limit: int
) -> list[dict[str, Any]]:
    """按 (source, repo_id) keyset 分页读取 repo_vectors。"""
    sql = """
        SELECT source, repo_id, model, backend, dim, text_hash, vector
        FROM repo_vectors
        WHERE (:scope = 'all' OR source = :scope)
          AND (:after_source = '' OR source > :after_source
               OR (source = :after_source AND repo_id > :after_repo_id))
        ORDER BY source, repo_id
        LIMIT :limit
    """
    rows = db.execute(
        text(sql),
        {
            "scope": scope,
            "after_source": after_source,
            "after_repo_id": after_repo_id,
            "limit": int(limit),
        },
    ).mappings()
    return [dict(row) for row in rows]


def _state_map(db: Session, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], VectorIndexState]:
    grouped: dict[str, list[str]] = {}
    for source, repo_id in keys:
        grouped.setdefault(source, []).append(repo_id)
    result: dict[tuple[str, str], VectorIndexState] = {}
    for source, repo_ids in grouped.items():
        rows = db.scalars(
            select(VectorIndexState).where(
                VectorIndexState.source == source,
                VectorIndexState.repo_id.in_(repo_ids),
            )
        ).all()
        for row in rows:
            result[(row.source, row.repo_id)] = row
    return result


def _language_map(db: Session, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], str]:
    grouped: dict[str, list[str]] = {}
    for source, repo_id in keys:
        grouped.setdefault(source, []).append(repo_id)
    result: dict[tuple[str, str], str] = {}
    if grouped.get("my"):
        rows = db.execute(
            select(MyRepository.id, MyRepository.language).where(
                MyRepository.id.in_(grouped["my"])
            )
        ).all()
        for repo_id, language in rows:
            result[("my", repo_id)] = language or ""
    # 热榜仓库表没有 language 列（D1 侧同样如此），元数据留空即可。
    return result
    return result


def _parse_vector(raw: Any) -> list[float] | None:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(value, list) or not value:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def _build_item(row: dict[str, Any], language: str) -> dict[str, Any]:
    source = str(row["source"])
    repo_id = str(row["repo_id"])
    values = _parse_vector(row.get("vector"))
    return {
        "id": vector_id(source, repo_id),
        "values": values,
        "metadata": {
            "source": source,
            "repo_id": repo_id,
            "text_hash": str(row.get("text_hash") or ""),
            "model": str(row.get("model") or ""),
            "dim": int(row.get("dim") or 0),
            "language": language,
        },
    }


def _mark_state(
    db: Session,
    row: dict[str, Any],
    *,
    status: str,
    attempts: int,
    error: str | None = None,
    synced: bool = False,
) -> VectorIndexState:
    source, repo_id = str(row["source"]), str(row["repo_id"])
    state = db.get(VectorIndexState, (source, repo_id))
    if state is None:
        state = VectorIndexState(source=source, repo_id=repo_id, vector_id=vector_id(source, repo_id))
        db.add(state)
    state.vector_id = vector_id(source, repo_id)
    state.text_hash = str(row.get("text_hash") or "")
    state.model = str(row.get("model") or "")
    state.backend = str(row.get("backend") or "")
    state.dim = int(row.get("dim") or 0)
    state.status = status
    state.attempts = attempts
    state.last_error = (error or "")[:1000] or None
    state.checked_at = _utcnow()
    if synced:
        state.synced_at = _utcnow()
    return state


def _upsert_batch(
    items: list[dict[str, Any]],
    *,
    max_retries: int,
    base_ms: int,
) -> dict[str, Any]:
    if not items:
        return {"total": 0, "upserted": 0}
    payload = {"items": items}
    result = _with_retry(
        lambda: _edge_request("POST", "/api/internal/vectors/upsert", payload),
        max_retries,
        base_ms,
    )
    return result if isinstance(result, dict) else {"total": len(items), "upserted": len(items)}


def _delete_batch(ids: list[str], *, max_retries: int, base_ms: int) -> dict[str, Any]:
    if not ids:
        return {"total": 0, "deleted": 0}
    result = _with_retry(
        lambda: _edge_request("POST", "/api/internal/vectors/delete", {"ids": ids}),
        max_retries,
        base_ms,
    )
    return result if isinstance(result, dict) else {"total": len(ids), "deleted": len(ids)}


def create_run(mode: str = "incremental", scope: str = "all", run_id: str | None = None) -> str:
    """创建（或复用）一条运行记录，返回 runId。"""
    db = SessionLocal()
    try:
        rid = run_id or uuid4().hex
        if db.get(VectorIndexRun, rid) is None:
            db.add(VectorIndexRun(id=rid, mode=mode, scope=scope))
            db.commit()
        return rid
    finally:
        db.close()


def serialize_run(run: VectorIndexRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "mode": run.mode,
        "scope": run.scope,
        "status": run.status,
        "batchSize": run.batch_size,
        "maxRetries": run.max_retries,
        "total": run.total,
        "processed": run.processed,
        "upserted": run.upserted,
        "deleted": run.deleted,
        "skipped": run.skipped,
        "failed": run.failed,
        "dimSkipped": run.dim_skipped,
        "checked": run.checked,
        "missing": run.missing,
        "stale": run.stale,
        "repaired": run.repaired,
        "batches": run.batches,
        "error": run.error,
        "createdAt": run.created_at.isoformat() if run.created_at else None,
        "finishedAt": run.finished_at.isoformat() if run.finished_at else None,
    }


def sync_vectors(
    *,
    run_id: str | None = None,
    mode: str = "incremental",
    scope: str = "all",
    limit: int | None = None,
    batch_size: int | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """执行一次索引同步；返回结构化统计（不抛异常）。"""
    settings = get_settings()
    batch = _clamp_batch(batch_size, settings.VECTORIZE_SYNC_BATCH_SIZE)
    max_retries = max(0, int(settings.VECTORIZE_SYNC_MAX_RETRIES))
    base_ms = max(0, int(settings.VECTORIZE_SYNC_RETRY_BASE_MS))
    max_rows = max(1, int(limit if limit is not None else settings.VECTORIZE_SYNC_MAX_PER_RUN))
    rid = create_run("full" if mode == "full" else "incremental", scope, run_id)

    db = SessionLocal()
    try:
        run = db.get(VectorIndexRun, rid)
        assert run is not None
        run.status = "running"
        run.error = None
        db.commit()

        if not settings.VECTORIZE_SYNC_ENABLED:
            run.status = "disabled"
            run.error = "VECTORIZE_SYNC_ENABLED=false"
            run.finished_at = _utcnow()
            db.commit()
            return serialize_run(run)
        if not (settings.EDGE_BASE_URL or "").strip() or not (settings.INTERNAL_TOKEN or "").strip():
            run.status = "disabled"
            run.error = "EDGE_BASE_URL / INTERNAL_TOKEN 未配置"
            run.finished_at = _utcnow()
            db.commit()
            return serialize_run(run)
        if not _has_repo_vectors(db):
            run.status = "failed"
            run.error = "repo_vectors 表不存在（需先完成 M3-02 向量化管线）"
            run.finished_at = _utcnow()
            db.commit()
            return serialize_run(run)

        run.total = min(_count_local_vectors(db, scope), max_rows)
        run.batch_size = batch
        run.max_retries = max_retries
        db.commit()

        after_source = run.cursor_source or ""
        after_repo_id = run.cursor_repo_id or ""
        processed = 0
        while processed < max_rows:
            rows = _load_vector_rows(db, scope, after_source, after_repo_id, min(batch, max_rows - processed))
            if not rows:
                break
            keys = [(str(row["source"]), str(row["repo_id"])) for row in rows]
            states = _state_map(db, keys)
            languages = _language_map(db, keys)

            items: list[dict[str, Any]] = []
            skipped = 0
            dim_skipped = 0
            for row in rows:
                key = (str(row["source"]), str(row["repo_id"]))
                state = states.get(key)
                values = _parse_vector(row.get("vector"))
                dim = int(row.get("dim") or 0)
                if values is None or (dim and len(values) != dim):
                    dim_skipped += 1
                    _mark_state(db, row, status="failed", attempts=(state.attempts if state else 0), error="向量为空或维度不一致")
                    continue
                if settings.VECTORIZE_INDEX_DIM and dim and dim != settings.VECTORIZE_INDEX_DIM:
                    dim_skipped += 1
                    _mark_state(
                        db,
                        row,
                        status="failed",
                        attempts=(state.attempts if state else 0),
                        error=f"维度 {dim} 与索引维度 {settings.VECTORIZE_INDEX_DIM} 不一致",
                    )
                    continue
                unchanged = (
                    state is not None
                    and state.status == "synced"
                    and state.text_hash == str(row.get("text_hash") or "")
                    and state.model == str(row.get("model") or "")
                    and state.backend == str(row.get("backend") or "")
                    and state.dim == dim
                )
                if mode != "full" and unchanged:
                    skipped += 1
                    continue
                items.append(_build_item(row, languages.get(key, "")))

            batch_error: str | None = None
            if items:
                try:
                    _upsert_batch(items, max_retries=max_retries, base_ms=base_ms)
                except EdgeRequestError as exc:
                    batch_error = str(exc)
                    run.failed += len(items)
                    for row in rows:
                        key = (str(row["source"]), str(row["repo_id"]))
                        if any(item["id"] == vector_id(*key) for item in items):
                            state = states.get(key)
                            _mark_state(
                                db,
                                row,
                                status="failed",
                                attempts=(state.attempts if state else 0) + 1,
                                error=batch_error,
                            )
                else:
                    run.upserted += len(items)
                    for row in rows:
                        key = (str(row["source"]), str(row["repo_id"]))
                        if any(item["id"] == vector_id(*key) for item in items):
                            state = states.get(key)
                            _mark_state(
                                db,
                                row,
                                status="synced",
                                attempts=(state.attempts if state else 0) + 1,
                                synced=True,
                            )

            run.skipped += skipped
            run.dim_skipped += dim_skipped
            run.processed += len(rows)
            run.batches += 1
            processed += len(rows)
            last = rows[-1]
            after_source, after_repo_id = str(last["source"]), str(last["repo_id"])
            run.cursor_source, run.cursor_repo_id = after_source, after_repo_id
            db.commit()

            if progress:
                progress(
                    {
                        "processed": run.processed,
                        "total": run.total,
                        "upserted": run.upserted,
                        "skipped": run.skipped,
                        "failed": run.failed,
                        "dimSkipped": run.dim_skipped,
                    }
                )

        run.status = "completed"
        if run.failed:
            run.error = f"{run.failed} 条向量批次失败，下次增量运行将自动重试"
        run.finished_at = _utcnow()
        db.commit()
        return serialize_run(run)
    except Exception as exc:  # noqa: BLE001 - 任务降级返回结构化错误
        logger.exception("Vectorize 索引同步失败")
        run = db.get(VectorIndexRun, rid)
        if run is not None:
            run.status = "failed"
            run.error = str(exc)[:1000]
            run.finished_at = _utcnow()
            db.commit()
            return serialize_run(run)
        return {"id": rid, "status": "failed", "error": str(exc)[:1000]}
    finally:
        db.close()


def _iter_local_ids(db: Session, scope: str, batch: int = MAX_CHECK_BATCH) -> Iterable[list[dict[str, Any]]]:
    after_source, after_repo_id = "", ""
    while True:
        rows = _load_vector_rows(db, scope, after_source, after_repo_id, batch)
        if not rows:
            return
        yield rows
        last = rows[-1]
        after_source, after_repo_id = str(last["source"]), str(last["repo_id"])


def reconcile_vectors(
    *,
    scope: str = "all",
    repair: bool = False,
    limit: int | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """对账：校验本地向量是否存在于索引，报告缺失 / 过期 / 维度问题，可选修复。"""
    settings = get_settings()
    max_retries = max(0, int(settings.VECTORIZE_SYNC_MAX_RETRIES))
    base_ms = max(0, int(settings.VECTORIZE_SYNC_RETRY_BASE_MS))
    max_rows = max(1, int(limit if limit is not None else settings.VECTORIZE_SYNC_MAX_PER_RUN))
    rid = create_run("reconcile", scope, run_id)
    db = SessionLocal()
    try:
        run = db.get(VectorIndexRun, rid)
        assert run is not None
        run.status = "running"
        db.commit()

        if not settings.VECTORIZE_SYNC_ENABLED:
            run.status = "disabled"
            run.error = "VECTORIZE_SYNC_ENABLED=false"
            run.finished_at = _utcnow()
            db.commit()
            return serialize_run(run)
        if not (settings.EDGE_BASE_URL or "").strip() or not (settings.INTERNAL_TOKEN or "").strip():
            run.status = "disabled"
            run.error = "EDGE_BASE_URL / INTERNAL_TOKEN 未配置"
            run.finished_at = _utcnow()
            db.commit()
            return serialize_run(run)
        if not _has_repo_vectors(db):
            run.status = "failed"
            run.error = "repo_vectors 表不存在（需先完成 M3-02 向量化管线）"
            run.finished_at = _utcnow()
            db.commit()
            return serialize_run(run)

        stats = _with_retry(
            lambda: _edge_request("GET", "/api/internal/vectors/stats"),
            max_retries,
            base_ms,
        )
        dimensions = int(stats.get("dimensions") or 0) if isinstance(stats, dict) else 0
        if settings.VECTORIZE_INDEX_DIM and dimensions and dimensions != settings.VECTORIZE_INDEX_DIM:
            run.status = "failed"
            run.error = f"索引维度 {dimensions} 与配置 VECTORIZE_INDEX_DIM={settings.VECTORIZE_INDEX_DIM} 不一致"
            run.finished_at = _utcnow()
            db.commit()
            return serialize_run(run)

        run.total = min(_count_local_vectors(db, scope), max_rows)
        db.commit()

        checked = 0
        missing: list[dict[str, Any]] = []
        stale: list[dict[str, Any]] = []
        for rows in _iter_local_ids(db, scope):
            if checked >= max_rows:
                break
            rows = rows[: max_rows - checked]
            keys = [(str(row["source"]), str(row["repo_id"])) for row in rows]
            states = _state_map(db, keys)
            ids = [vector_id(*key) for key in keys]
            result = _with_retry(
                lambda: _edge_request("POST", "/api/internal/vectors/check", {"ids": ids}),
                max_retries,
                base_ms,
            )
            found = set(result.get("found") or []) if isinstance(result, dict) else set()
            for row, key, vid in zip(rows, keys, ids):
                state = states.get(key)
                if state is not None:
                    state.checked_at = _utcnow()
                if vid not in found:
                    missing.append(row)
                elif state is None or (
                    state.text_hash != str(row.get("text_hash") or "")
                    or state.model != str(row.get("model") or "")
                    or state.backend != str(row.get("backend") or "")
                    or state.dim != int(row.get("dim") or 0)
                ):
                    stale.append(row)
            checked += len(rows)

        run.checked = checked
        run.processed = checked
        run.missing = len(missing)
        run.stale = len(stale)
        db.commit()

        if repair and (missing or stale):
            to_repair: dict[tuple[str, str], dict[str, Any]] = {}
            for row in [*missing, *stale]:
                to_repair[(str(row["source"]), str(row["repo_id"]))] = row
            languages = _language_map(db, to_repair.keys())
            repair_rows = list(to_repair.values())
            for start in range(0, len(repair_rows), _clamp_batch(None, settings.VECTORIZE_SYNC_BATCH_SIZE)):
                chunk = repair_rows[start : start + _clamp_batch(None, settings.VECTORIZE_SYNC_BATCH_SIZE)]
                items = [_build_item(row, languages.get((str(row["source"]), str(row["repo_id"])), "")) for row in chunk]
                try:
                    _upsert_batch(items, max_retries=max_retries, base_ms=base_ms)
                except EdgeRequestError as exc:
                    run.failed += len(items)
                    run.error = str(exc)[:1000]
                    for row in chunk:
                        _mark_state(db, row, status="failed", attempts=1, error=str(exc))
                    continue
                run.repaired += len(items)
                for row in chunk:
                    _mark_state(db, row, status="synced", attempts=1, synced=True)
            db.commit()

        if settings.VECTORIZE_SYNC_DELETE_ORPHANS:
            local_keys: set[tuple[str, str]] = set()
            for rows in _iter_local_ids(db, scope):
                local_keys.update((str(row["source"]), str(row["repo_id"])) for row in rows)
            orphans = db.scalars(select(VectorIndexState)).all()
            orphan_rows = [
                state
                for state in orphans
                if (state.source, state.repo_id) not in local_keys
                and (scope == "all" or state.source == scope)
            ][: max(0, int(settings.VECTORIZE_SYNC_MAX_ORPHANS))]
            if orphan_rows:
                ids = [state.vector_id for state in orphan_rows]
                try:
                    _delete_batch(ids, max_retries=max_retries, base_ms=base_ms)
                except EdgeRequestError as exc:
                    run.error = str(exc)[:1000]
                else:
                    for state in orphan_rows:
                        db.delete(state)
                    run.deleted += len(orphan_rows)
                    db.commit()

        run.status = "completed"
        run.finished_at = _utcnow()
        db.commit()
        return serialize_run(run)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Vectorize 索引对账失败")
        run = db.get(VectorIndexRun, rid)
        if run is not None:
            run.status = "failed"
            run.error = str(exc)[:1000]
            run.finished_at = _utcnow()
            db.commit()
            return serialize_run(run)
        return {"id": rid, "status": "failed", "error": str(exc)[:1000]}
    finally:
        db.close()


def index_status() -> dict[str, Any]:
    """本地向量数 / 状态分布 / 最近运行，供状态接口使用。"""
    db = SessionLocal()
    try:
        vectors = _count_local_vectors(db, "all")
        by_status = {"synced": 0, "failed": 0, "pending": 0}
        for status, count in db.execute(
            select(VectorIndexState.status, func.count()).group_by(VectorIndexState.status)
        ).all():
            by_status[str(status)] = int(count)
        runs = db.scalars(select(VectorIndexRun).order_by(VectorIndexRun.created_at.desc()).limit(5)).all()
        last = runs[0] if runs else None
        return {
            "enabled": bool(get_settings().VECTORIZE_SYNC_ENABLED),
            "edgeConfigured": bool((get_settings().EDGE_BASE_URL or "").strip() and (get_settings().INTERNAL_TOKEN or "").strip()),
            "indexName": get_settings().VECTORIZE_INDEX_NAME,
            "indexDim": get_settings().VECTORIZE_INDEX_DIM,
            "repoVectors": vectors,
            "states": by_status,
            "lastRun": serialize_run(last) if last else None,
            "runs": [serialize_run(run) for run in runs],
        }
    finally:
        db.close()


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        runs = db.scalars(
            select(VectorIndexRun).order_by(VectorIndexRun.created_at.desc()).limit(max(1, min(limit, 100)))
        ).all()
        return [serialize_run(run) for run in runs]
    finally:
        db.close()


def get_run(run_id: str) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        run = db.get(VectorIndexRun, run_id)
        return serialize_run(run) if run else None
    finally:
        db.close()
