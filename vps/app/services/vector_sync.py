"""Vectorize 索引同步：批量 upsert / 失败重试 / 对账。

数据流：本地 `repo_vectors`（M3-02 向量化管线）→ edge 内部接口 → Cloudflare Vectorize。
VPS 不持有 Cloudflare 账号凭据，所有索引操作都经 edge Worker 的 Vectorize 绑定完成。

设计要点：

- **稳定 ID**：`v1_ + sha256("{source}:{repo_id}")[:32]`，规避 Vectorize ID 长度限制；
- **增量**：以 `text_hash` 为版本，只推送新增 / 变更 / 上次失败的向量；
- **批量**：keyset 分页读取，单批大小可配（默认 100，上限 1000）；
- **重试**：网络错误 / 429 / 5xx 指数退避，单批最终失败只标记该批，不拖垮整个运行；
- **对账**：`getByIds` 比对缺失 / 过期向量并修复，可选清理本地已不存在的孤儿向量；
- **可观测**：`vector_sync_state` 记录每条向量的状态，`vector_sync_runs` 记录每次运行统计。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional
from uuid import uuid4

import httpx
from sqlalchemy import bindparam, func, inspect, select, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.models import VectorSyncRun, VectorSyncState

logger = logging.getLogger(__name__)

SOURCES: tuple[str, ...] = ("my", "trending")
SCOPES: tuple[str, ...] = ("my", "trending", "all")
KINDS: tuple[str, ...] = ("sync", "reconcile")
MAX_BATCH_SIZE = 1000
MAX_CHECK_BATCH = 100
VECTOR_ID_PREFIX = "v1_"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
ProgressCallback = Callable[[dict[str, Any]], None]


class VectorIndexError(RuntimeError):
    """Vectorize 同步错误基类。"""


class VectorIndexDisabled(VectorIndexError):
    """同步未启用或 edge 地址 / 令牌未配置。"""


class VectorIndexSourceMissing(VectorIndexError):
    """本地 `repo_vectors` 表不存在（M3-02 尚未落地）。"""


class VectorIndexUnsupported(VectorIndexError):
    """edge / Vectorize 不支持当前操作（如 list）。"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_scope(scope: str) -> str:
    value = (scope or "all").strip().lower()
    if value not in SCOPES:
        raise VectorIndexError(f"非法 scope：{scope}（可选 my / trending / all）")
    return value


def normalize_kind(kind: str) -> str:
    value = (kind or "sync").strip().lower()
    if value not in KINDS:
        raise VectorIndexError(f"非法 kind：{kind}（可选 sync / reconcile）")
    return value


def sources_for(scope: str) -> list[str]:
    normalized = normalize_scope(scope)
    return list(SOURCES) if normalized == "all" else [normalized]


def vector_id_for(source: str, repo_id: str) -> str:
    """稳定向量 ID：固定 35 字符，满足 Vectorize 对 ID 长度的限制。"""
    digest = hashlib.sha256(f"{source}:{repo_id}".encode("utf-8")).hexdigest()
    return f"{VECTOR_ID_PREFIX}{digest[:32]}"


@dataclass(frozen=True)
class LocalVector:
    """从 `repo_vectors` 读取的一条待同步向量。"""

    source: str
    repo_id: str
    model: str
    backend: str
    dim: int
    text_hash: str
    vector: list[float]

    @property
    def vector_id(self) -> str:
        return vector_id_for(self.source, self.repo_id)

    def metadata(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "repo_id": self.repo_id,
            "text_hash": self.text_hash,
            "model": self.model,
            "dim": self.dim,
        }


# --------------------------------------------------------------------------- edge 客户端


