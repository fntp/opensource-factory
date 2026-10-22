"""监控与告警服务（REQ-202610-0941 / M5-03）。

职责：

- **资源采集**：/proc/meminfo、/proc/loadavg、systemd cgroup（openfactory-*.service）、
  进程 RSS 回退、运行目录磁盘占用、日志目录统计；
- **健康检查**：数据库 / 运行目录 / Redis / Edge / 模型预算；
- **阈值判定**：内存 3.5G 预警 / 4G 严重，磁盘 13G 预警 / 15G 严重，日志超预算预警；
- **告警闭环**：按 `kind + scope` 去重、冷却窗口内累加、条件恢复自动 resolved、人工确认；
- **日志与历史治理**：按保留天数清理日志文件与检查历史。

本模块测试不访问网络：Redis 只做 TCP 探测，Edge 探测在未配置 EDGE_BASE_URL 时跳过。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MonitoringAlert, MonitoringCheckRun

logger = logging.getLogger(__name__)

DEFAULT_HOME = Path(os.environ.get("OPENFACTORY_HOME", "/opt/openfactory"))
RUNTIME_SUBDIRS: tuple[str, ...] = ("data", "logs")
SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


def _utcnow() -> datetime:
    """统一使用无时区 UTC 时间（与模型默认值一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _mb(value_bytes: float) -> float:
    return round(float(value_bytes) / (1024 * 1024), 1)


# ── 采集：内存 / 负载 / 进程 ─────────────────────────────────────


def parse_meminfo(raw: str) -> dict[str, int]:
    """解析 /proc/meminfo，返回 kB 为单位的数值字典。"""
    values: dict[str, int] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            values[key.strip()] = int(parts[0])
        except ValueError:
            continue
    return values


def parse_loadavg(raw: str) -> dict[str, Any]:
    """解析 /proc/loadavg：1/5/15 分钟负载 + 运行 / 总进程数。"""
    parts = raw.strip().split()
    result: dict[str, Any] = {"one": 0.0, "five": 0.0, "fifteen": 0.0, "running": 0, "total": 0}
    try:
        if len(parts) >= 3:
            result["one"] = float(parts[0])
            result["five"] = float(parts[1])
            result["fifteen"] = float(parts[2])
        if len(parts) >= 4 and "/" in parts[3]:
            running, total = parts[3].split("/", 1)
            result["running"] = int(running)
            result["total"] = int(total)
    except (TypeError, ValueError):
        logger.debug("loadavg 解析失败: %s", raw)
    return result


