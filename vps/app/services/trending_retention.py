"""热榜数据保留策略（M2-08）：保留窗口、归档与清理。

职责：
- `archive_snapshots`：把过期快照写成 gzip JSONL 归档（先落盘、再删除）；
- `cleanup_trending_snapshots`：按保留窗口归档并删除本地镜像快照，同时清理过期归档；
- `retention_status`：保留策略与磁盘占用状态，供 API / 运维查询；
- `cleanup_edge_trending_snapshots`：调用 edge 内部接口清理 D1 同日期范围快照。

安全约束：归档失败时**不删除**任何快照；所有时间边界按 `snapshot_date`（DATE）比较，
保留窗口含 cutoff 当天，即删除 `snapshot_date < cutoff` 的行。
"""
from __future__ import annotations

import gzip
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import BASE_DIR, get_settings
from app.models import TrendingSnapshot

logger = logging.getLogger(__name__)

ARCHIVE_PREFIX = "trending-snapshots-"
ARCHIVE_SUFFIX = ".jsonl.gz"
ARCHIVE_FORMAT = "openfactory.trending_snapshots"
ARCHIVE_VERSION = 1
EDGE_CLEANUP_TIMEOUT_SECONDS = 10.0


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_archive_dir(value: Optional[str | Path] = None) -> Path:
    """归档目录：相对路径按 `vps/` 根目录解析，避免受进程 cwd 影响。"""
    raw = Path(value if value is not None else get_settings().TRENDING_ARCHIVE_DIR).expanduser()
    if not raw.is_absolute():
        raw = BASE_DIR / raw
    return raw


def retention_cutoff(today: date, retention_days: int) -> date:
    """保留窗口起点：删除早于该日期的快照。"""
    return today - timedelta(days=max(0, int(retention_days)))


