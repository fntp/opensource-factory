"""资源预算实测与判定（REQ-202610-0944 / M5-06）。

把 ``docs/planning/resource-plan.md`` 的 4G 内存 / 15G 磁盘预算变成可重复执行的
实测工具。只依赖标准库，部署机即使没有创建虚拟环境也能运行：

    cd vps
    python -m app.resource_budget check
    python -m app.resource_budget check --json
    python -m app.resource_budget check --no-services

判定口径：

- 内存：优先读 systemd ``MemoryCurrent``（openfactory-* 单元），不可用时回退 ``ps`` RSS；
  静态上限读 ``deploy/systemd/*.service`` 的 ``MemoryMax``，加模型峰值驻留；
- 磁盘：按 resource-plan §4 的科目统计 models / repo / data / logs / backups；
- 红线：内存 4096 MB、磁盘 15360 MB；预警：3584 MB / 13312 MB；
- 超限只输出优化建议，不自动修改配置或删除文件。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from app.services.model_budget import build_model_budget_report

DEFAULT_MEMORY_BUDGET_MB = 4096
DEFAULT_MEMORY_WARN_MB = 3584
DEFAULT_DISK_BUDGET_MB = 15360
DEFAULT_DISK_WARN_MB = 13312

# resource-plan §2 / §3：应用 2G + AI 推理 2G
APP_MEMORY_BUDGET_MB = 2048
AI_MEMORY_BUDGET_MB = 2048

# resource-plan §4：磁盘科目配额（MB），余量 3072 不单独统计
DISK_ALLOCATIONS_MB: dict[str, int] = {
    "models": 4096,
    "repo": 2048,
    "data": 2048,
    "logs": 1024,
    "backups": 3072,
}
DISK_SPARE_MB = 3072

SERVICE_UNITS: tuple[str, ...] = (
    "openfactory-api.service",
    "openfactory-worker.service",
    "openfactory-beat.service",
    "openfactory-redis.service",
)

# systemd 不可用时的 ps 回退匹配（尽量限定在本项目进程）
PROCESS_PATTERNS: tuple[str, ...] = (
    "uvicorn app.main:app",
    "celery -A app.tasks.celery_app",
    "redis-server",
)

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_OLLAMA_MODEL = "qwen2.5:1.5b-instruct-q4_K_M"
DEFAULT_EMBEDDING_QUANTIZATION = "int8"
DEFAULT_MODEL_BUDGET_MB = 2048

_LEVEL_ORDER = {"ok": 0, "unknown": 1, "warning": 2, "critical": 3}


@dataclass(frozen=True)
class ServiceUsage:
    """一个 systemd 单元（或回退进程）的内存占用。"""

    unit: str
    active: bool
    memory_mb: float
    memory_max_mb: float | None
    error: str = ""


@dataclass(frozen=True)
class DiskUsage:
    """一个磁盘预算科目的实测占用。"""

    category: str
    path: str
    size_mb: float
    budget_mb: int


@dataclass(frozen=True)
class Finding:
    """单项预算判定。"""

    name: str
    level: str  # ok / warning / critical / unknown
    measured_mb: float | None
    budget_mb: float
    detail: str


@dataclass(frozen=True)
class ResourceReport:
    """完整的资源预算报告。"""

    memory_budget_mb: int
    memory_warn_mb: int
    disk_budget_mb: int
    disk_warn_mb: int
    services: tuple[ServiceUsage, ...]
    disk: tuple[DiskUsage, ...]
    findings: tuple[Finding, ...]
    measured_memory_mb: float
    projected_memory_mb: float
    measured_disk_mb: float
    model_peak_mb: int
    model_verified: bool
    status: str
    summary: str
    suggestions: tuple[str, ...] = field(default_factory=tuple)


def parse_systemd_show(text: str) -> dict[str, str]:
    """解析 ``systemctl show -p Key=Value`` 输出。"""
    values: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _bytes_to_mb(value: str | None) -> float | None:
    """systemd 字节值转 MB；``infinity`` / 空 / 非数字返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"infinity", "[not set]", "n/a"}:
        return None
    try:
        number = int(float(text))
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return 0.0
    return round(number / (1024 * 1024), 1)


def _run_command(command: list[str], timeout: float = 5.0) -> str:
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "command failed").strip())
    return proc.stdout


Runner = Callable[[list[str]], Any]


