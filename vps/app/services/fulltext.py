"""README 全文镜像与 FTS5 检索（M6-01，本地镜像先行）。

职责：

- 维护 `repo_readmes`（清洗后的 README 全文，`source + repo_id` 联合主键）；
- 维护 SQLite FTS5 虚表 `repo_readme_fts`，由触发器随镜像表增删改自动同步；
- 提供 bm25 排序、命中片段、scope 过滤的全文检索；
- 提供索引状态 / 全量重建 / README 补索引任务。

设计约束：

- 只依赖 SQLite 内置 FTS5，不引入外部检索服务；非 SQLite 环境自动降级为 LIKE；
- trigram 分词对中英文子串检索友好，但要求查询词 ≥3 字符；1~2 字符短词回退 LIKE；
- 任何外部抓取失败都返回结构化统计，不抛出异常，保证 Celery 任务可重试。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import func, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MyRepository, RepoReadme, TrendingRepository
from app.services.readme import clean_readme

logger = logging.getLogger(__name__)

SOURCES: tuple[str, ...] = ("my", "trending")
SCOPES: tuple[str, ...] = ("my", "trending", "all")

_TERM_SPLIT_RE = re.compile(r"[\s,，。；;：:!?！？、()（）\[\]【】{}<>\"“”‘’]+")
_LIKE_ESCAPE_RE = re.compile(r"([\\%_])")


class FulltextError(RuntimeError):
    """全文检索参数 / 状态错误。"""


class FulltextDisabled(FulltextError):
    """全文检索未启用。"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite"


def ensure_fts_schema(engine: Engine) -> bool:
    """幂等创建 FTS5 虚表与同步触发器；非 SQLite 返回 False。"""
    if not _is_sqlite(engine):
        return False

    create_sql = (
        "CREATE VIRTUAL TABLE IF NOT EXISTS repo_readme_fts USING fts5("
        "source UNINDEXED, repo_id UNINDEXED, content, tokenize='trigram')"
    )
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(create_sql)
    except Exception:  # noqa: BLE001 - 旧版 SQLite 无 trigram 时退回 unicode61
        logger.warning("FTS5 trigram 不可用，回退 unicode61", exc_info=True)
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS repo_readme_fts USING fts5("
                    "source UNINDEXED, repo_id UNINDEXED, content, tokenize='unicode61')"
                )
        except Exception:  # noqa: BLE001 - 未编译 FTS5 时降级为 LIKE 检索
            logger.warning("SQLite 未启用 FTS5，全文检索将回退 LIKE", exc_info=True)
            return False

    triggers = (
        """
        CREATE TRIGGER IF NOT EXISTS repo_readmes_ai AFTER INSERT ON repo_readmes BEGIN
          INSERT INTO repo_readme_fts(source, repo_id, content)
          VALUES (new.source, new.repo_id, new.content);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS repo_readmes_au AFTER UPDATE ON repo_readmes BEGIN
          DELETE FROM repo_readme_fts
          WHERE source = old.source AND repo_id = old.repo_id;
          INSERT INTO repo_readme_fts(source, repo_id, content)
          VALUES (new.source, new.repo_id, new.content);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS repo_readmes_ad AFTER DELETE ON repo_readmes BEGIN
          DELETE FROM repo_readme_fts
          WHERE source = old.source AND repo_id = old.repo_id;
        END
        """,
    )
    try:
        with engine.begin() as conn:
            for trigger in triggers:
                conn.exec_driver_sql(trigger)
    except Exception:  # noqa: BLE001 - 触发器失败时降级为 LIKE，保证应用可启动
        logger.warning("FTS 同步触发器创建失败，全文检索将回退 LIKE", exc_info=True)
        return False
    return True


def normalize_scope(scope: str) -> str:
    value = (scope or "all").strip().lower()
    if value not in SCOPES:
        raise FulltextError(f"非法 scope：{scope}（可选 my / trending / all）")
    return value


def normalize_query(query: str) -> str:
    value = " ".join((query or "").split())
    if not value:
        raise FulltextError("查询不能为空")
    return value


def extract_terms(query: str) -> list[str]:
    """按空白与常见标点切分检索词；保留 C++ / node.js / ci/cd 这类词。"""
    return [term for term in _TERM_SPLIT_RE.split(query) if term]


def _quote_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _like_escape(value: str) -> str:
    return _LIKE_ESCAPE_RE.sub(r"\\\1", value)


def _sources_for(scope: str) -> list[str]:
    normalized = normalize_scope(scope)
    return list(SOURCES) if normalized == "all" else [normalized]


def _max_chars() -> int:
    return max(1000, int(get_settings().FTS_MAX_README_CHARS))