class EdgeVectorClient:
    """edge 内部 Vectorize 接口客户端（同步 httpx，带指数退避重试）。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_base_ms: int = 500,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.timeout = max(1.0, float(timeout))
        self.max_retries = max(0, int(max_retries))
        self.retry_base_ms = max(0, int(retry_base_ms))
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Optional[Settings] = None) -> "EdgeVectorClient":
        cfg = settings or get_settings()
        base_url = (cfg.EDGE_BASE_URL or "").strip()
        token = (cfg.INTERNAL_TOKEN or "").strip()
        if not base_url or not token:
            raise VectorIndexDisabled("EDGE_BASE_URL 与 INTERNAL_TOKEN 未配置，无法同步 Vectorize")
        return cls(
            base_url,
            token,
            timeout=cfg.VECTORIZE_SYNC_TIMEOUT_SECONDS,
            max_retries=cfg.VECTORIZE_SYNC_MAX_RETRIES,
            retry_base_ms=cfg.VECTORIZE_SYNC_RETRY_BASE_MS,
        )

    # ------------------------------------------------------------------ HTTP

    def _delay(self, attempt: int, retry_after: str | None = None) -> float:
        delay = (self.retry_base_ms / 1000.0) * (2**attempt)
        if retry_after:
            try:
                delay = max(delay, min(30.0, float(retry_after)))
            except (TypeError, ValueError):
                pass
        return min(30.0, delay)

    def _request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        *,
        params: dict[str, Any] | None = None,
        allow_unsupported: bool = False,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"X-Internal-Token": self.token}
        last_error = "未知错误"

        for attempt in range(self.max_retries + 1):
            retry_after: str | None = None
            try:
                with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                    response = client.request(
                        method, url, json=payload, params=params, headers=headers
                    )
            except httpx.HTTPError as exc:
                last_error = f"网络错误：{exc}"
            else:
                if allow_unsupported and response.status_code in (404, 501):
                    raise VectorIndexUnsupported(
                        f"edge 接口不支持该操作：HTTP {response.status_code}"
                    )
                if response.status_code in RETRYABLE_STATUS:
                    retry_after = response.headers.get("Retry-After")
                    last_error = f"HTTP {response.status_code}"
                elif response.status_code >= 400:
                    detail = (response.text or "")[:300]
                    raise VectorIndexError(
                        f"edge 接口返回 HTTP {response.status_code}：{detail}"
                    )
                else:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise VectorIndexError("edge 接口返回非 JSON 响应") from exc

            if attempt >= self.max_retries:
                break
            delay = self._delay(attempt, retry_after)
            if delay > 0:
                time.sleep(delay)

        raise VectorIndexError(
            f"edge 请求失败（已重试 {self.max_retries} 次）：{last_error}"
        )

    # ------------------------------------------------------------------ API

    def upsert(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("POST", "/api/internal/vectors/upsert", {"vectors": items})

    def check(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        data = self._request("POST", "/api/internal/vectors/check", {"ids": ids})
        result: dict[str, dict[str, Any]] = {}
        for item in data.get("vectors") or []:
            vector_id = str(item.get("id") or "")
            if vector_id:
                metadata = item.get("metadata")
                result[vector_id] = metadata if isinstance(metadata, dict) else {}
        return result

    def delete(self, ids: list[str]) -> dict[str, Any]:
        return self._request("POST", "/api/internal/vectors/delete", {"ids": ids})

    def stats(self) -> dict[str, Any]:
        return self._request("GET", "/api/internal/vectors/stats")

    def list_ids(self, *, count: int = 1000, max_pages: int = 100) -> list[str]:
        """分页列出索引中的全部 id（孤儿对账用；edge 不支持时抛 Unsupported）。"""
        ids: list[str] = []
        cursor: str | None = None
        for _ in range(max(1, max_pages)):
            params: dict[str, Any] = {"count": count}
            if cursor:
                params["cursor"] = cursor
            data = self._request(
                "GET", "/api/internal/vectors/list", params=params, allow_unsupported=True
            )
            vectors = data.get("vectors") or []
            ids.extend(str(item.get("id")) for item in vectors if item.get("id"))
            cursor = data.get("cursor")
            if not cursor or not vectors:
                break
        return ids


# --------------------------------------------------------------------------- 本地数据


def _has_repo_vectors(db: Session) -> bool:
    try:
        return bool(inspect(db.get_bind()).has_table("repo_vectors"))
    except Exception:  # noqa: BLE001 - 连接异常按不可用处理
        return False


def count_local_vectors(db: Session, scope: str) -> int:
    if not _has_repo_vectors(db):
        return 0
    sources = sources_for(scope)
    stmt = text("SELECT COUNT(*) FROM repo_vectors WHERE source IN :sources").bindparams(
        bindparam("sources", expanding=True)
    )
    return int(db.execute(stmt, {"sources": sources}).scalar() or 0)


def _count_candidates(db: Session, scope: str, *, only_changed: bool) -> int:
    sources = sources_for(scope)
    clause = ""
    if only_changed:
        clause = (
            " AND (s.text_hash IS NULL OR s.text_hash <> r.text_hash OR s.status = 'failed')"
        )
    stmt = text(
        "SELECT COUNT(*) FROM repo_vectors r "
        "LEFT JOIN vector_sync_state s ON s.source = r.source AND s.repo_id = r.repo_id "
        "WHERE r.source IN :sources" + clause
    ).bindparams(bindparam("sources", expanding=True))
    return int(db.execute(stmt, {"sources": sources}).scalar() or 0)


def _parse_vector(raw: Any) -> list[float]:
    if isinstance(raw, (list, tuple)):
        return [float(value) for value in raw]
    try:
        parsed = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [float(value) for value in parsed]


def load_local_batch(
    db: Session,
    scope: str,
    *,
    after: tuple[str, str] | None = None,
    limit: int = 100,
    only_changed: bool = True,
) -> list[LocalVector]:
    """按 `(source, repo_id)` keyset 分页读取本地向量。"""
    sources = sources_for(scope)
    clause = ""
    params: dict[str, Any] = {"sources": sources, "limit": max(1, int(limit))}
    if only_changed:
        clause = (
            " AND (s.text_hash IS NULL OR s.text_hash <> r.text_hash OR s.status = 'failed')"
        )
    if after:
        clause += (
            " AND (r.source > :after_source OR (r.source = :after_source AND r.repo_id > :after_repo))"
        )
        params["after_source"], params["after_repo"] = after
    stmt = text(
        "SELECT r.source, r.repo_id, r.model, r.backend, r.dim, r.text_hash, r.vector "
        "FROM repo_vectors r "
        "LEFT JOIN vector_sync_state s ON s.source = r.source AND s.repo_id = r.repo_id "
        "WHERE r.source IN :sources" + clause + " ORDER BY r.source, r.repo_id LIMIT :limit"
    ).bindparams(bindparam("sources", expanding=True))
    rows = db.execute(stmt, params).all()
    result: list[LocalVector] = []
    for row in rows:
        vector = _parse_vector(row.vector)
        if not vector:
            logger.warning("跳过空向量：source=%s repo=%s", row.source, row.repo_id)
            continue
        result.append(
            LocalVector(
                source=str(row.source),
                repo_id=str(row.repo_id),
                model=str(row.model or ""),
                backend=str(row.backend or ""),
                dim=int(row.dim or len(vector)),
                text_hash=str(row.text_hash or ""),
                vector=vector,
            )
        )
    return result


def load_local_ids(db: Session, scope: str) -> set[str]:
    sources = sources_for(scope)
    stmt = text("SELECT source, repo_id FROM repo_vectors WHERE source IN :sources").bindparams(
        bindparam("sources", expanding=True)
    )
    rows = db.execute(stmt, {"sources": sources}).all()
    return {vector_id_for(str(row.source), str(row.repo_id)) for row in rows}


# --------------------------------------------------------------------------- 运行记录


def create_run(
    db: Session,
    *,
    kind: str,
    scope: str,
    batch_size: int,
    max_retries: int,
    force: bool,
    limit: int,
    total: int,
) -> VectorSyncRun:
    run = VectorSyncRun(
        id=uuid4().hex,
        kind=kind,
        scope=scope,
        status="running",
        batch_size=batch_size,
        max_retries=max_retries,
        force=bool(force),
        limit=limit,
        total=total,
    )
    db.add(run)
    db.commit()
    return run


def run_to_dict(run: VectorSyncRun) -> dict[str, Any]:
    return {
        "runId": run.id,
        "kind": run.kind,
        "scope": run.scope,
        "status": run.status,
        "batchSize": run.batch_size,
        "maxRetries": run.max_retries,
        "force": bool(run.force),
        "limit": run.limit,
        "total": run.total,
        "processed": run.processed,
        "synced": run.synced,
        "skipped": run.skipped,
        "failed": run.failed,
        "deleted": run.deleted,
        "checked": run.checked,
        "missing": run.missing,
        "repaired": run.repaired,
        "orphanScan": run.orphan_scan,
        "cursorSource": run.cursor_source,
        "cursorRepoId": run.cursor_repo_id,
        "error": run.error,
        "createdAt": run.created_at,
        "updatedAt": run.updated_at,
        "finishedAt": run.finished_at,
    }


def list_runs(db: Session, limit: int = 20) -> list[VectorSyncRun]:
    return list(
        db.execute(
            select(VectorSyncRun)
            .order_by(VectorSyncRun.created_at.desc())
            .limit(max(1, min(100, int(limit))))
        )
        .scalars()
        .all()
    )


def get_run(db: Session, run_id: str) -> VectorSyncRun:
    run = db.get(VectorSyncRun, run_id)
    if run is None:
        raise VectorIndexError(f"同步运行不存在：{run_id}")
    return run


def get_status(db: Session) -> dict[str, Any]:
    """本地向量覆盖率与同步状态分布（不访问 edge，保证状态接口稳定）。"""
    settings = get_settings()
    local_total = count_local_vectors(db, "all")
    states = {
        str(status): int(count)
        for status, count in db.execute(
            select(VectorSyncState.status, func.count()).group_by(VectorSyncState.status)
        ).all()
    }
    known = sum(states.values())
    return {
        "enabled": bool(settings.VECTORIZE_SYNC_ENABLED),
        "configured": bool((settings.EDGE_BASE_URL or "").strip() and (settings.INTERNAL_TOKEN or "").strip()),
        "indexName": settings.VECTORIZE_INDEX_NAME,
        "dim": settings.VECTORIZE_INDEX_DIM,
        "localVectors": local_total,
        "states": states,
        "pending": max(0, local_total - known),
        "lastRuns": [run_to_dict(run) for run in list_runs(db, limit=5)],
    }


# --------------------------------------------------------------------------- 同步核心


def _notify(progress: Optional[ProgressCallback], run: VectorSyncRun) -> None:
    if progress is None:
        return
    percent = round((run.processed / run.total) * 100, 1) if run.total else 100.0
    progress(
        {
            "runId": run.id,
            "kind": run.kind,
            "scope": run.scope,
            "status": run.status,
            "total": run.total,
            "processed": run.processed,
            "percent": percent,
            "synced": run.synced,
            "skipped": run.skipped,
            "failed": run.failed,
            "deleted": run.deleted,
        }
    )


def _state_for(db: Session, row: LocalVector) -> VectorSyncState:
    state = db.get(VectorSyncState, (row.source, row.repo_id))
    if state is None:
        state = VectorSyncState(
            source=row.source,
            repo_id=row.repo_id,
            vector_id=row.vector_id,
            text_hash=row.text_hash,
            model=row.model,
            backend=row.backend,
            dim=row.dim,
            status="pending",
        )
        db.add(state)
    return state


def _mark_synced(db: Session, row: LocalVector) -> None:
    state = _state_for(db, row)
    state.vector_id = row.vector_id
    state.text_hash = row.text_hash
    state.model = row.model
    state.backend = row.backend
    state.dim = row.dim
    state.status = "synced"
    state.attempts = (state.attempts or 0) + 1
    state.last_error = None
    state.synced_at = _utcnow()
    state.checked_at = state.synced_at


def _mark_failed(db: Session, row: LocalVector, error: str) -> None:
    state = _state_for(db, row)
    state.vector_id = row.vector_id
    state.text_hash = row.text_hash
    state.model = row.model
    state.backend = row.backend
    state.dim = row.dim
    state.status = "failed"
    state.attempts = (state.attempts or 0) + 1
    state.last_error = (error or "")[:500]
    state.checked_at = _utcnow()


def _mark_dim_mismatch(db: Session, row: LocalVector, expected: int) -> None:
    state = _state_for(db, row)
    state.vector_id = row.vector_id
    state.text_hash = row.text_hash
    state.model = row.model
    state.backend = row.backend
    state.dim = row.dim
    state.status = "dim_mismatch"
    state.last_error = f"向量维度 {row.dim} 与索引维度 {expected} 不一致"
    state.checked_at = _utcnow()


def _sync_batch(
    db: Session,
    run: VectorSyncRun,
    rows: Iterable[LocalVector],
    client: EdgeVectorClient,
    settings: Settings,
) -> None:
    """上传一批向量；维度不一致的跳过，失败只标记该批。"""
    items: list[dict[str, Any]] = []
    valid: list[LocalVector] = []
    expected_dim = int(settings.VECTORIZE_INDEX_DIM or 0)

    for row in rows:
        if expected_dim and row.dim != expected_dim:
            run.skipped += 1
            _mark_dim_mismatch(db, row, expected_dim)
            continue
        items.append({"id": row.vector_id, "values": row.vector, "metadata": row.metadata()})
        valid.append(row)

    if not items:
        return

    try:
        client.upsert(items)
    except Exception as exc:  # noqa: BLE001 - 单批失败不拖垮整个运行
        message = str(exc)[:500]
        logger.warning("Vectorize upsert 失败（%d 条）：%s", len(items), message)
        run.failed += len(valid)
        run.error = message
        for row in valid:
            _mark_failed(db, row, message)
        return

    run.synced += len(valid)
    for row in valid:
        _mark_synced(db, row)


def _reconcile_rows(
    db: Session,
    run: VectorSyncRun,
    rows: list[LocalVector],
    client: EdgeVectorClient,
    settings: Settings,
) -> None:
    """对账：逐批 getByIds，仅修复缺失 / 过期向量。"""
    for start in range(0, len(rows), MAX_CHECK_BATCH):
        chunk = rows[start : start + MAX_CHECK_BATCH]
        try:
            remote = client.check([row.vector_id for row in chunk])
        except Exception as exc:  # noqa: BLE001
            message = str(exc)[:500]
            logger.warning("Vectorize 对账失败（%d 条）：%s", len(chunk), message)
            run.failed += len(chunk)
            run.error = message
            for row in chunk:
                _mark_failed(db, row, message)
            continue

        run.checked += len(chunk)
        repair: list[LocalVector] = []
        for row in chunk:
            metadata = remote.get(row.vector_id)
            if metadata is None:
                run.missing += 1
                repair.append(row)
            elif str(metadata.get("text_hash") or "") != row.text_hash:
                run.repaired += 1
                repair.append(row)
            else:
                run.skipped += 1
        if repair:
            _sync_batch(db, run, repair, client, settings)


def _scan_orphans(
    db: Session,
    run: VectorSyncRun,
    client: EdgeVectorClient,
    settings: Settings,
) -> None:
    """可选：删除本地已不存在、但仍留在索引中的向量（默认关闭）。"""
    if not settings.VECTORIZE_SYNC_DELETE_ORPHANS:
        run.orphan_scan = "disabled"
        return
    if run.total < count_local_vectors(db, run.scope):
        run.orphan_scan = "limited"
        return

    local_ids = load_local_ids(db, run.scope)
    try:
        remote_ids = client.list_ids()
    except VectorIndexUnsupported:
        run.orphan_scan = "unsupported"
        return
    except Exception as exc:  # noqa: BLE001
        run.orphan_scan = "failed"
        run.error = str(exc)[:500]
        return

    orphan_ids = [
        vector_id
        for vector_id in remote_ids
        if vector_id.startswith(VECTOR_ID_PREFIX) and vector_id not in local_ids
    ]
    limit = max(0, int(settings.VECTORIZE_SYNC_MAX_ORPHANS or 0))
    truncated = len(orphan_ids) > limit
    orphan_ids = orphan_ids[:limit]

    for start in range(0, len(orphan_ids), MAX_BATCH_SIZE):
        chunk = orphan_ids[start : start + MAX_BATCH_SIZE]
        try:
            client.delete(chunk)
        except Exception as exc:  # noqa: BLE001
            run.failed += len(chunk)
            run.error = str(exc)[:500]
            run.orphan_scan = "failed"
            return
        run.deleted += len(chunk)
    run.orphan_scan = "truncated" if truncated else "done"


def sync_vector_index(
    *,
    kind: str = "sync",
    scope: str = "all",
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
    force: bool = False,
    client: Optional[EdgeVectorClient] = None,
    progress: Optional[ProgressCallback] = None,
    db: Optional[Session] = None,
) -> dict[str, Any]:
    """执行一次 Vectorize 索引同步（sync / reconcile），返回运行统计。"""
    settings = get_settings()
    if not settings.VECTORIZE_SYNC_ENABLED:
        raise VectorIndexDisabled("VECTORIZE_SYNC_ENABLED=false，索引同步已关闭")

    normalized_kind = normalize_kind(kind)
    normalized_scope = normalize_scope(scope)
    effective_batch = max(
        1, min(MAX_BATCH_SIZE, int(batch_size or settings.VECTORIZE_SYNC_BATCH_SIZE))
    )
    effective_limit = max(1, int(limit or settings.VECTORIZE_SYNC_MAX_PER_RUN))
    if client is None:
        client = EdgeVectorClient.from_settings(settings)

    owns_db = db is None
    session = db or SessionLocal()
    try:
        if not _has_repo_vectors(session):
            raise VectorIndexSourceMissing(
                "本地 repo_vectors 表不存在；请先完成 M3-02 向量化管线并生成向量"
            )

        only_changed = normalized_kind == "sync" and not force
        total = _count_candidates(session, normalized_scope, only_changed=only_changed)
        if total > effective_limit:
            total = effective_limit
        run = create_run(
            session,
            kind=normalized_kind,
            scope=normalized_scope,
            batch_size=effective_batch,
            max_retries=int(settings.VECTORIZE_SYNC_MAX_RETRIES),
            force=force,
            limit=effective_limit,
            total=total,
        )
        _notify(progress, run)

        after: tuple[str, str] | None = None
        while run.processed < run.total:
            take = min(effective_batch, run.total - run.processed)
            rows = load_local_batch(
                session,
                normalized_scope,
                after=after,
                limit=take,
                only_changed=only_changed,
            )
            if not rows:
                break
            run.cursor_source = rows[-1].source
            run.cursor_repo_id = rows[-1].repo_id
            if normalized_kind == "reconcile":
                _reconcile_rows(session, run, rows, client, settings)
            else:
                _sync_batch(session, run, rows, client, settings)
            run.processed += len(rows)
            session.commit()
            _notify(progress, run)
            after = (rows[-1].source, rows[-1].repo_id)

        if normalized_kind == "reconcile":
            _scan_orphans(session, run, client, settings)

        if run.processed < run.total:
            run.total = run.processed
        if run.failed == 0:
            run.status = "completed"
        elif run.synced or run.checked or run.deleted:
            run.status = "partial"
        else:
            run.status = "failed"
        run.finished_at = _utcnow()
        session.commit()
        _notify(progress, run)

        logger.info(
            "Vectorize 同步完成: run=%s kind=%s scope=%s total=%d synced=%d skipped=%d failed=%d deleted=%d",
            run.id,
            run.kind,
            run.scope,
            run.total,
            run.synced,
            run.skipped,
            run.failed,
            run.deleted,
        )
        result = run_to_dict(run)
        result["indexName"] = settings.VECTORIZE_INDEX_NAME
        result["dim"] = settings.VECTORIZE_INDEX_DIM
        return result
    except Exception as exc:
        session.rollback()
        raise exc
    finally:
        if owns_db:
            session.close()