def collect_service_usage(
    units: Sequence[str] = SERVICE_UNITS,
    *,
    runner: Runner | None = None,
) -> tuple[ServiceUsage, ...]:
    """读取 systemd 单元内存；单个单元失败不影响其它单元。"""
    run = runner or _run_command
    results: list[ServiceUsage] = []
    for unit in units:
        try:
            output = run(
                [
                    "systemctl",
                    "show",
                    unit,
                    "-p",
                    "Id",
                    "-p",
                    "ActiveState",
                    "-p",
                    "MemoryCurrent",
                    "-p",
                    "MemoryMax",
                ]
            )
            if hasattr(output, "stdout"):
                if getattr(output, "returncode", 0) != 0:
                    raise RuntimeError(getattr(output, "stderr", "") or "systemctl failed")
                output = output.stdout
            values = parse_systemd_show(str(output))
        except Exception as exc:  # noqa: BLE001 - 非 systemd 环境属于预期降级
            results.append(ServiceUsage(unit, False, 0.0, None, str(exc)))
            continue

        active = values.get("ActiveState") == "active"
        results.append(
            ServiceUsage(
                unit=values.get("Id", unit),
                active=active,
                memory_mb=_bytes_to_mb(values.get("MemoryCurrent")) or 0.0,
                memory_max_mb=_bytes_to_mb(values.get("MemoryMax")),
            )
        )
    return tuple(results)