def save_readme(
    db: Session,
    *,
    source: str,
    repo_id: str,
    content: str,
    commit: bool = True,
) -> RepoReadme:
    """写入 / 更新 README 镜像；FTS 索引由 SQLite 触发器自动同步。"""
    if source not in SOURCES:
        raise FulltextError(f"非法 source：{source}")
    cleaned = clean_readme(content or "")[: _max_chars()]
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
    now = _utcnow()
    row = db.get(RepoReadme, (source, repo_id))
    if row is None:
        row = RepoReadme(
            source=source,
            repo_id=repo_id,
            content=cleaned,
            content_hash=digest,
            char_count=len(cleaned),
            fetched_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.content = cleaned
        row.content_hash = digest
        row.char_count = len(cleaned)
        row.updated_at = now
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def delete_readme(db: Session, *, source: str, repo_id: str, commit: bool = True) -> bool:
    """删除 README 镜像；返回是否确实删除。"""
    row = db.get(RepoReadme, (source, repo_id))
    if row is None:
        return False
    db.delete(row)
    if commit:
        db.commit()
    return True


def rebuild_index(db: Session) -> dict[str, Any]:
    """全量重建 FTS 索引（删除后按镜像表重新灌入）。"""
    settings = get_settings()
    if not settings.FTS_ENABLED:
        raise FulltextDisabled("全文检索未启用")
    try:
        db.execute(text("DELETE FROM repo_readme_fts"))
    except Exception as exc:  # noqa: BLE001 - 表不存在时给出明确错误
        db.rollback()
        raise FulltextError(f"FTS 索引不可用：{exc}") from exc

    rows = list(db.execute(select(RepoReadme)).scalars().all())
    for row in rows:
        db.execute(
            text(
                "INSERT INTO repo_readme_fts(source, repo_id, content) "
                "VALUES (:source, :repo_id, :content)"
            ),
            {"source": row.source, "repo_id": row.repo_id, "content": row.content},
        )
    db.commit()
    return {"rebuilt": len(rows)}


def get_index_status(db: Session) -> dict[str, Any]:
    """索引覆盖率与来源分布。"""
    settings = get_settings()
    total = int(db.scalar(select(func.count()).select_from(RepoReadme)) or 0)
    total_chars = int(db.scalar(select(func.coalesce(func.sum(RepoReadme.char_count), 0))) or 0)
    by_source = {
        str(source): int(count)
        for source, count in db.execute(
            select(RepoReadme.source, func.count()).group_by(RepoReadme.source)
        ).all()
    }
    latest = db.scalar(select(func.max(RepoReadme.updated_at)))
    fts_docs: Optional[int]
    try:
        fts_docs = int(db.execute(text("SELECT count(*) FROM repo_readme_fts")).scalar() or 0)
    except Exception:  # noqa: BLE001 - 未初始化时返回 None
        db.rollback()
        fts_docs = None
    return {
        "enabled": bool(settings.FTS_ENABLED),
        "totalDocs": total,
        "bySource": by_source,
        "totalChars": total_chars,
        "ftsDocs": fts_docs,
        "latestUpdatedAt": latest.isoformat() if latest else None,
    }


def _make_snippet(content: str, terms: Iterable[str], *, max_chars: int = 240) -> str:
    """为 LIKE 回退生成命中片段（纯文本，不注入 HTML）。"""
    text_value = content or ""
    if not text_value:
        return ""
    lower = text_value.lower()
    positions = [lower.find(term.lower()) for term in terms if term]
    positions = [pos for pos in positions if pos >= 0]
    if not positions:
        return text_value[:max_chars] + ("…" if len(text_value) > max_chars else "")
    position = min(positions)
    start = max(0, position - max_chars // 3)
    end = min(len(text_value), start + max_chars)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text_value) else ""
    return f"{prefix}{text_value[start:end].strip()}{suffix}"


def _score_rows(ranks: list[float]) -> list[float]:
    """把 bm25（负值、越小越相关）归一化为 0.5~1.0 的展示分。"""
    values = [max(0.0, -float(rank)) for rank in ranks]
    top = max(values) if values else 0.0
    if top <= 0:
        return [1.0 for _ in values]
    return [round(0.5 + 0.5 * (value / top), 6) for value in values]


def _hydrate(
    db: Session,
    rows: list[Any],
    *,
    terms: list[str],
    snippets: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """把 FTS / LIKE 命中水合为完整项目信息。"""
    ranks = [float(getattr(row, "rank", 0.0) or 0.0) for row in rows]
    scores = _score_rows(ranks) if snippets is None else []
    items: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        source = str(row.source)
        repo_id = str(row.repo_id)
        model = MyRepository if source == "my" else TrendingRepository
        repo = db.get(model, repo_id)
        if repo is None:
            continue
        content = getattr(row, "content", "") or ""
        if not content:
            readme_row = db.get(RepoReadme, (source, repo_id))
            content = readme_row.content if readme_row is not None else ""
        # FTS5 trigram 的 snippet() 窗口在长文本上可能截断命中词，统一用原文重新取片段
        snippet = _make_snippet(content, terms) if content else (getattr(row, "snippet", "") or "")
        matched = [term for term in terms if term and term.lower() in content.lower()]
        description = getattr(repo, "description", "") or ""
        if source == "trending" and not description:
            description = getattr(repo, "readme_summary", "") or ""
        items.append(
            {
                "id": repo.id,
                "source": source,
                "fullName": repo.id,
                "name": repo.name,
                "description": description,
                "language": getattr(repo, "language", "") or "",
                "stars": int(getattr(repo, "stars", 0) or 0),
                "starsToday": int(getattr(repo, "stars_today", 0) or 0),
                "url": repo.html_url,
                "score": scores[index] if snippets is None else round(
                    len(matched) / max(1, len(terms)), 6
                ),
                "reason": f"README 全文命中：{len(matched)}/{max(1, len(terms))} 个关键词。",
                "snippet": snippet,
                "matchedTerms": matched,
            }
        )
    return items


def _fts_rows(
    db: Session,
    *,
    terms: list[str],
    short_terms: list[str],
    sources: list[str],
    limit: int,
    offset: int,
    joiner: str = "AND",
) -> list[Any]:
    match = f" {joiner} ".join(_quote_term(term) for term in terms)
    source_sql = ", ".join(f"'{source}'" for source in sources)
    clauses = [f"source IN ({source_sql})"]
    params: dict[str, Any] = {
        "match": match,
        "limit": limit,
        "offset": offset,
        "tokens": max(1, int(get_settings().FTS_SNIPPET_TOKENS)),
    }
    for index, term in enumerate(short_terms):
        clauses.append(f"content LIKE :short{index} ESCAPE '\\'")
        params[f"short{index}"] = f"%{_like_escape(term)}%"
    sql = text(
        "SELECT source, repo_id, bm25(repo_readme_fts) AS rank, "
        "snippet(repo_readme_fts, 2, '', '', '…', :tokens) AS snippet "
        "FROM repo_readme_fts "
        f"WHERE repo_readme_fts MATCH :match AND {' AND '.join(clauses)} "
        "ORDER BY rank LIMIT :limit OFFSET :offset"
    )
    return list(db.execute(sql, params).all())


def _like_rows(
    db: Session,
    *,
    terms: list[str],
    sources: list[str],
    limit: int,
) -> list[RepoReadme]:
    conditions = [
        RepoReadme.content.like(f"%{_like_escape(term)}%", escape="\\") for term in terms
    ]
    stmt = (
        select(RepoReadme)
        .where(RepoReadme.source.in_(sources))
        .where(or_(*conditions))
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def search_fulltext(
    db: Session,
    query: str,
    *,
    scope: str = "all",
    top_k: Optional[int] = None,
    offset: int = 0,
) -> dict[str, Any]:
    """README 全文检索：FTS5 优先，短词 / 无命中回退 LIKE。"""
    settings = get_settings()
    if not settings.FTS_ENABLED:
        raise FulltextDisabled("全文检索未启用")
    started = time.perf_counter()
    normalized = normalize_query(query)
    normalized_scope = normalize_scope(scope)
    effective_top_k = max(
        1, min(int(settings.FTS_MAX_TOP_K), int(top_k or settings.FTS_DEFAULT_TOP_K))
    )
    effective_offset = max(0, int(offset))
    terms = extract_terms(normalized)
    if not terms:
        raise FulltextError("查询不能为空")
    long_terms = [term for term in terms if len(term) >= 3]
    short_terms = [term for term in terms if len(term) < 3]
    sources = _sources_for(normalized_scope)
    fetch_limit = max(effective_top_k + effective_offset, effective_top_k * 4)
    mode = "like"
    items: list[dict[str, Any]] = []

    if long_terms:
        try:
            rows = _fts_rows(
                db,
                terms=long_terms,
                short_terms=short_terms,
                sources=sources,
                limit=fetch_limit,
                offset=effective_offset,
            )
            if not rows and len(long_terms) > 1:
                rows = _fts_rows(
                    db,
                    terms=long_terms,
                    short_terms=short_terms,
                    sources=sources,
                    limit=fetch_limit,
                    offset=effective_offset,
                    joiner="OR",
                )
            if rows:
                items = _hydrate(db, rows, terms=terms)
                mode = "fts"
        except Exception:  # noqa: BLE001 - FTS 语法 / 旧库异常回退 LIKE
            logger.warning("FTS 查询失败，回退 LIKE：%s", normalized, exc_info=True)
            db.rollback()

    if not items:
        rows = _like_rows(db, terms=terms, sources=sources, limit=max(fetch_limit, 50))
        scored: list[tuple[float, RepoReadme]] = []
        for row in rows:
            lower = row.content.lower()
            matched = sum(1 for term in terms if term.lower() in lower)
            if matched:
                scored.append((matched / len(terms), row))
        scored.sort(key=lambda item: (-item[0], -item[1].char_count))
        page = [row for _, row in scored[effective_offset : effective_offset + effective_top_k]]
        items = _hydrate(
            db,
            page,
            terms=terms,
            snippets=[_make_snippet(row.content, terms) for row in page],
        )
        mode = "like"

    return {
        "query": normalized,
        "scope": normalized_scope,
        "mode": mode,
        "count": len(items),
        "topK": effective_top_k,
        "offset": effective_offset,
        "tookMs": int((time.perf_counter() - started) * 1000),
        "terms": terms,
        "index": get_index_status(db),
        "items": items,
    }


def _select_targets(
    db: Session,
    *,
    source: str,
    repo_ids: Optional[Iterable[str]],
    limit: int,
    force: bool,
) -> list[Any]:
    if source == "my":
        model = MyRepository
        order = (MyRepository.stars.desc(), MyRepository.id.asc())
    elif source == "trending":
        model = TrendingRepository
        order = (TrendingRepository.stars_today.desc(), TrendingRepository.id.asc())
    else:
        raise FulltextError(f"非法 source：{source}")

    stmt = select(model).where(model.platform == "github").order_by(*order)
    ids = [str(item).strip() for item in (repo_ids or []) if str(item).strip()]
    if ids:
        stmt = stmt.where(model.id.in_(ids))
    rows = list(db.execute(stmt).scalars().all())
    if force:
        return rows[:limit]
    existing = {
        (str(row.source), str(row.repo_id))
        for row in db.execute(select(RepoReadme.source, RepoReadme.repo_id)).all()
    }
    return [row for row in rows if (source, row.id) not in existing][:limit]


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _default_fetch(token: str) -> Callable[[str], str]:
    from app.services.github_service import get_readme

    def fetch(repo_id: str) -> str:
        return _run_async(get_readme(token, repo_id))

    return fetch


def sync_readmes(
    db: Session,
    *,
    source: str = "all",
    repo_ids: Optional[Iterable[str]] = None,
    limit: Optional[int] = None,
    force: bool = False,
    token: str = "",
    fetch_fn: Optional[Callable[[str], str]] = None,
    batch_size: Optional[int] = None,
) -> dict[str, Any]:
    """为本地镜像仓库抓取 README 并写入 FTS 索引。"""
    settings = get_settings()
    if not settings.FTS_ENABLED:
        return {"status": "disabled", "reason": "FTS_ENABLED=false"}
    source_value = (source or "all").strip().lower()
    if source_value not in (*SOURCES, "all"):
        raise FulltextError(f"非法 source：{source}")
    limit_value = max(1, int(limit or settings.FTS_SYNC_MAX_PER_RUN))
    batch_value = max(1, int(batch_size or settings.FTS_SYNC_BATCH_SIZE))
    fetch = fetch_fn or _default_fetch((token or settings.GITHUB_TOKEN or "").strip())
    sources = list(SOURCES) if source_value == "all" else [source_value]
    stats: dict[str, Any] = {
        "status": "ok",
        "source": source_value,
        "total": 0,
        "fetched": 0,
        "indexed": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    remaining = limit_value
    for item_source in sources:
        if remaining <= 0:
            break
        targets = _select_targets(
            db,
            source=item_source,
            repo_ids=repo_ids,
            limit=remaining,
            force=force,
        )
        remaining -= len(targets)
        stats["total"] += len(targets)
        for index, repo in enumerate(targets, start=1):
            try:
                raw = fetch(repo.id)
            except Exception as exc:  # noqa: BLE001 - 单条失败不阻塞整批
                stats["failed"] += 1
                stats["errors"].append({"repoId": repo.id, "error": str(exc)[:300]})
                continue
            if not raw:
                stats["skipped"] += 1
                continue
            cleaned = clean_readme(raw)
            if not cleaned:
                stats["skipped"] += 1
                continue
            save_readme(
                db,
                source=item_source,
                repo_id=repo.id,
                content=cleaned,
                commit=False,
            )
            stats["fetched"] += 1
            stats["indexed"] += 1
            if index % batch_value == 0:
                db.commit()
        db.commit()

    if stats["failed"] and not stats["indexed"]:
        stats["status"] = "error"
    elif stats["failed"]:
        stats["status"] = "partial"
    return stats