def _row_to_dict(row: TrendingSnapshot) -> dict[str, Any]:
    """ORM 行 → 可 JSON 序列化的归档记录（字段与表结构一致）。"""
    return {
        "snapshot_date": row.snapshot_date.isoformat() if row.snapshot_date else None,
        "repo_id": row.repo_id,
        "platform": row.platform,
        "owner": row.owner,
        "name": row.name,
        "html_url": row.html_url,
        "description": row.description,
        "language": row.language,
        "tech_stack": row.tech_stack,
        "stars": row.stars,
        "stars_today": row.stars_today,
        "rank": row.rank,
        "language_rank": row.language_rank,
        "star_delta": row.star_delta,
        "rank_delta": row.rank_delta,
        "appearances": row.appearances,
        "is_new": row.is_new,
        "trend": row.trend,
        "trending_pages": row.trending_pages,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def archive_snapshots(
    db: Session,
    before_date: date,
    archive_dir: Optional[str | Path] = None,
) -> dict[str, Any]:
    """把 `snapshot_date < before_date` 的快照写成 gzip JSONL。

    返回 `{archived, file, bytes, firstDate, lastDate}`；无过期数据时不创建文件。
    写入采用「临时文件 + 原子 rename」，任何异常都会清理临时文件并向上抛出。
    """
    target_dir = resolve_archive_dir(archive_dir)
    stmt = (
        select(TrendingSnapshot)
        .where(TrendingSnapshot.snapshot_date < before_date)
        .order_by(TrendingSnapshot.snapshot_date.asc(), TrendingSnapshot.repo_id.asc())
        .execution_options(yield_per=1000)
    )

    bounds = db.execute(
        select(func.min(TrendingSnapshot.snapshot_date), func.max(TrendingSnapshot.snapshot_date))
        .where(TrendingSnapshot.snapshot_date < before_date)
    ).one()
    first_date, last_date = bounds[0], bounds[1]
    if first_date is None or last_date is None:
        return {"archived": 0, "file": None, "bytes": 0, "firstDate": None, "lastDate": None}

    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{ARCHIVE_PREFIX}{first_date.isoformat()}_{last_date.isoformat()}{ARCHIVE_SUFFIX}"
    path = target_dir / filename
    temp_path = path.with_name(f"{path.name}.tmp")
    row_count = _count_snapshots(db, before_date)

    archived = 0
    try:
        with gzip.open(temp_path, "wt", encoding="utf-8") as handle:
            header = {
                "format": ARCHIVE_FORMAT,
                "version": ARCHIVE_VERSION,
                "exportedAt": _utcnow_iso(),
                "beforeDate": before_date.isoformat(),
                "firstDate": first_date.isoformat(),
                "lastDate": last_date.isoformat(),
                "rowCount": row_count,
            }
            handle.write(json.dumps(header, ensure_ascii=False, separators=(",", ":")) + "\n")
            for row in db.execute(stmt).scalars():
                handle.write(json.dumps(_row_to_dict(row), ensure_ascii=False, separators=(",", ":")) + "\n")
                archived += 1
        os.replace(temp_path, path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise

    size = path.stat().st_size
    logger.info("热榜快照已归档: %s（%d 行，%d 字节）", path, archived, size)
    return {
        "archived": archived,
        "file": str(path),
        "bytes": size,
        "firstDate": first_date.isoformat(),
        "lastDate": last_date.isoformat(),
    }


def prune_archives(
    archive_dir: Optional[str | Path] = None,
    keep_days: Optional[int] = None,
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """删除超过保留期的归档文件；`keep_days <= 0` 表示永久保留。"""
    settings = get_settings()
    days = settings.TRENDING_ARCHIVE_KEEP_DAYS if keep_days is None else int(keep_days)
    if days <= 0:
        return {"deleted": 0, "bytes": 0}

    target_dir = resolve_archive_dir(archive_dir)
    if not target_dir.exists():
        return {"deleted": 0, "bytes": 0}

    cutoff = (now or datetime.now(timezone.utc)).timestamp() - days * 86400
    deleted = 0
    freed = 0
    for path in target_dir.glob(f"{ARCHIVE_PREFIX}*{ARCHIVE_SUFFIX}"):
        try:
            stat = path.stat()
            if stat.st_mtime >= cutoff:
                continue
            freed += stat.st_size
            path.unlink()
            deleted += 1
        except OSError as exc:  # noqa: BLE001 - 单个文件失败不影响其他归档
            logger.warning("清理归档文件失败 %s: %s", path, exc)

    if deleted:
        logger.info("已清理过期热榜归档 %d 个（释放 %d 字节）", deleted, freed)
    return {"deleted": deleted, "bytes": freed}


def _count_snapshots(db: Session, before_date: Optional[date] = None) -> int:
    stmt = select(func.count()).select_from(TrendingSnapshot)
    if before_date is not None:
        stmt = stmt.where(TrendingSnapshot.snapshot_date < before_date)
    return int(db.execute(stmt).scalar_one())


def _sqlite_database_path() -> Optional[Path]:
    """从 `DATABASE_URL` 解析 SQLite 文件路径；非 SQLite / 内存库返回 None。"""
    url = get_settings().DATABASE_URL
    if not url.startswith("sqlite"):
        return None
    raw = url.split(":///", 1)[-1].split("?", 1)[0]
    if not raw or raw == ":memory:":
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _archive_stats(archive_dir: Path) -> dict[str, int]:
    if not archive_dir.exists():
        return {"files": 0, "bytes": 0}
    files = list(archive_dir.glob(f"{ARCHIVE_PREFIX}*{ARCHIVE_SUFFIX}"))
    total = 0
    for path in files:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return {"files": len(files), "bytes": total}


def retention_status(
    db: Session,
    *,
    today: Optional[date] = None,
    retention_days: Optional[int] = None,
    archive_dir: Optional[str | Path] = None,
    archive_keep_days: Optional[int] = None,
) -> dict[str, Any]:
    """保留策略状态：窗口、过期量、最早 / 最新快照、库文件与归档占用。"""
    settings = get_settings()
    days = int(settings.TRENDING_RETENTION_DAYS if retention_days is None else retention_days)
    keep_days = int(
        settings.TRENDING_ARCHIVE_KEEP_DAYS if archive_keep_days is None else archive_keep_days
    )
    target_date = today or date.today()
    cutoff = retention_cutoff(target_date, days) if days > 0 else None
    total = _count_snapshots(db)
    expired = _count_snapshots(db, cutoff) if cutoff is not None else 0

    oldest, latest = db.execute(
        select(func.min(TrendingSnapshot.snapshot_date), func.max(TrendingSnapshot.snapshot_date))
    ).one()

    db_path = _sqlite_database_path()
    db_bytes = 0
    if db_path is not None:
        try:
            db_bytes = db_path.stat().st_size
        except OSError:
            db_bytes = 0

    archive_dir_path = resolve_archive_dir(archive_dir)
    stats = _archive_stats(archive_dir_path)

    return {
        "enabled": days > 0,
        "retentionDays": days,
        "cutoff": cutoff.isoformat() if cutoff else None,
        "archiveEnabled": bool(settings.TRENDING_ARCHIVE_ENABLED),
        "archiveDir": str(archive_dir_path),
        "archiveKeepDays": keep_days,
        "totalSnapshots": total,
        "expiredSnapshots": expired,
        "oldestDate": oldest.isoformat() if oldest else None,
        "latestDate": latest.isoformat() if latest else None,
        "databaseBytes": db_bytes,
        "archiveFiles": stats["files"],
        "archiveBytes": stats["bytes"],
    }


def cleanup_trending_snapshots(
    db: Session,
    *,
    today: Optional[date] = None,
    retention_days: Optional[int] = None,
    archive: Optional[bool] = None,
    archive_dir: Optional[str | Path] = None,
    archive_keep_days: Optional[int] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """按保留窗口归档并删除本地快照；归档失败时中止删除并返回 error。"""
    settings = get_settings()
    days = int(settings.TRENDING_RETENTION_DAYS if retention_days is None else retention_days)
    archive_enabled = bool(settings.TRENDING_ARCHIVE_ENABLED if archive is None else archive)
    keep_days = int(
        settings.TRENDING_ARCHIVE_KEEP_DAYS if archive_keep_days is None else archive_keep_days
    )
    target_date = today or date.today()

    total = _count_snapshots(db)
    if days <= 0:
        return {
            "status": "disabled",
            "retentionDays": days,
            "cutoff": None,
            "totalBefore": total,
            "expired": 0,
            "archived": 0,
            "archiveFile": None,
            "archiveBytes": 0,
            "deleted": 0,
            "archiveSkipped": True,
            "prunedArchives": 0,
            "prunedBytes": 0,
        }

    cutoff = retention_cutoff(target_date, days)
    expired = _count_snapshots(db, cutoff)
    base = {
        "retentionDays": days,
        "cutoff": cutoff.isoformat(),
        "totalBefore": total,
        "expired": expired,
        "archived": 0,
        "archiveFile": None,
        "archiveBytes": 0,
        "deleted": 0,
        "archiveSkipped": not archive_enabled,
        "prunedArchives": 0,
        "prunedBytes": 0,
    }

    if dry_run:
        return {"status": "dry_run", **base}

    archive_result: dict[str, Any] = {"archived": 0, "file": None, "bytes": 0}
    if archive_enabled and expired > 0:
        try:
            archive_result = archive_snapshots(db, cutoff, archive_dir)
        except Exception as exc:  # noqa: BLE001 - 归档失败必须阻止删除
            logger.exception("热榜快照归档失败，已跳过清理")
            return {
                "status": "error",
                "error": f"归档失败，未删除任何快照: {str(exc)[:300]}",
                **base,
            }

    result = db.execute(delete(TrendingSnapshot).where(TrendingSnapshot.snapshot_date < cutoff))
    db.commit()
    deleted = int(result.rowcount or 0)

    prune = {"deleted": 0, "bytes": 0}
    try:
        prune = prune_archives(archive_dir, keep_days)
    except Exception as exc:  # noqa: BLE001 - 归档清理失败不影响主流程
        logger.warning("清理过期热榜归档失败: %s", exc)

    logger.info(
        "热榜保留清理完成: cutoff=%s 过期=%d 归档=%d 删除=%d",
        cutoff,
        expired,
        archive_result["archived"],
        deleted,
    )
    return {
        "status": "ok",
        **base,
        "archived": archive_result["archived"],
        "archiveFile": archive_result["file"],
        "archiveBytes": archive_result["bytes"],
        "deleted": deleted,
        "prunedArchives": prune["deleted"],
        "prunedBytes": prune["bytes"],
    }


def cleanup_edge_trending_snapshots(
    before_date: date,
    *,
    dry_run: bool = False,
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> dict[str, Any]:
    """调用 edge 内部接口删除 D1 中 `snapshot_date < before_date` 的快照。

    未配置边缘地址 / 内部令牌时跳过；HTTP 或网络异常只记录并返回 error，不抛异常。
    """
    settings = get_settings()
    edge_base = (base_url if base_url is not None else settings.EDGE_BASE_URL).strip()
    internal_token = (token if token is not None else settings.INTERNAL_TOKEN).strip()
    if not edge_base or not internal_token:
        return {"skipped": True, "deleted": 0, "error": None}

    endpoint = f"{edge_base.rstrip('/')}/api/internal/trending/retention/cleanup"
    headers = {"Content-Type": "application/json", "X-Internal-Token": internal_token}
    payload = {"beforeDate": before_date.isoformat(), "dryRun": dry_run}
    owns_client = client is None
    http_client = client or httpx.Client(timeout=EDGE_CLEANUP_TIMEOUT_SECONDS)
    try:
        response = http_client.post(endpoint, json=payload, headers=headers)
        if response.status_code >= 400:
            logger.warning("热榜 D1 清理失败: HTTP %s", response.status_code)
            return {
                "skipped": False,
                "deleted": 0,
                "error": f"HTTP {response.status_code}",
            }
        data = response.json()
        return {
            "skipped": False,
            "deleted": int(data.get("deleted") or 0),
            "error": None,
        }
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("热榜 D1 清理异常: %s", exc)
        return {"skipped": False, "deleted": 0, "error": str(exc)[:300]}
    finally:
        if owns_client:
            http_client.close()