def collect_process_memory(
    ps_text: str,
    patterns: Sequence[str] = PROCESS_PATTERNS,
) -> tuple[float, int]:
    """从 ``ps -eo pid=,rss=,args=`` 输出统计匹配进程的 RSS（MB）与数量。"""
    total_kb = 0
    matched = 0
    for raw in (ps_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        _pid, rss, args = parts
        try:
            rss_kb = int(rss)
        except ValueError:
            continue
        if any(pattern in args for pattern in patterns):
            total_kb += rss_kb
            matched += 1
    return round(total_kb / 1024, 1), matched


def directory_size_bytes(path: Path | str) -> int:
    """递归统计目录 / 文件的表观大小，不跟随符号链接。"""
    target = Path(path)
    if not target.exists():
        return 0
    if target.is_file():
        try:
            return target.stat().st_size
        except OSError:
            return 0

    total = 0
    stack = [target]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total


def _size_mb(path: Path | str) -> float:
    return round(directory_size_bytes(path) / (1024 * 1024), 1)


def default_model_dirs() -> tuple[Path, ...]:
    """模型缓存候选目录（存在才计入）。"""
    candidates: list[Path] = []
    env_dir = os.environ.get("OLLAMA_MODELS", "").strip()
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    home = Path.home()
    candidates.extend(
        [
            home / ".ollama" / "models",
            home / ".cache" / "huggingface" / "hub",
            Path("/usr/share/ollama/.ollama/models"),
        ]
    )
    unique: list[Path] = []
    for path in candidates:
        if path.is_dir() and path not in unique:
            unique.append(path)
    return tuple(unique)


def collect_disk_usage(
    home: Path | str,
    repo: Path | str,
    model_dirs: Iterable[Path | str] | None = None,
) -> tuple[DiskUsage, ...]:
    """按 resource-plan §4 的科目统计磁盘占用。"""
    home_path = Path(home)
    repo_path = Path(repo)
    models = tuple(Path(p) for p in (model_dirs if model_dirs is not None else default_model_dirs()))
    model_size = round(sum(_size_mb(path) for path in models), 1)

    rows = (
        DiskUsage("models", " / ".join(str(p) for p in models) or "（未发现模型目录）", model_size, DISK_ALLOCATIONS_MB["models"]),
        DiskUsage("repo", str(repo_path), _size_mb(repo_path), DISK_ALLOCATIONS_MB["repo"]),
        DiskUsage("data", str(home_path / "data"), _size_mb(home_path / "data"), DISK_ALLOCATIONS_MB["data"]),
        DiskUsage("logs", str(home_path / "logs"), _size_mb(home_path / "logs"), DISK_ALLOCATIONS_MB["logs"]),
        DiskUsage("backups", str(home_path / "backups"), _size_mb(home_path / "backups"), DISK_ALLOCATIONS_MB["backups"]),
    )
    return rows


def read_unit_caps(unit_dir: Path | str) -> dict[str, int]:
    """读取 systemd 单元模板中的 MemoryMax（MB）。"""
    caps: dict[str, int] = {}
    directory = Path(unit_dir)
    if not directory.is_dir():
        return caps
    for path in sorted(directory.glob("*.service")):
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^MemoryMax=(\d+)M$", text, re.MULTILINE)
        if match:
            caps[path.name] = int(match.group(1))
    return caps


def read_model_config(home: Path | str) -> dict[str, str]:
    """从运行目录 .env 读取模型配置；缺失时使用与 Settings 一致的默认值。"""
    values = {
        "EMBEDDING_MODEL": DEFAULT_EMBEDDING_MODEL,
        "EMBEDDING_QUANTIZATION": DEFAULT_EMBEDDING_QUANTIZATION,
        "OLLAMA_MODEL": DEFAULT_OLLAMA_MODEL,
        "MODEL_BUDGET_MB": str(DEFAULT_MODEL_BUDGET_MB),
    }
    env_path = Path(home) / ".env"
    if not env_path.is_file():
        return values
    try:
        from app.runtime import parse_env_file

        parsed = parse_env_file(env_path)
    except Exception:  # noqa: BLE001 - 配置损坏时退回默认值
        return values
    for key in values:
        if parsed.get(key):
            values[key] = parsed[key]
    return values


def _level_for(measured: float, warn: float, budget: float) -> str:
    if measured > budget:
        return "critical"
    if measured >= warn:
        return "warning"
    return "ok"


def _percent(measured: float, budget: float) -> str:
    if budget <= 0:
        return "—"
    return f"{measured / budget * 100:.1f}%"


def _worst(levels: Iterable[str]) -> str:
    return max(levels, key=lambda item: _LEVEL_ORDER.get(item, 0), default="ok")


def _suggestions_for(findings: Sequence[Finding]) -> tuple[str, ...]:
    suggestions: list[str] = []
    for finding in findings:
        if finding.level == "ok":
            continue
        if finding.name in {"memory_measured", "memory_projected", "memory_static_caps"}:
            suggestions.extend(
                [
                    "降低 Celery 并发：openfactory-worker.service 的 --concurrency 由 2 调整为 1。",
                    "确认 OLLAMA_KEEP_ALIVE=2m，摘要 / 向量化任务结束后及时卸载模型。",
                    "内存仍超限时，将 EMBEDDING_MODEL 切换为 BAAI/bge-small-zh-v1.5（约 300 MB）。",
                ]
            )
        elif finding.name == "disk_total":
            suggestions.extend(
                [
                    "按科目清理日志 / 归档 / 备份后复测；确认没有残留构建产物。",
                    "磁盘仍超限时，将模型目录迁移到独立磁盘并更新 OLLAMA_MODELS。",
                ]
            )
        elif finding.name.startswith("disk_"):
            category = finding.name.removeprefix("disk_")
            action = {
                "models": "删除未使用的 Ollama / HuggingFace 模型缓存，仅保留 bge-m3 int8 与 ≤2B LLM。",
                "repo": "清理 node_modules / .venv 缓存与构建产物，必要时重建虚拟环境。",
                "data": "执行 SQLite VACUUM，清理过期热榜归档（TRENDING_ARCHIVE_KEEP_DAYS）。",
                "logs": "清理 14 天前的日志（运行目录 logs/，或使用 M5-03 日志清理接口）。",
                "backups": "按保留策略删除旧备份（最近 7 份），见备份恢复手册。",
            }.get(category, "按该科目清理后复测。")
            suggestions.append(f"{category} 超出配额：{action}")
    # 去重并保持顺序
    return tuple(dict.fromkeys(suggestions))


def build_resource_report(
    services: Sequence[ServiceUsage],
    disk: Sequence[DiskUsage],
    *,
    memory_budget_mb: int = DEFAULT_MEMORY_BUDGET_MB,
    memory_warn_mb: int = DEFAULT_MEMORY_WARN_MB,
    disk_budget_mb: int = DEFAULT_DISK_BUDGET_MB,
    disk_warn_mb: int = DEFAULT_DISK_WARN_MB,
    model_peak_mb: int = 0,
    model_verified: bool = True,
    loaded_model_mb: float = 0.0,
    unit_caps: dict[str, int] | None = None,
) -> ResourceReport:
    """构建资源预算报告（纯函数，便于测试）。"""
    memory_budget = max(1, int(memory_budget_mb))
    memory_warn = min(max(0, int(memory_warn_mb)), memory_budget)
    disk_budget = max(1, int(disk_budget_mb))
    disk_warn = min(max(0, int(disk_warn_mb)), disk_budget)

    measured_app_mb = round(sum(item.memory_mb for item in services), 1)
    measured_memory = round(measured_app_mb + max(0.0, loaded_model_mb), 1)
    projected_memory = round(measured_app_mb + max(float(model_peak_mb), loaded_model_mb), 1)
    measured_disk = round(sum(item.size_mb for item in disk), 1)

    caps = dict(unit_caps or {})
    caps_total = sum(caps.values())

    findings: list[Finding] = []

    findings.append(
        Finding(
            "memory_measured",
            _level_for(measured_memory, memory_warn, memory_budget),
            measured_memory,
            memory_budget,
            f"实测进程 + 已加载模型 {measured_memory:.1f} MB / {memory_budget} MB（{_percent(measured_memory, memory_budget)}）",
        )
    )

    projected_level = _level_for(projected_memory, memory_warn, memory_budget)
    if not model_verified:
        projected_level = "unknown"
    findings.append(
        Finding(
            "memory_projected",
            projected_level,
            projected_memory,
            memory_budget,
            f"实测进程 + 模型峰值 {projected_memory:.1f} MB / {memory_budget} MB（{_percent(projected_memory, memory_budget)}）",
        )
    )

    if caps_total > 0:
        static_total = caps_total + int(model_peak_mb)
        findings.append(
            Finding(
                "memory_static_caps",
                _level_for(static_total, memory_warn, memory_budget),
                static_total,
                memory_budget,
                f"systemd 上限合计 {caps_total} MB + 模型峰值 {model_peak_mb} MB = {static_total} MB / {memory_budget} MB",
            )
        )
    else:
        findings.append(
            Finding(
                "memory_static_caps",
                "unknown",
                None,
                memory_budget,
                "未读取到 deploy/systemd/*.service 的 MemoryMax",
            )
        )

    if model_peak_mb > AI_MEMORY_BUDGET_MB:
        model_level = "critical"
    elif not model_verified:
        model_level = "unknown"
    else:
        model_level = "ok"
    findings.append(
        Finding(
            "model_budget",
            model_level,
            float(model_peak_mb),
            AI_MEMORY_BUDGET_MB,
            f"模型峰值驻留 {model_peak_mb} MB / {AI_MEMORY_BUDGET_MB} MB"
            + ("（未识别的模型，无法验证）" if not model_verified else ""),
        )
    )

    findings.append(
        Finding(
            "disk_total",
            _level_for(measured_disk, disk_warn, disk_budget),
            measured_disk,
            disk_budget,
            f"磁盘合计 {measured_disk:.1f} MB / {disk_budget} MB（{_percent(measured_disk, disk_budget)}）",
        )
    )

    for item in disk:
        level = "warning" if item.size_mb > item.budget_mb else "ok"
        findings.append(
            Finding(
                f"disk_{item.category}",
                level,
                item.size_mb,
                item.budget_mb,
                f"{item.category} {item.size_mb:.1f} MB / {item.budget_mb} MB",
            )
        )

    levels = [finding.level for finding in findings]
    if "critical" in levels:
        status = "FAIL"
    elif "warning" in levels:
        status = "WARN"
    elif "unknown" in levels:
        status = "UNKNOWN"
    else:
        status = "PASS"

    summary = (
        f"{status}：内存 {measured_memory:.1f} / {memory_budget} MB，"
        f"磁盘 {measured_disk:.1f} / {disk_budget} MB"
    )
    if status == "FAIL":
        summary += "；存在超限项，按建议优化后复测"
    elif status == "WARN":
        summary += "；接近红线，建议提前清理"
    elif status == "UNKNOWN":
        summary += "；部分数据不可读，需在部署机复测"

    return ResourceReport(
        memory_budget_mb=memory_budget,
        memory_warn_mb=memory_warn,
        disk_budget_mb=disk_budget,
        disk_warn_mb=disk_warn,
        services=tuple(services),
        disk=tuple(disk),
        findings=tuple(findings),
        measured_memory_mb=measured_memory,
        projected_memory_mb=projected_memory,
        measured_disk_mb=measured_disk,
        model_peak_mb=int(model_peak_mb),
        model_verified=bool(model_verified),
        status=status,
        summary=summary,
        suggestions=_suggestions_for(findings),
    )


def _format_finding(finding: Finding) -> str:
    marker = {"ok": "OK", "warning": "WARN", "critical": "FAIL", "unknown": "SKIP"}[finding.level]
    return f"[{marker}] {finding.name}: {finding.detail}"


def render_text(report: ResourceReport) -> str:
    lines = [
        f"OpenFactory 资源预算实测（内存 {report.memory_budget_mb} MB / 磁盘 {report.disk_budget_mb} MB）",
        "",
        "内存：",
    ]
    for service in report.services:
        state = "active" if service.active else "inactive"
        cap = f"，上限 {service.memory_max_mb:.0f} MB" if service.memory_max_mb else ""
        lines.append(f"  {service.unit}: {state}，{service.memory_mb:.1f} MB{cap}")
        if service.error:
            lines.append(f"    （读取失败：{service.error}）")
    lines.append("")
    lines.append("磁盘：")
    for item in report.disk:
        lines.append(f"  {item.category}: {item.size_mb:.1f} MB / {item.budget_mb} MB（{item.path}）")
    lines.append("")
    lines.append("判定：")
    lines.extend(f"  {_format_finding(finding)}" for finding in report.findings)
    lines.append("")
    lines.append(f"结论：{report.summary}")
    if report.suggestions:
        lines.append("优化建议：")
        lines.extend(f"  - {suggestion}" for suggestion in report.suggestions)
    return "\n".join(lines)


def _default_repo() -> Path:
    # vps/app/services/resource_budget.py -> 仓库根
    return Path(__file__).resolve().parents[3]


def _default_home() -> Path:
    return Path(os.environ.get("OPENFACTORY_HOME", "/opt/openfactory"))


def _load_model_budget(home: Path) -> tuple[int, bool, dict[str, str]]:
    config = read_model_config(home)
    try:
        budget_mb = int(config.get("MODEL_BUDGET_MB", DEFAULT_MODEL_BUDGET_MB))
    except ValueError:
        budget_mb = DEFAULT_MODEL_BUDGET_MB
    report = build_model_budget_report(
        embedding_model=config.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        ollama_model=config.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        embedding_quantization=config.get(
            "EMBEDDING_QUANTIZATION", DEFAULT_EMBEDDING_QUANTIZATION
        ),
        budget_mb=budget_mb,
    )
    return report.peak_resident_mb, report.verified, config


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.resource_budget",
        description="OpenFactory 资源预算实测（4G 内存 / 15G 磁盘红线）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="采集并判定当前资源占用")
    check.add_argument("--home", type=Path, default=_default_home(), help="运行目录")
    check.add_argument("--repo", type=Path, default=_default_repo(), help="代码检出目录")
    check.add_argument(
        "--models-dir",
        type=Path,
        action="append",
        default=None,
        help="模型目录（可重复；默认探测 Ollama / HuggingFace 缓存）",
    )
    check.add_argument("--memory-budget-mb", type=int, default=DEFAULT_MEMORY_BUDGET_MB)
    check.add_argument("--memory-warn-mb", type=int, default=DEFAULT_MEMORY_WARN_MB)
    check.add_argument("--disk-budget-mb", type=int, default=DEFAULT_DISK_BUDGET_MB)
    check.add_argument("--disk-warn-mb", type=int, default=DEFAULT_DISK_WARN_MB)
    check.add_argument("--no-services", action="store_true", help="不读取 systemd，仅用 ps 回退")
    check.add_argument("--json", action="store_true", help="以 JSON 输出")
    check.add_argument("--strict", action="store_true", help="WARN / UNKNOWN 也返回非零")

    args = parser.parse_args(argv)

    if args.command != "check":  # pragma: no cover - argparse 已限制
        return 2

    services = () if args.no_services else collect_service_usage()
    if not any(service.active and service.memory_mb > 0 for service in services):
        try:
            ps_text = _run_command(["ps", "-eo", "pid=,rss=,args="])
            process_mb, matched = collect_process_memory(ps_text)
        except Exception:  # noqa: BLE001 - 无 ps 时保持 0
            process_mb, matched = 0.0, 0
        if matched:
            services = tuple(services) + (
                ServiceUsage("process-fallback", True, process_mb, None, f"匹配 {matched} 个进程"),
            )

    disk = collect_disk_usage(args.home, args.repo, args.models_dir)
    unit_caps = read_unit_caps(Path(args.repo) / "deploy" / "systemd")
    model_peak_mb, model_verified, _config = _load_model_budget(Path(args.home))

    report = build_resource_report(
        services,
        disk,
        memory_budget_mb=args.memory_budget_mb,
        memory_warn_mb=args.memory_warn_mb,
        disk_budget_mb=args.disk_budget_mb,
        disk_warn_mb=args.disk_warn_mb,
        model_peak_mb=model_peak_mb,
        model_verified=model_verified,
        unit_caps=unit_caps,
    )

    if args.json:
        payload = asdict(report)
        payload["disk_allocations_mb"] = DISK_ALLOCATIONS_MB
        payload["disk_spare_mb"] = DISK_SPARE_MB
        payload["unit_caps_mb"] = unit_caps
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))

    if report.status == "FAIL":
        return 1
    if args.strict and report.status in {"WARN", "UNKNOWN"}:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    sys.exit(main())