def read_meminfo(path: Path | str = "/proc/meminfo") -> dict[str, int]:
    """读取 /proc/meminfo；不可读时返回空字典（不抛异常）。"""
    try:
        return parse_meminfo(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return {}


def read_loadavg(path: Path | str = "/proc/loadavg") -> dict[str, Any]:
    """读取 /proc/loadavg；不可读时返回零值。"""
    try:
        return parse_loadavg(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return parse_loadavg("")


def collect_cgroup_memory(
    root: Path | str = "/sys/fs/cgroup",
    prefix: str = "openfactory-",
) -> dict[str, Any]:
    """汇总 systemd cgroup v2 中 `openfactory-*.service` 的 memory.current。"""
    root_path = Path(root)
    total = 0
    services: list[dict[str, Any]] = []
    if not root_path.is_dir():
        return {"usedMb": 0.0, "services": services}
    patterns = (
        f"system.slice/{prefix}*.service/memory.current",
        f"{prefix}*.service/memory.current",
    )
    seen: set[Path] = set()
    for pattern in patterns:
        for path in root_path.glob(pattern):
            if path in seen:
                continue
            seen.add(path)
            try:
                value = int(path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
            total += value
            services.append({"name": path.parent.name, "usedMb": _mb(value)})
    return {"usedMb": _mb(total), "services": services}


def _read_process_rss_kb(pid: str, proc_root: Path) -> int:
    try:
        for line in (proc_root / pid / "status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return 0
    return 0


def _read_cmdline(pid: str, proc_root: Path) -> str:
    try:
        raw = (proc_root / pid / "cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def collect_process_memory(
    patterns: str,
    proc_root: Path | str = "/proc",
) -> dict[str, Any]:
    """按 cmdline 关键字汇总进程 RSS（cgroup 不可用时的回退口径）。

    `patterns` 逗号分隔；每项可用 `+` 连接多个关键字，需全部命中。
    """
    proc_path = Path(proc_root)
    specs = [item.strip().lower() for item in (patterns or "").split(",") if item.strip()]
    matched: list[dict[str, Any]] = []
    unique_pids: set[str] = set()
    total_kb = 0
    if not proc_path.is_dir() or not specs:
        return {"usedMb": 0.0, "processes": matched, "matchedPids": 0}

    cmdlines: dict[str, str] = {}
    try:
        pid_dirs = [entry.name for entry in proc_path.iterdir() if entry.name.isdigit()]
    except OSError:
        pid_dirs = []

    for pid in pid_dirs:
        cmdline = _read_cmdline(pid, proc_path)
        if cmdline:
            cmdlines[pid] = cmdline.lower()

    for spec in specs:
        tokens = [token for token in spec.split("+") if token]
        if not tokens:
            continue
        pids = [pid for pid, cmdline in cmdlines.items() if all(token in cmdline for token in tokens)]
        rss_kb = sum(_read_process_rss_kb(pid, proc_path) for pid in pids)
        matched.append(
            {
                "pattern": spec,
                "count": len(pids),
                "rssMb": _mb(rss_kb * 1024),
                "pids": pids[:20],
            }
        )
        for pid in pids:
            if pid not in unique_pids:
                unique_pids.add(pid)
                total_kb += _read_process_rss_kb(pid, proc_path)

    return {
        "usedMb": _mb(total_kb * 1024),
        "processes": matched,
        "matchedPids": len(unique_pids),
    }


# ── 采集：磁盘 / 日志 ───────────────────────────────────────────


def directory_size_bytes(path: Path | str) -> int:
    """递归统计目录内普通文件大小（不跟随符号链接，权限错误跳过）。"""
    root = Path(path)
    if not root.is_dir():
        return 0
    total = 0
    for current, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            file_path = Path(current) / name
            try:
                if file_path.is_symlink():
                    continue
                total += file_path.stat().st_size
            except OSError:
                continue
    return total


def collect_log_stats(
    log_dir: Path | str,
    *,
    budget_mb: int,
    retention_days: int,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """统计日志目录文件数量 / 占用 / 超期文件。"""
    root = Path(log_dir)
    now = now or _utcnow()
    cutoff = now - timedelta(days=max(0, retention_days))
    files: list[dict[str, Any]] = []
    total_bytes = 0
    old_files = 0
    if root.is_dir():
        for current, _dirs, names in os.walk(root, followlinks=False):
            for name in names:
                path = Path(current) / name
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    stat = path.stat()
                except OSError:
                    continue
                total_bytes += stat.st_size
                modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(tzinfo=None)
                expired = modified < cutoff
                if expired:
                    old_files += 1
                files.append(
                    {
                        "name": str(path.relative_to(root)),
                        "sizeMb": _mb(stat.st_size),
                        "modifiedAt": modified.isoformat(),
                        "expired": expired,
                    }
                )
    files.sort(key=lambda item: item["sizeMb"], reverse=True)
    return {
        "path": str(root),
        "exists": root.is_dir(),
        "files": len(files),
        "totalMb": _mb(total_bytes),
        "budgetMb": int(budget_mb),
        "retentionDays": int(retention_days),
        "oldFiles": old_files,
        "items": files[:50],
    }


def logs_status(settings: Any | None = None) -> dict[str, Any]:
    """当前日志目录统计（供 `/api/monitoring/logs` 使用）。"""
    cfg = settings or get_settings()
    log_dir = resolve_log_dir(cfg, resolve_home(cfg))
    if log_dir is None:
        return {
            "path": "",
            "exists": False,
            "files": 0,
            "totalMb": 0.0,
            "budgetMb": int(getattr(cfg, "MONITOR_LOG_BUDGET_MB", 1024) or 1024),
            "retentionDays": int(getattr(cfg, "MONITOR_LOG_RETENTION_DAYS", 14) or 14),
            "oldFiles": 0,
            "items": [],
        }
    return collect_log_stats(
        log_dir,
        budget_mb=int(getattr(cfg, "MONITOR_LOG_BUDGET_MB", 1024) or 1024),
        retention_days=int(getattr(cfg, "MONITOR_LOG_RETENTION_DAYS", 14) or 14),
    )


def cleanup_log_files(
    log_dir: Path | str,
    *,
    retention_days: int,
    now: Optional[datetime] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """删除超过保留天数的日志文件；`dry_run` 只统计不删除。"""
    root = Path(log_dir)
    now = now or _utcnow()
    cutoff = now - timedelta(days=max(0, retention_days))
    deleted = 0
    freed_bytes = 0
    kept = 0
    if root.is_dir():
        for current, _dirs, names in os.walk(root, followlinks=False):
            for name in names:
                path = Path(current) / name
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    stat = path.stat()
                except OSError:
                    continue
                modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(tzinfo=None)
                if modified >= cutoff:
                    kept += 1
                    continue
                deleted += 1
                freed_bytes += stat.st_size
                if not dry_run:
                    try:
                        path.unlink()
                    except OSError:
                        deleted -= 1
                        freed_bytes -= stat.st_size
                        logger.warning("日志文件删除失败: %s", path, exc_info=True)
    return {
        "status": "dry_run" if dry_run else "ok",
        "path": str(root),
        "retentionDays": int(retention_days),
        "cutoff": cutoff.isoformat(),
        "deleted": deleted,
        "kept": kept,
        "freedMb": _mb(freed_bytes),
    }


# ── 资源快照 ────────────────────────────────────────────────────


def resolve_home(settings: Any | None = None) -> Optional[Path]:
    """解析运行目录：MONITOR_HOME → OPENFACTORY_HOME → 已存在的 /opt/openfactory。"""
    cfg = settings or get_settings()
    configured = str(getattr(cfg, "MONITOR_HOME", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    env_home = os.environ.get("OPENFACTORY_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser()
    if DEFAULT_HOME.is_dir():
        return DEFAULT_HOME
    return None


def resolve_log_dir(settings: Any | None = None, home: Optional[Path] = None) -> Optional[Path]:
    """日志目录：LOG_DIR 优先，其次运行目录 logs/。"""
    cfg = settings or get_settings()
    configured = str(getattr(cfg, "LOG_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    if home is not None:
        return home / "logs"
    return None


def collect_resources(settings: Any | None = None, home: Optional[Path] = None) -> dict[str, Any]:
    """采集一轮资源快照（内存 / 磁盘 / 负载 / 日志）。"""
    cfg = settings or get_settings()
    home = home if home is not None else resolve_home(cfg)

    meminfo = read_meminfo()
    total_mb = _mb(meminfo.get("MemTotal", 0) * 1024)
    available_mb = _mb(meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) * 1024)

    cgroup = collect_cgroup_memory()
    process = collect_process_memory(str(getattr(cfg, "MONITOR_PROCESS_PATTERNS", "") or ""))
    if cgroup["usedMb"] > 0:
        used_mb, source = cgroup["usedMb"], "cgroup"
    elif process["usedMb"] > 0:
        used_mb, source = process["usedMb"], "process"
    else:
        used_mb, source = max(0.0, round(total_mb - available_mb, 1)), "system"

    memory_budget = int(getattr(cfg, "MONITOR_MEMORY_BUDGET_MB", 4096) or 4096)
    memory = {
        "usedMb": used_mb,
        "budgetMb": memory_budget,
        "warnMb": int(getattr(cfg, "MONITOR_MEMORY_WARN_MB", 3584) or 3584),
        "criticalMb": int(getattr(cfg, "MONITOR_MEMORY_CRITICAL_MB", 4096) or 4096),
        "percent": round(used_mb / memory_budget * 100, 1) if memory_budget else 0.0,
        "source": source,
        "systemTotalMb": total_mb,
        "systemAvailableMb": available_mb,
        "cgroupServices": cgroup["services"],
        "processes": process["processes"],
    }

    disk_budget = int(getattr(cfg, "MONITOR_DISK_BUDGET_MB", 15360) or 15360)
    disk_used = _mb(directory_size_bytes(home)) if home else 0.0
    filesystem_total = filesystem_free = 0.0
    if home and home.exists():
        try:
            usage = shutil.disk_usage(home)
            filesystem_total = _mb(usage.total)
            filesystem_free = _mb(usage.free)
        except OSError:
            pass
    disk = {
        "usedMb": disk_used,
        "budgetMb": disk_budget,
        "warnMb": int(getattr(cfg, "MONITOR_DISK_WARN_MB", 13312) or 13312),
        "criticalMb": int(getattr(cfg, "MONITOR_DISK_CRITICAL_MB", 15360) or 15360),
        "percent": round(disk_used / disk_budget * 100, 1) if disk_budget else 0.0,
        "path": str(home) if home else "",
        "filesystemTotalMb": filesystem_total,
        "filesystemFreeMb": filesystem_free,
    }

    log_dir = resolve_log_dir(cfg, home)
    logs = (
        collect_log_stats(
            log_dir,
            budget_mb=int(getattr(cfg, "MONITOR_LOG_BUDGET_MB", 1024) or 1024),
            retention_days=int(getattr(cfg, "MONITOR_LOG_RETENTION_DAYS", 14) or 14),
        )
        if log_dir is not None
        else {"path": "", "exists": False, "files": 0, "totalMb": 0.0, "budgetMb": 0, "retentionDays": 0, "oldFiles": 0, "items": []}
    )

    return {
        "memory": memory,
        "disk": disk,
        "load": read_loadavg(),
        "logs": logs,
        "collectedAt": _utcnow().isoformat(),
    }


# ── 健康检查 ────────────────────────────────────────────────────


def _check(name: str, ok: bool, detail: str, severity: str = "info") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "severity": severity if not ok else "info"}


def check_database(db: Session) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        return _check("database", True, "数据库可读写")
    except Exception as exc:  # noqa: BLE001 - 健康检查必须返回结构化结果
        return _check("database", False, f"数据库不可用：{type(exc).__name__}: {exc}"[:300], "critical")


def check_runtime_home(home: Optional[Path]) -> dict[str, Any]:
    if home is None:
        return _check("runtime_home", True, "未配置运行目录（开发模式），跳过")
    if not home.exists():
        return _check("runtime_home", False, f"运行目录不存在：{home}", "warning")
    if not home.is_dir():
        return _check("runtime_home", False, f"运行目录不是目录：{home}", "warning")
    missing = [name for name in RUNTIME_SUBDIRS if not (home / name).is_dir()]
    if missing:
        return _check("runtime_home", False, f"运行目录缺少：{', '.join(missing)}", "warning")
    if not os.access(home / "data", os.W_OK):
        return _check("runtime_home", False, f"数据目录不可写：{home / 'data'}", "warning")
    return _check("runtime_home", True, str(home))


def check_redis(redis_url: str, timeout: float = 2.0) -> dict[str, Any]:
    url = (redis_url or "").strip()
    if not url:
        return _check("redis", True, "未配置 REDIS_URL，跳过")
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=max(0.1, timeout)):
            return _check("redis", True, f"{host}:{port} 可连接")
    except OSError as exc:
        return _check("redis", False, f"{host}:{port} 不可连接：{exc}"[:300], "warning")


def check_edge(base_url: str, timeout: float = 3.0) -> dict[str, Any]:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return _check("edge", True, "未配置 EDGE_BASE_URL，跳过")
    try:
        response = httpx.get(f"{base}/healthz", timeout=max(0.2, timeout))
        if 200 <= response.status_code < 300:
            return _check("edge", True, f"{base} 健康")
        return _check("edge", False, f"{base} 返回 HTTP {response.status_code}", "warning")
    except Exception as exc:  # noqa: BLE001 - 边缘不可达属于预期告警
        return _check("edge", False, f"{base} 不可达：{type(exc).__name__}: {exc}"[:300], "warning")


def check_model_budget(settings: Any | None = None) -> dict[str, Any]:
    from app.services.model_budget import build_model_budget_report

    cfg = settings or get_settings()
    try:
        report = build_model_budget_report(
            embedding_model=str(getattr(cfg, "EMBEDDING_MODEL", "") or ""),
            ollama_model=str(getattr(cfg, "OLLAMA_MODEL", "") or ""),
            embedding_quantization=str(getattr(cfg, "EMBEDDING_QUANTIZATION", "int8") or "int8"),
            budget_mb=int(getattr(cfg, "MODEL_BUDGET_MB", 2048) or 2048),
        )
    except Exception as exc:  # noqa: BLE001 - 配置异常不应中断监控
        return _check("model_budget", False, f"预算校验失败：{exc}"[:300], "warning")
    known_over = any(item.resident_mb is not None and not item.within_budget for item in report.items)
    if known_over:
        return _check("model_budget", False, report.summary, "warning")
    return _check("model_budget", True, report.summary if report.verified else "未识别的模型，跳过预算校验")


def run_health_checks(
    db: Session,
    settings: Any | None = None,
    home: Optional[Path] = None,
) -> list[dict[str, Any]]:
    cfg = settings or get_settings()
    return [
        check_database(db),
        check_runtime_home(home if home is not None else resolve_home(cfg)),
        check_redis(str(getattr(cfg, "REDIS_URL", "") or ""), float(getattr(cfg, "MONITOR_REDIS_TIMEOUT_SECONDS", 2.0) or 2.0)),
        check_edge(str(getattr(cfg, "EDGE_BASE_URL", "") or ""), float(getattr(cfg, "MONITOR_EDGE_TIMEOUT_SECONDS", 3.0) or 3.0)),
        check_model_budget(cfg),
    ]


# ── 阈值判定与告警 ──────────────────────────────────────────────


def evaluate_findings(
    resources: dict[str, Any],
    checks: Iterable[dict[str, Any]],
    settings: Any | None = None,
) -> list[dict[str, Any]]:
    """把资源快照与健康检查转换为告警判定（不写库）。"""
    cfg = settings or get_settings()
    findings: list[dict[str, Any]] = []
    memory = resources.get("memory", {})
    disk = resources.get("disk", {})
    logs = resources.get("logs", {})

    def add(kind: str, scope: str, severity: str, message: str, details: dict[str, Any]) -> None:
        findings.append(
            {
                "kind": kind,
                "scope": scope,
                "severity": severity,
                "message": message,
                "details": details,
                "dedupeKey": f"monitoring:{kind}:{scope}",
            }
        )

    used_mb = float(memory.get("usedMb") or 0)
    critical_mb = int(memory.get("criticalMb") or 0)
    warn_mb = int(memory.get("warnMb") or 0)
    if critical_mb and used_mb >= critical_mb:
        add(
            "memory",
            "project",
            "critical",
            f"内存占用 {used_mb:.0f} MB 已达 {critical_mb / 1024:.1f}G 红线（来源：{memory.get('source')}）",
            {"usedMb": used_mb, "criticalMb": critical_mb, "budgetMb": memory.get("budgetMb"), "source": memory.get("source")},
        )
    elif warn_mb and used_mb >= warn_mb:
        add(
            "memory",
            "project",
            "warning",
            f"内存占用 {used_mb:.0f} MB 超过 {warn_mb / 1024:.1f}G 预警线",
            {"usedMb": used_mb, "warnMb": warn_mb, "budgetMb": memory.get("budgetMb"), "source": memory.get("source")},
        )

    disk_used = float(disk.get("usedMb") or 0)
    disk_critical = int(disk.get("criticalMb") or 0)
    disk_warn = int(disk.get("warnMb") or 0)
    if disk_critical and disk_used >= disk_critical:
        add(
            "disk",
            "runtime",
            "critical",
            f"运行目录占用 {disk_used:.0f} MB 已达 {disk_critical / 1024:.1f}G 红线",
            {"usedMb": disk_used, "criticalMb": disk_critical, "path": disk.get("path")},
        )
    elif disk_warn and disk_used >= disk_warn:
        add(
            "disk",
            "runtime",
            "warning",
            f"运行目录占用 {disk_used:.0f} MB 超过 {disk_warn / 1024:.1f}G 预警线",
            {"usedMb": disk_used, "warnMb": disk_warn, "path": disk.get("path")},
        )

    log_total = float(logs.get("totalMb") or 0)
    log_budget = int(logs.get("budgetMb") or 0)
    if log_budget and log_total >= log_budget:
        add(
            "logs",
            "runtime",
            "warning",
            f"日志占用 {log_total:.0f} MB 超过预算 {log_budget} MB",
            {"totalMb": log_total, "budgetMb": log_budget, "path": logs.get("path")},
        )

    for check in checks:
        if check.get("ok"):
            continue
        severity = check.get("severity") or "warning"
        name = str(check.get("name") or "unknown")
        add(
            "service",
            name,
            severity,
            f"{name} 检查失败：{check.get('detail')}",
            {"check": name, "detail": check.get("detail")},
        )
    return findings


def record_alert(
    db: Session,
    finding: dict[str, Any],
    *,
    cooldown_minutes: int = 60,
    now: Optional[datetime] = None,
) -> tuple[MonitoringAlert, bool]:
    """写入或合并告警，返回 `(alert, created)`。

    同一 `dedupe_key` 始终复用未关闭的告警；冷却窗口内累加次数，
    超出窗口视为新事件（次数重置为 1），避免同一故障留下多条 open 记录。
    """
    now = now or _utcnow()
    dedupe_key = str(finding["dedupeKey"])
    latest = (
        db.execute(
            select(MonitoringAlert)
            .where(
                MonitoringAlert.dedupe_key == dedupe_key,
                MonitoringAlert.status.in_(("open", "acknowledged")),
            )
            .order_by(MonitoringAlert.last_seen_at.desc())
        )
        .scalars()
        .first()
    )
    details = json.dumps(finding.get("details") or {}, ensure_ascii=False, default=str)

    if latest is not None:
        within = latest.last_seen_at >= now - timedelta(minutes=max(0, cooldown_minutes))
        latest.occurrences = latest.occurrences + 1 if within else 1
        if not within:
            latest.first_seen_at = now
        latest.last_seen_at = now
        latest.message = str(finding.get("message") or "")[:2000]
        latest.details = details
        latest.severity = str(finding.get("severity") or "warning")
        return latest, False

    alert = MonitoringAlert(
        id=uuid4().hex,
        kind=str(finding.get("kind") or "service")[:32],
        severity=str(finding.get("severity") or "warning"),
        message=str(finding.get("message") or "")[:2000],
        details=details,
        dedupe_key=dedupe_key,
        status="open",
        occurrences=1,
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(alert)
    return alert, True


def resolve_stale_alerts(
    db: Session,
    active_keys: Iterable[str],
    *,
    now: Optional[datetime] = None,
) -> int:
    """把不再命中的 open / acknowledged 告警置为 resolved。"""
    active = set(active_keys)
    now = now or _utcnow()
    rows = (
        db.execute(
            select(MonitoringAlert).where(MonitoringAlert.status.in_(("open", "acknowledged")))
        )
        .scalars()
        .all()
    )
    resolved = 0
    for alert in rows:
        if alert.dedupe_key in active:
            continue
        alert.status = "resolved"
        alert.resolved_at = now
        resolved += 1
    return resolved


def notify_monitoring_webhook(alert: MonitoringAlert, url: Optional[str] = None) -> bool:
    """best-effort webhook；未配置或失败只记日志。"""
    target = (url if url is not None else get_settings().MONITOR_ALERT_WEBHOOK_URL).strip()
    if not target:
        return False
    payload = {
        "source": "openfactory",
        "type": "monitoring_alert",
        "alert": serialize_alert(alert),
    }
    try:
        response = httpx.post(target, json=payload, timeout=5.0)
        if 200 <= response.status_code < 300:
            return True
        logger.warning("监控告警 webhook 返回 %s", response.status_code)
    except Exception as exc:  # noqa: BLE001 - 通知失败不影响检查
        logger.warning("监控告警 webhook 发送失败: %s", exc)
    return False


def serialize_alert(alert: MonitoringAlert) -> dict[str, Any]:
    try:
        details = json.loads(alert.details or "{}")
    except (TypeError, ValueError):
        details = {}
    return {
        "id": alert.id,
        "kind": alert.kind,
        "severity": alert.severity,
        "message": alert.message,
        "details": details,
        "dedupeKey": alert.dedupe_key,
        "status": alert.status,
        "occurrences": alert.occurrences,
        "firstSeenAt": _iso(alert.first_seen_at),
        "lastSeenAt": _iso(alert.last_seen_at),
        "acknowledgedAt": _iso(alert.acknowledged_at),
        "resolvedAt": _iso(alert.resolved_at),
    }


def serialize_run(run: MonitoringCheckRun) -> dict[str, Any]:
    def load(raw: str, fallback: Any) -> Any:
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return fallback

    return {
        "id": run.id,
        "status": run.status,
        "checks": load(run.checks, []),
        "resources": load(run.resources, {}),
        "findings": load(run.findings, []),
        "createdAt": _iso(run.created_at),
    }


def _overall_status(findings: Iterable[dict[str, Any]], checks: Iterable[dict[str, Any]]) -> str:
    severities = [str(item.get("severity") or "info") for item in findings]
    severities += [str(item.get("severity") or "info") for item in checks if not item.get("ok")]
    if any(item == "critical" for item in severities):
        return "critical"
    if any(item == "warning" for item in severities):
        return "warning"
    return "ok"


def list_alerts(
    db: Session,
    *,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[MonitoringAlert]:
    query = select(MonitoringAlert).order_by(MonitoringAlert.last_seen_at.desc()).limit(max(1, min(limit, 200)))
    if status:
        query = query.where(MonitoringAlert.status == status)
    return list(db.execute(query).scalars().all())


def acknowledge_alert(db: Session, alert_id: str, *, now: Optional[datetime] = None) -> Optional[MonitoringAlert]:
    """确认告警（幂等）：open → acknowledged；resolved 保持不变。"""
    alert = db.get(MonitoringAlert, alert_id)
    if alert is None:
        return None
    if alert.status == "open":
        alert.status = "acknowledged"
        alert.acknowledged_at = now or _utcnow()
        db.commit()
    return alert


def latest_run(db: Session) -> Optional[MonitoringCheckRun]:
    return (
        db.execute(select(MonitoringCheckRun).order_by(MonitoringCheckRun.created_at.desc()).limit(1))
        .scalars()
        .first()
    )


def list_runs(db: Session, limit: int = 20) -> list[MonitoringCheckRun]:
    return list(
        db.execute(
            select(MonitoringCheckRun)
            .order_by(MonitoringCheckRun.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
        .scalars()
        .all()
    )


# ── 检查执行 ────────────────────────────────────────────────────


def build_status(db: Session, settings: Any | None = None, home: Optional[Path] = None) -> dict[str, Any]:
    """实时状态（不写库）：健康检查 + 资源 + 阈值 + 当前告警 + 最近运行。"""
    cfg = settings or get_settings()
    home = home if home is not None else resolve_home(cfg)
    checks = run_health_checks(db, cfg, home)
    resources = collect_resources(cfg, home)
    findings = evaluate_findings(resources, checks, cfg)
    return {
        "status": _overall_status(findings, checks),
        "checkedAt": _utcnow().isoformat(),
        "checks": checks,
        "resources": resources,
        "findings": findings,
        "thresholds": {
            "memoryWarnMb": resources["memory"]["warnMb"],
            "memoryCriticalMb": resources["memory"]["criticalMb"],
            "diskWarnMb": resources["disk"]["warnMb"],
            "diskCriticalMb": resources["disk"]["criticalMb"],
            "logBudgetMb": resources["logs"].get("budgetMb", 0),
        },
        "alerts": [serialize_alert(item) for item in list_alerts(db, status=None, limit=50)],
        "latestRun": serialize_run(run) if (run := latest_run(db)) else None,
    }


def run_monitoring_check(
    db: Session,
    settings: Any | None = None,
    home: Optional[Path] = None,
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """执行一轮检查：采集 → 判定 → 告警落库 / 恢复 → 保存历史。"""
    cfg = settings or get_settings()
    now = now or _utcnow()
    home = home if home is not None else resolve_home(cfg)
    checks = run_health_checks(db, cfg, home)
    resources = collect_resources(cfg, home)
    findings = evaluate_findings(resources, checks, cfg)
    status = _overall_status(findings, checks)

    created_alerts: list[MonitoringAlert] = []
    deduplicated = 0
    for finding in findings:
        alert, created = record_alert(
            db,
            finding,
            cooldown_minutes=int(getattr(cfg, "MONITOR_ALERT_COOLDOWN_MINUTES", 60) or 0),
            now=now,
        )
        if created:
            created_alerts.append(alert)
        else:
            deduplicated += 1
    resolved = resolve_stale_alerts(db, {item["dedupeKey"] for item in findings}, now=now)

    run = MonitoringCheckRun(
        id=uuid4().hex,
        status=status,
        checks=json.dumps(checks, ensure_ascii=False, default=str),
        resources=json.dumps(resources, ensure_ascii=False, default=str),
        findings=json.dumps(findings, ensure_ascii=False, default=str),
        created_at=now,
    )
    db.add(run)
    db.commit()

    webhook_url = str(getattr(cfg, "MONITOR_ALERT_WEBHOOK_URL", "") or "")
    for alert in created_alerts:
        notify_monitoring_webhook(alert, webhook_url)

    return {
        "id": run.id,
        "status": status,
        "checkedAt": now.isoformat(),
        "checks": checks,
        "resources": resources,
        "findings": findings,
        "alerts": {
            "created": len(created_alerts),
            "deduplicated": deduplicated,
            "resolved": resolved,
        },
        "run": serialize_run(run),
    }


def cleanup_monitoring_history(
    db: Session,
    retention_days: int,
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """清理超过保留天数的检查历史（0 = 不清理）。"""
    if retention_days <= 0:
        return {"status": "disabled", "deleted": 0, "cutoff": None}
    now = now or _utcnow()
    cutoff = now - timedelta(days=retention_days)
    rows = (
        db.execute(select(MonitoringCheckRun).where(MonitoringCheckRun.created_at < cutoff))
        .scalars()
        .all()
    )
    for row in rows:
        db.delete(row)
    db.commit()
    return {"status": "ok", "deleted": len(rows), "cutoff": cutoff.isoformat()}
