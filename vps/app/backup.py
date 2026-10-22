"""备份与恢复（REQ-202610-0942 / M5-04）。

仅使用标准库，便于在未安装应用依赖的系统 Python 下直接运行：

    cd vps
    python3 -m app.backup status --backup-dir /opt/openfactory/backups
    python3 -m app.backup create --database data/opensource_factory.db --backup-dir /opt/openfactory/backups
    python3 -m app.backup drill  --backup-dir /opt/openfactory/backups

设计要点：

- SQLite 快照使用 ``sqlite3.Connection.backup()``，对 WAL 模式同样能取得一致性视图；
- 每份产物配一个 ``.json`` 清单（大小 / SHA-256 / 表行数 / 完整性结果），状态扫描不依赖业务库；
- 恢复默认拒绝覆盖；``--force`` 覆盖前自动生成 pre-restore 快照；
- 保留策略按「每类份数 + 备份总量」双阈值清理，最新一份永不删除；
- D1 导出是 SQL 文本，校验方式是导入临时 SQLite 并做完整性与表行数核对。
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SQLITE_KIND = "sqlite"
D1_KIND = "d1"
KINDS = (SQLITE_KIND, D1_KIND)
SQLITE_SUFFIX = ".sqlite3.gz"
D1_SUFFIX = ".sql.gz"
MANIFEST_SUFFIX = ".json"
DEFAULT_RETENTION = 7
DEFAULT_MAX_TOTAL_MB = 3072
LABEL_RE = re.compile(r"[^A-Za-z0-9._-]+")


class BackupError(RuntimeError):
    """备份 / 校验 / 恢复失败（CLI 捕获后以退出码 1 返回）。"""


@dataclass
class BackupCheck:
    """单项检查结果。"""

    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass
class BackupEntry:
    """一份备份产物（文件 + 清单）。"""

    kind: str
    name: str
    path: Path
    created_at: str
    size_bytes: int
    sha256: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "path": str(self.path),
            "createdAt": self.created_at,
            "sizeBytes": self.size_bytes,
            "sha256": self.sha256,
        }


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def utc_stamp(now: Optional[datetime] = None) -> str:
    """生成文件名时间戳（UTC，秒级）。"""
    return _now(now).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _iso(now: Optional[datetime] = None) -> str:
    return _now(now).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_label(label: str) -> str:
    cleaned = LABEL_RE.sub("-", (label or "").strip()).strip("-._")
    return cleaned[:40]


def _kind_dir(backup_dir: Path, kind: str) -> Path:
    return Path(backup_dir) / kind


def _manifest_path(path: Path) -> Path:
    return Path(str(path) + MANIFEST_SUFFIX)


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _read_manifest(path: Path) -> dict[str, Any]:
    manifest = _manifest_path(path)
    if not manifest.is_file():
        return {}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_stamp_from_name(name: str) -> str:
    match = re.search(r"-(\d{8}T\d{6}Z)", name)
    if not match:
        return ""
    try:
        parsed = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    return parsed.isoformat().replace("+00:00", "Z")


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    counts: dict[str, int] = {}
    for (name,) in rows:
        quoted = str(name).replace('"', '""')
        counts[str(name)] = int(conn.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0])
    return counts


def _integrity_checks(conn: sqlite3.Connection) -> list[BackupCheck]:
    integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    checks = [BackupCheck("integrity", integrity.lower() == "ok", integrity)]
    try:
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.DatabaseError as exc:  # 旧库 / 特殊 schema 可能不支持
        checks.append(BackupCheck("foreign_keys", False, str(exc)))
    else:
        checks.append(
            BackupCheck(
                "foreign_keys",
                not violations,
                "ok" if not violations else f"{len(violations)} 条外键违规",
            )
        )
    return checks


def _open_readonly(path: Path) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=30)


def _decompress_to(path: Path, target: Path) -> None:
    """把 .gz 快照解压到 target；非 gz 文件直接复制。"""
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as source, target.open("wb") as dest:
            shutil.copyfileobj(source, dest, 1024 * 1024)
    else:
        shutil.copyfile(path, target)


def _gzip_file(source: Path, target: Path) -> None:
    with source.open("rb") as src, gzip.open(target, "wb", compresslevel=6) as dest:
        shutil.copyfileobj(src, dest, 1024 * 1024)


def _ensure_kind_dir(backup_dir: Path, kind: str) -> Path:
    directory = _kind_dir(backup_dir, kind)
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory


def _unique_path(path: Path) -> Path:
    """同一秒内重复创建时追加序号，避免覆盖已有备份。"""
    if not path.exists():
        return path
    stem = path.name[: -len(path.suffixes[-2:])] if len(path.suffixes) >= 2 else path.stem
    suffixes = "".join(path.suffixes[-2:]) if len(path.suffixes) >= 2 else path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffixes}")
        if not candidate.exists():
            return candidate
    raise BackupError(f"无法为备份生成唯一文件名：{path}")


def _entry_from_path(kind: str, path: Path) -> BackupEntry:
    manifest = _read_manifest(path)
    stat = path.stat()
    created_at = str(manifest.get("createdAt") or _parse_stamp_from_name(path.name) or "")
    if not created_at:
        created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return BackupEntry(
        kind=kind,
        name=path.name,
        path=path,
        created_at=created_at,
        size_bytes=int(stat.st_size),
        sha256=str(manifest.get("sha256") or ""),
        manifest=manifest,
    )


def list_backups(backup_dir: Path | str, kind: Optional[str] = None) -> list[BackupEntry]:
    """列出备份产物，按创建时间倒序。"""
    root = Path(backup_dir)
    kinds = (kind,) if kind else KINDS
    entries: list[BackupEntry] = []
    for current in kinds:
        if current not in KINDS:
            raise BackupError(f"未知备份类型：{current}")
        directory = _kind_dir(root, current)
        if not directory.is_dir():
            continue
        suffix = SQLITE_SUFFIX if current == SQLITE_KIND else D1_SUFFIX
        for path in directory.glob(f"*{suffix}"):
            if path.is_file():
                entries.append(_entry_from_path(current, path))
    entries.sort(key=lambda item: (item.created_at, item.name), reverse=True)
    return entries


def _resolve_entry(backup_dir: Path | str, kind: str, name: Optional[str] = None) -> BackupEntry:
    entries = list_backups(backup_dir, kind)
    if not entries:
        raise BackupError(f"没有可用的 {kind} 备份：{backup_dir}")
    if not name:
        return entries[0]
    if Path(name).name != name:
        raise BackupError("备份名只能是文件名，不能包含路径")
    for entry in entries:
        if entry.name == name:
            return entry
    raise BackupError(f"未找到备份：{name}")


def backup_status(
    backup_dir: Path | str,
    *,
    retention: int = DEFAULT_RETENTION,
    max_total_mb: int = DEFAULT_MAX_TOTAL_MB,
) -> dict[str, Any]:
    """汇总备份目录状态（供 API / CLI 使用）。"""
    root = Path(backup_dir)
    entries = list_backups(root)
    total = sum(entry.size_bytes for entry in entries)
    max_bytes = max(0, int(max_total_mb)) * 1024 * 1024
    per_kind: dict[str, Any] = {}
    for kind in KINDS:
        items = [entry for entry in entries if entry.kind == kind]
        per_kind[kind] = {
            "count": len(items),
            "totalBytes": sum(item.size_bytes for item in items),
            "latest": items[0].to_dict() if items else None,
        }
    free_bytes = None
    if root.exists():
        try:
            free_bytes = shutil.disk_usage(root).free
        except OSError:
            free_bytes = None
    return {
        "backupDir": str(root),
        "retention": int(retention),
        "maxTotalBytes": max_bytes,
        "totalBytes": total,
        "usagePercent": round(total / max_bytes * 100, 1) if max_bytes else 0.0,
        "withinBudget": max_bytes == 0 or total <= max_bytes,
        "freeBytes": free_bytes,
        "counts": {kind: per_kind[kind]["count"] for kind in KINDS},
        "kinds": per_kind,
        "latest": entries[0].to_dict() if entries else None,
    }


def prune_backups(
    backup_dir: Path | str,
    *,
    keep: int = DEFAULT_RETENTION,
    max_total_bytes: int = 0,
    protect: Iterable[str] = (),
) -> list[str]:
    """按份数与总量清理备份；返回被删除的文件名。

    - 每类至少保留最新 1 份；``keep`` 为每类保留份数；
    - ``max_total_bytes`` > 0 时，删除最旧产物直到总量达标（保护最新一份与 ``protect``）；
    - 只删除本模块管理的 ``.sqlite3.gz`` / ``.sql.gz`` 及其 ``.json`` 清单。
    """
    root = Path(backup_dir)
    keep = max(1, int(keep))
    protected = set(protect)
    entries = list_backups(root)
    keep_names: set[str] = set()
    for kind in KINDS:
        for entry in [item for item in entries if item.kind == kind][:keep]:
            keep_names.add(entry.name)

    deleted: list[str] = []

    def _delete(entry: BackupEntry) -> None:
        if entry.name in protected or entry.name in deleted:
            return
        try:
            entry.path.unlink()
        except FileNotFoundError:
            pass
        try:
            _manifest_path(entry.path).unlink()
        except FileNotFoundError:
            pass
        deleted.append(entry.name)

    # 1) 超出份数的最旧产物
    for entry in reversed(entries):
        if entry.name not in keep_names:
            _delete(entry)

    # 2) 超出总量预算：从最旧开始删，但保留每类最新一份
    if max_total_bytes and max_total_bytes > 0:
        remaining = [item for item in list_backups(root)]
        total = sum(item.size_bytes for item in remaining)
        latest_names = {
            item.name for kind in KINDS for item in [x for x in remaining if x.kind == kind][:1]
        }
        for entry in reversed(remaining):
            if total <= max_total_bytes:
                break
            if entry.name in latest_names or entry.name in protected:
                continue
            size = entry.size_bytes
            _delete(entry)
            total -= size

    return deleted


def create_sqlite_snapshot(
    database: Path | str,
    backup_dir: Path | str,
    *,
    label: str = "",
    keep: int = DEFAULT_RETENTION,
    max_total_bytes: int = 0,
    verify_integrity: bool = True,
    now: Optional[datetime] = None,
) -> BackupEntry:
    """创建 SQLite 一致性快照（gzip + manifest），并执行保留清理。

    ``verify_integrity=False`` 用于恢复前的安全快照：即使源库已损坏也尽量留一份现场。
    """
    db_path = Path(database).expanduser()
    if not db_path.is_file():
        raise BackupError(f"数据库文件不存在：{db_path}")
    directory = _ensure_kind_dir(Path(backup_dir), SQLITE_KIND)
    stamp = utc_stamp(now)
    safe_label = _safe_label(label)
    name = f"sqlite-{stamp}{('-' + safe_label) if safe_label else ''}{SQLITE_SUFFIX}"
    final = _unique_path(directory / name)
    name = final.name
    tmp_db = directory / f".tmp-{uuid.uuid4().hex}.sqlite3"
    tmp_gz = directory / f".tmp-{uuid.uuid4().hex}.gz"

    try:
        source = _open_readonly(db_path)
        try:
            target = sqlite3.connect(tmp_db)
            try:
                source.backup(target)
                integrity = str(target.execute("PRAGMA integrity_check").fetchone()[0])
                if verify_integrity and integrity.lower() != "ok":
                    raise BackupError(f"快照完整性检查失败：{integrity}")
                try:
                    table_counts = _table_counts(target)
                except sqlite3.DatabaseError:
                    table_counts = {}
                sqlite_version = sqlite3.sqlite_version
            finally:
                target.close()
        finally:
            source.close()

        _gzip_file(tmp_db, tmp_gz)
        os.chmod(tmp_gz, 0o600)
        os.replace(tmp_gz, final)
        size_bytes = final.stat().st_size
        sha256 = _sha256_file(final)
        manifest = {
            "kind": SQLITE_KIND,
            "name": name,
            "createdAt": _iso(now),
            "source": str(db_path.resolve()),
            "sizeBytes": size_bytes,
            "sha256": sha256,
            "sqliteVersion": sqlite_version,
            "tableCounts": table_counts,
            "integrity": integrity,
            "label": safe_label,
        }
        _atomic_json(_manifest_path(final), manifest)
        prune_backups(
            backup_dir,
            keep=keep,
            max_total_bytes=max_total_bytes,
            protect={name},
        )
        return _entry_from_path(SQLITE_KIND, final)
    finally:
        for temp in (tmp_db, tmp_gz):
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


def verify_sqlite_snapshot(path: Path | str) -> dict[str, Any]:
    """校验 SQLite 快照：SHA-256、完整性、外键、表行数。"""
    snapshot = Path(path)
    checks: list[BackupCheck] = []
    result: dict[str, Any] = {
        "ok": False,
        "name": snapshot.name,
        "path": str(snapshot),
        "checks": [],
        "tableCounts": {},
        "sizeBytes": 0,
        "sha256": "",
        "error": "",
    }
    if not snapshot.is_file():
        result["checks"] = [BackupCheck("file", False, "文件不存在").to_dict()]
        result["error"] = f"文件不存在：{snapshot}"
        return result

    result["sizeBytes"] = snapshot.stat().st_size
    result["sha256"] = _sha256_file(snapshot)
    manifest = _read_manifest(snapshot)
    checks.append(BackupCheck("file", True, str(snapshot)))
    if manifest.get("sha256"):
        checks.append(
            BackupCheck(
                "sha256",
                manifest["sha256"] == result["sha256"],
                "与清单一致" if manifest["sha256"] == result["sha256"] else "与清单不一致",
            )
        )
    else:
        checks.append(BackupCheck("sha256", True, "无清单，跳过比对"))

    temp_dir = Path(tempfile.mkdtemp(prefix="openfactory-verify-"))
    restored = temp_dir / "snapshot.sqlite3"
    try:
        _decompress_to(snapshot, restored)
        conn = _open_readonly(restored)
        try:
            checks.extend(_integrity_checks(conn))
            counts = _table_counts(conn)
            result["tableCounts"] = counts
            expected = manifest.get("tableCounts")
            if isinstance(expected, dict):
                mismatch = {
                    key: {"expected": expected.get(key), "actual": counts.get(key)}
                    for key in sorted(set(expected) | set(counts))
                    if expected.get(key) != counts.get(key)
                }
                checks.append(
                    BackupCheck(
                        "table_counts",
                        not mismatch,
                        "与清单一致" if not mismatch else f"{len(mismatch)} 张表行数不一致",
                    )
                )
            else:
                checks.append(BackupCheck("table_counts", True, "无清单，跳过比对"))
        finally:
            conn.close()
    except (OSError, sqlite3.DatabaseError, EOFError, gzip.BadGzipFile) as exc:
        checks.append(BackupCheck("readable", False, str(exc)))
        result["error"] = str(exc)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    result["checks"] = [check.to_dict() for check in checks]
    result["ok"] = bool(checks) and all(check.ok for check in checks)
    if not result["ok"] and not result["error"]:
        result["error"] = "；".join(check.detail for check in checks if not check.ok)
    return result


def restore_sqlite_snapshot(
    snapshot: Path | str,
    target: Path | str,
    *,
    force: bool = False,
    safety_dir: Path | str | None = None,
    keep: int = 3,
) -> dict[str, Any]:
    """把快照恢复到目标 SQLite 文件。

    目标已存在时必须 ``force=True``；覆盖前自动在 ``safety_dir`` 生成 pre-restore 快照。
    """
    snapshot_path = Path(snapshot)
    target_path = Path(target).expanduser()
    verification = verify_sqlite_snapshot(snapshot_path)
    if not verification["ok"]:
        raise BackupError(f"快照校验失败，拒绝恢复：{verification['error']}")

    safety: Optional[BackupEntry] = None
    if target_path.exists():
        if not force:
            raise BackupError(f"目标已存在，需显式 --force：{target_path}")
        safety_root = Path(safety_dir) if safety_dir else target_path.parent / "pre-restore"
        try:
            safety = create_sqlite_snapshot(
                target_path,
                safety_root,
                label="pre-restore",
                keep=keep,
                max_total_bytes=0,
                verify_integrity=False,
            )
        except BackupError:
            # 目标库已损坏到 backup API 无法读取时，不阻塞恢复；报告中留空并提示。
            safety = None

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="openfactory-restore-"))
    restored = temp_dir / "snapshot.sqlite3"
    try:
        _decompress_to(snapshot_path, restored)
        source = _open_readonly(restored)
        try:
            destination = sqlite3.connect(target_path, timeout=30)
            try:
                source.backup(destination)
                integrity = str(destination.execute("PRAGMA integrity_check").fetchone()[0])
                if integrity.lower() != "ok":
                    raise BackupError(f"恢复后完整性检查失败：{integrity}")
                destination.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                table_counts = _table_counts(destination)
            finally:
                destination.close()
        finally:
            source.close()
    except (OSError, sqlite3.DatabaseError, EOFError, gzip.BadGzipFile) as exc:
        raise BackupError(f"恢复失败：{exc}") from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return {
        "ok": True,
        "snapshot": snapshot_path.name,
        "restoredTo": str(target_path.resolve()),
        "safetySnapshot": safety.name if safety else "",
        "tableCounts": table_counts,
        "checks": verification["checks"],
    }


def run_restore_drill(
    backup_dir: Path | str,
    *,
    name: Optional[str] = None,
    work_dir: Path | str | None = None,
    keep_work: bool = False,
) -> dict[str, Any]:
    """恢复演练：把最新 / 指定 SQLite 快照恢复到临时库并核对表行数。"""
    started = time.monotonic()
    entry = _resolve_entry(backup_dir, SQLITE_KIND, name)
    checks: list[BackupCheck] = []
    report: dict[str, Any] = {
        "ok": False,
        "snapshot": entry.name,
        "restoredPath": "",
        "checks": [],
        "tableCounts": {},
        "durationMs": 0,
        "error": "",
    }
    verification = verify_sqlite_snapshot(entry.path)
    checks.extend(BackupCheck(**item) for item in verification["checks"])
    if not verification["ok"]:
        report["checks"] = [check.to_dict() for check in checks]
        report["error"] = verification["error"]
        report["durationMs"] = int((time.monotonic() - started) * 1000)
        return report

    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="openfactory-drill-"))
    work.mkdir(parents=True, exist_ok=True)
    restored = work / f"drill-{uuid.uuid4().hex}.sqlite3"
    try:
        result = restore_sqlite_snapshot(entry.path, restored, force=False)
        counts = result["tableCounts"]
        report["tableCounts"] = counts
        expected = entry.manifest.get("tableCounts")
        if isinstance(expected, dict):
            mismatch = {
                key: {"expected": expected.get(key), "actual": counts.get(key)}
                for key in sorted(set(expected) | set(counts))
                if expected.get(key) != counts.get(key)
            }
            checks.append(
                BackupCheck(
                    "drill_table_counts",
                    not mismatch,
                    "与清单一致" if not mismatch else f"{len(mismatch)} 张表行数不一致",
                )
            )
        else:
            checks.append(BackupCheck("drill_table_counts", True, "无清单，跳过比对"))
        checks.append(BackupCheck("restore", True, "已恢复到临时库"))
        report["restoredPath"] = result["restoredTo"]
    except BackupError as exc:
        checks.append(BackupCheck("restore", False, str(exc)))
        report["error"] = str(exc)
    finally:
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)

    report["checks"] = [check.to_dict() for check in checks]
    report["ok"] = all(check.ok for check in checks)
    if not report["ok"] and not report["error"]:
        report["error"] = "；".join(check.detail for check in checks if not check.ok)
    report["durationMs"] = int((time.monotonic() - started) * 1000)
    return report


def verify_d1_dump(
    path: Path | str,
    *,
    expected_tables: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """校验 D1 SQL 导出：流式导入临时 SQLite，检查完整性与表行数。"""
    dump = Path(path)
    checks: list[BackupCheck] = []
    result: dict[str, Any] = {
        "ok": False,
        "name": dump.name,
        "path": str(dump),
        "checks": [],
        "tableCounts": {},
        "sizeBytes": 0,
        "sha256": "",
        "error": "",
    }
    if not dump.is_file():
        result["checks"] = [BackupCheck("file", False, "文件不存在").to_dict()]
        result["error"] = f"文件不存在：{dump}"
        return result

    result["sizeBytes"] = dump.stat().st_size
    result["sha256"] = _sha256_file(dump)
    manifest = _read_manifest(dump)
    checks.append(BackupCheck("file", True, str(dump)))
    if manifest.get("sha256"):
        checks.append(
            BackupCheck(
                "sha256",
                manifest["sha256"] == result["sha256"],
                "与清单一致" if manifest["sha256"] == result["sha256"] else "与清单不一致",
            )
        )
    else:
        checks.append(BackupCheck("sha256", True, "无清单，跳过比对"))

    temp_dir = Path(tempfile.mkdtemp(prefix="openfactory-d1-verify-"))
    restored = temp_dir / "d1-import.sqlite3"
    statement_count = 0
    try:
        if dump.suffix == ".gz":
            with gzip.open(dump, "rt", encoding="utf-8", errors="strict") as source:
                statement_count = _execute_sql_stream(source, restored)
        else:
            with dump.open("r", encoding="utf-8", errors="strict") as source:
                statement_count = _execute_sql_stream(source, restored)
        conn = _open_readonly(restored)
        try:
            checks.extend(_integrity_checks(conn))
            counts = _table_counts(conn)
            result["tableCounts"] = counts
            expected = expected_tables
            if expected is None and isinstance(manifest.get("expectedTables"), list):
                expected = manifest["expectedTables"]
            if expected is not None:
                expected_set = {str(item) for item in expected}
                missing = sorted(expected_set - set(counts))
                checks.append(
                    BackupCheck(
                        "expected_tables",
                        not missing,
                        "齐全" if not missing else f"缺少表：{', '.join(missing)}",
                    )
                )
            expected_counts = manifest.get("tableCounts")
            if isinstance(expected_counts, dict):
                mismatch = {
                    key: {"expected": expected_counts.get(key), "actual": counts.get(key)}
                    for key in sorted(set(expected_counts) | set(counts))
                    if expected_counts.get(key) != counts.get(key)
                }
                checks.append(
                    BackupCheck(
                        "table_counts",
                        not mismatch,
                        "与清单一致" if not mismatch else f"{len(mismatch)} 张表行数不一致",
                    )
                )
            checks.append(BackupCheck("statements", statement_count > 0, f"执行 {statement_count} 条语句"))
        finally:
            conn.close()
    except (OSError, sqlite3.DatabaseError, EOFError, gzip.BadGzipFile, UnicodeDecodeError) as exc:
        checks.append(BackupCheck("import", False, str(exc)))
        result["error"] = str(exc)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    result["checks"] = [check.to_dict() for check in checks]
    result["ok"] = bool(checks) and all(check.ok for check in checks)
    if not result["ok"] and not result["error"]:
        result["error"] = "；".join(check.detail for check in checks if not check.ok)
    return result


def _extract_complete_statements(buffer: str) -> tuple[list[str], str]:
    """从缓冲区中切出所有完整 SQL 语句，返回 (语句列表, 剩余未完成文本)。

    逐字符检查分号并用 ``sqlite3.complete_statement`` 判定，能正确处理字符串 /
    注释里的分号；不会像 ``executescript`` 那样隐式提交，因而保留 dump 中的
    ``BEGIN`` / ``COMMIT`` 事务边界。
    """
    statements: list[str] = []
    start = 0
    for index, char in enumerate(buffer):
        if char != ";":
            continue
        candidate = buffer[start : index + 1]
        if sqlite3.complete_statement(candidate):
            statements.append(candidate)
            start = index + 1
    return statements, buffer[start:]


def _execute_sql_stream(source: Iterable[str], database: Path) -> int:
    """逐语句执行 SQL dump，避免把大文件一次性读入内存。"""
    conn = sqlite3.connect(database, timeout=30)
    buffer = ""
    executed = 0
    try:
        for line_number, line in enumerate(source, start=1):
            buffer += line
            statements, buffer = _extract_complete_statements(buffer)
            for statement in statements:
                try:
                    conn.execute(statement)
                except sqlite3.DatabaseError as exc:
                    raise sqlite3.DatabaseError(f"第 {line_number} 行附近执行失败：{exc}") from exc
                executed += 1
        if buffer.strip():
            try:
                conn.execute(buffer)
            except sqlite3.DatabaseError as exc:
                raise sqlite3.DatabaseError(f"文件末尾执行失败：{exc}") from exc
            executed += 1
        conn.commit()
    finally:
        conn.close()
    return executed


def finalize_d1_export(
    raw_path: Path | str,
    backup_dir: Path | str,
    *,
    label: str = "",
    keep: int = DEFAULT_RETENTION,
    max_total_bytes: int = 0,
    expected_tables: Optional[Iterable[str]] = None,
    database_name: str = "",
    remove_raw: bool = True,
    now: Optional[datetime] = None,
) -> BackupEntry:
    """校验 wrangler 原始导出并归档为 gzip + manifest。

    ``remove_raw=True``（默认）会在归档成功后删除调用方提供的临时导出文件。
    """
    raw = Path(raw_path)
    if not raw.is_file():
        raise BackupError(f"D1 导出文件不存在：{raw}")
    verification = verify_d1_dump(raw, expected_tables=expected_tables)
    if not verification["ok"]:
        raise BackupError(f"D1 导出校验失败：{verification['error']}")

    directory = _ensure_kind_dir(Path(backup_dir), D1_KIND)
    stamp = utc_stamp(now)
    safe_label = _safe_label(label)
    name = f"d1-{stamp}{('-' + safe_label) if safe_label else ''}{D1_SUFFIX}"
    final = _unique_path(directory / name)
    name = final.name
    tmp_gz = directory / f".tmp-{uuid.uuid4().hex}.gz"
    try:
        _gzip_file(raw, tmp_gz)
        os.chmod(tmp_gz, 0o600)
        os.replace(tmp_gz, final)
        size_bytes = final.stat().st_size
        sha256 = _sha256_file(final)
        manifest = {
            "kind": D1_KIND,
            "name": name,
            "createdAt": _iso(now),
            "database": database_name,
            "sizeBytes": size_bytes,
            "sha256": sha256,
            "tableCounts": verification["tableCounts"],
            "expectedTables": sorted({str(item) for item in expected_tables}) if expected_tables else [],
            "integrity": "ok",
            "label": safe_label,
        }
        _atomic_json(_manifest_path(final), manifest)
        prune_backups(
            backup_dir,
            keep=keep,
            max_total_bytes=max_total_bytes,
            protect={name},
        )
        if remove_raw:
            try:
                raw.unlink()
            except FileNotFoundError:
                pass
        return _entry_from_path(D1_KIND, final)
    finally:
        try:
            tmp_gz.unlink()
        except FileNotFoundError:
            pass


def sqlite_path_from_url(database_url: str) -> Optional[Path]:
    """从 SQLAlchemy SQLite URL 解析文件路径；非 SQLite / 内存库返回 None。"""
    if not database_url or not database_url.startswith("sqlite"):
        return None
    raw = database_url.split(":///", 1)[-1].split("?", 1)[0]
    if not raw or raw == ":memory:":
        return None
    return Path(raw).expanduser()


def _default_backup_dir() -> Path:
    return Path(os.environ.get("BACKUP_DIR", "./data/backups"))


def _default_keep() -> int:
    try:
        return max(1, int(os.environ.get("BACKUP_RETENTION_COUNT", DEFAULT_RETENTION)))
    except ValueError:
        return DEFAULT_RETENTION


def _default_max_total_mb() -> int:
    try:
        return max(0, int(os.environ.get("BACKUP_MAX_TOTAL_MB", DEFAULT_MAX_TOTAL_MB)))
    except ValueError:
        return DEFAULT_MAX_TOTAL_MB


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _cmd_create(args: argparse.Namespace) -> int:
    database = args.database or os.environ.get("DATABASE_URL", "")
    db_path = sqlite_path_from_url(database) if database.startswith("sqlite") else Path(database)
    if db_path is None:
        raise BackupError("仅支持 SQLite 数据库快照")
    entry = create_sqlite_snapshot(
        db_path,
        args.backup_dir,
        label=args.label,
        keep=args.keep,
        max_total_bytes=args.max_total_mb * 1024 * 1024,
    )
    _print_json(entry.to_dict())
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    entries = list_backups(args.backup_dir, args.kind)
    if args.json:
        _print_json([entry.to_dict() for entry in entries])
        return 0
    if not entries:
        print("（无备份）")
        return 0
    for entry in entries:
        print(f"{entry.created_at}\t{entry.kind}\t{entry.size_bytes}\t{entry.name}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    status = backup_status(
        args.backup_dir,
        retention=args.keep,
        max_total_mb=args.max_total_mb,
    )
    _print_json(status)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    entry = _resolve_entry(args.backup_dir, SQLITE_KIND, args.name)
    report = verify_sqlite_snapshot(entry.path)
    _print_json(report)
    return 0 if report["ok"] else 1


def _cmd_drill(args: argparse.Namespace) -> int:
    report = run_restore_drill(
        args.backup_dir,
        name=args.name,
        work_dir=args.work_dir,
        keep_work=args.keep_work,
    )
    _print_json(report)
    return 0 if report["ok"] else 1


def _cmd_restore(args: argparse.Namespace) -> int:
    entry = _resolve_entry(args.backup_dir, SQLITE_KIND, args.name)
    report = restore_sqlite_snapshot(
        entry.path,
        args.target,
        force=args.force,
        safety_dir=args.safety_dir,
    )
    _print_json(report)
    return 0


def _cmd_verify_d1(args: argparse.Namespace) -> int:
    if args.file:
        path = Path(args.file)
    else:
        path = _resolve_entry(args.backup_dir, D1_KIND, args.name).path
    expected = args.expected_table or None
    report = verify_d1_dump(path, expected_tables=expected)
    _print_json(report)
    return 0 if report["ok"] else 1


def _cmd_finalize_d1(args: argparse.Namespace) -> int:
    entry = finalize_d1_export(
        args.raw,
        args.backup_dir,
        label=args.label,
        keep=args.keep,
        max_total_bytes=args.max_total_mb * 1024 * 1024,
        expected_tables=args.expected_table or None,
        database_name=args.database_name,
    )
    _print_json(entry.to_dict())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.backup",
        description="OpenFactory 备份与恢复工具（SQLite 快照 / D1 导出校验 / 恢复演练）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--backup-dir", default=str(_default_backup_dir()), help="备份根目录")
        p.add_argument("--keep", type=int, default=_default_keep(), help="每类保留份数（默认 7）")
        p.add_argument(
            "--max-total-mb",
            type=int,
            default=_default_max_total_mb(),
            help="备份总量上限 MB（默认 3072，0 不限制）",
        )

    create = sub.add_parser("create", help="创建 SQLite 快照")
    add_common(create)
    create.add_argument("--database", default="", help="SQLite 文件路径；默认读 DATABASE_URL")
    create.add_argument("--label", default="", help="可选标签（进入文件名）")
    create.set_defaults(func=_cmd_create)

    listing = sub.add_parser("list", help="列出备份")
    add_common(listing)
    listing.add_argument("--kind", choices=KINDS, default=None)
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=_cmd_list)

    status = sub.add_parser("status", help="备份状态汇总")
    add_common(status)
    status.set_defaults(func=_cmd_status)

    verify = sub.add_parser("verify", help="校验 SQLite 快照")
    add_common(verify)
    verify.add_argument("--name", default="", help="快照文件名；缺省最新一份")
    verify.set_defaults(func=_cmd_verify)

    drill = sub.add_parser("drill", help="执行恢复演练")
    add_common(drill)
    drill.add_argument("--name", default="", help="快照文件名；缺省最新一份")
    drill.add_argument("--work-dir", default="", help="演练工作目录；缺省临时目录")
    drill.add_argument("--keep-work", action="store_true", help="保留演练临时库")
    drill.set_defaults(func=_cmd_drill)

    restore = sub.add_parser("restore", help="恢复 SQLite 快照（危险操作）")
    add_common(restore)
    restore.add_argument("--name", required=True, help="快照文件名")
    restore.add_argument("--target", required=True, help="目标 SQLite 文件")
    restore.add_argument("--force", action="store_true", help="目标存在时允许覆盖（会先生成安全快照）")
    restore.add_argument("--safety-dir", default="", help="pre-restore 快照目录")
    restore.set_defaults(func=_cmd_restore)

    verify_d1 = sub.add_parser("verify-d1", help="校验 D1 SQL 导出")
    add_common(verify_d1)
    verify_d1.add_argument("--file", default="", help="D1 导出文件路径（.sql / .sql.gz）")
    verify_d1.add_argument("--name", default="", help="备份目录中的文件名；--file 为空时使用")
    verify_d1.add_argument("--expected-table", action="append", default=[], help="期望存在的表（可重复）")
    verify_d1.set_defaults(func=_cmd_verify_d1)

    finalize = sub.add_parser("finalize-d1", help="校验并归档 wrangler 原始导出")
    add_common(finalize)
    finalize.add_argument("--raw", required=True, help="wrangler 导出的原始 .sql 文件")
    finalize.add_argument("--label", default="", help="可选标签")
    finalize.add_argument("--database-name", default="", help="D1 数据库名（写入清单）")
    finalize.add_argument("--expected-table", action="append", default=[], help="期望存在的表（可重复）")
    finalize.set_defaults(func=_cmd_finalize_d1)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BackupError as exc:
        print(f"[backup] 错误：{exc}", file=sys.stderr)
        return 1
    except (OSError, sqlite3.DatabaseError) as exc:
        print(f"[backup] 失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
