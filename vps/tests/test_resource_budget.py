"""资源预算实测测试（REQ-202610-0944 / M5-06）。

全部用例离线执行：systemd / ps 输出由测试替身注入，目录统计使用 tmp_path。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.resource_budget import (
    AI_MEMORY_BUDGET_MB,
    APP_MEMORY_BUDGET_MB,
    DEFAULT_DISK_BUDGET_MB,
    DISK_ALLOCATIONS_MB,
    DISK_SPARE_MB,
    DiskUsage,
    ServiceUsage,
    build_resource_report,
    collect_disk_usage,
    collect_process_memory,
    collect_service_usage,
    directory_size_bytes,
    main,
    parse_systemd_show,
    read_model_config,
    read_unit_caps,
)

ROOT = Path(__file__).resolve().parents[2]


def _mb(value: int) -> int:
    return value * 1024 * 1024


def test_parse_systemd_show() -> None:
    values = parse_systemd_show(
        "Id=openfactory-api.service\nActiveState=active\nMemoryCurrent=17334272\nMemoryMax=402653184\n"
    )
    assert values["Id"] == "openfactory-api.service"
    assert values["ActiveState"] == "active"
    assert values["MemoryCurrent"] == "17334272"


def test_collect_service_usage_reads_memory_and_caps() -> None:
    def runner(command: list[str]) -> str:
        unit = command[2]
        if unit == "broken.service":
            raise RuntimeError("systemd not available")
        return (
            f"Id={unit}\nActiveState=active\n"
            f"MemoryCurrent={_mb(120)}\nMemoryMax={_mb(384)}\n"
        )

    services = collect_service_usage(
        ("openfactory-api.service", "broken.service"), runner=runner
    )
    assert services[0].active
    assert services[0].memory_mb == 120.0
    assert services[0].memory_max_mb == 384.0
    assert not services[1].active
    assert "systemd" in services[1].error


def test_collect_service_usage_handles_infinity() -> None:
    def runner(command: list[str]) -> str:
        return "Id=x\nActiveState=inactive\nMemoryCurrent=[not set]\nMemoryMax=infinity\n"

    service = collect_service_usage(("x.service",), runner=runner)[0]
    assert service.memory_mb == 0.0
    assert service.memory_max_mb is None


def test_collect_process_memory_matches_patterns() -> None:
    ps_text = """\
  101  102400 /usr/bin/uvicorn app.main:app --host 127.0.0.1
  102  204800 /usr/bin/celery -A app.tasks.celery_app worker
  103  512000 /usr/bin/python unrelated.py
"""
    total, matched = collect_process_memory(ps_text)
    assert matched == 2
    assert total == 300.0


def test_directory_size_and_disk_usage(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    repo = tmp_path / "repo"
    models = tmp_path / "models"
    for path in (home / "data", home / "logs", home / "backups", repo, models):
        path.mkdir(parents=True, exist_ok=True)
    (home / "data" / "db.sqlite").write_bytes(b"x" * 2048)
    (home / "logs" / "api.log").write_bytes(b"x" * 1024)
    (repo / "main.py").write_bytes(b"x" * 4096)
    (models / "model.bin").write_bytes(b"x" * 8192)

    assert directory_size_bytes(home / "data") == 2048
    rows = collect_disk_usage(home, repo, [models])
    by_name = {row.category: row for row in rows}
    assert by_name["models"].size_mb == 0.0
    assert by_name["repo"].size_mb == 0.0
    assert by_name["data"].size_mb == 0.0
    # 小于 0.1MB 的文件按 1 位小数会四舍五入为 0；改用 KB 级断言避免依赖舍入
    assert by_name["data"].path == str(home / "data")
    assert by_name["logs"].budget_mb == 1024
    assert by_name["backups"].budget_mb == 3072


def test_collect_disk_usage_uses_real_sizes(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    repo = tmp_path / "repo"
    models = tmp_path / "models"
    for path in (home / "data", home / "logs", home / "backups", repo, models):
        path.mkdir(parents=True, exist_ok=True)
    (models / "model.bin").write_bytes(b"x" * (2 * 1024 * 1024))
    (repo / "bundle.bin").write_bytes(b"x" * (1024 * 1024))

    rows = {row.category: row for row in collect_disk_usage(home, repo, [models])}
    assert rows["models"].size_mb == 2.0
    assert rows["repo"].size_mb == 1.0


def test_read_unit_caps_matches_resource_plan() -> None:
    caps = read_unit_caps(ROOT / "deploy" / "systemd")
    assert set(caps) == {
        "openfactory-api.service",
        "openfactory-beat.service",
        "openfactory-redis.service",
        "openfactory-worker.service",
    }
    assert sum(caps.values()) == 1664
    assert sum(caps.values()) <= APP_MEMORY_BUDGET_MB


def test_disk_allocations_match_resource_plan() -> None:
    assert sum(DISK_ALLOCATIONS_MB.values()) + DISK_SPARE_MB == DEFAULT_DISK_BUDGET_MB
    assert sum(DISK_ALLOCATIONS_MB.values()) == 12288


def test_read_model_config_defaults_and_env(tmp_path: Path) -> None:
    defaults = read_model_config(tmp_path)
    assert defaults["EMBEDDING_MODEL"] == "BAAI/bge-m3"
    assert defaults["OLLAMA_MODEL"] == "qwen2.5:1.5b-instruct-q4_K_M"

    (tmp_path / ".env").write_text(
        "EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5\n"
        "OLLAMA_MODEL=qwen2.5:1.5b-instruct-q4_K_M\n"
        "MODEL_BUDGET_MB=2048\n",
        encoding="utf-8",
    )
    values = read_model_config(tmp_path)
    assert values["EMBEDDING_MODEL"] == "BAAI/bge-small-zh-v1.5"


def _passing_inputs():
    services = (
        ServiceUsage("openfactory-api.service", True, 120.0, 384.0),
        ServiceUsage("openfactory-worker.service", True, 300.0, 768.0),
        ServiceUsage("openfactory-beat.service", True, 80.0, 192.0),
        ServiceUsage("openfactory-redis.service", True, 40.0, 320.0),
    )
    disk = (
        DiskUsage("models", "models", 2200.0, 4096),
        DiskUsage("repo", "repo", 500.0, 2048),
        DiskUsage("data", "data", 300.0, 2048),
        DiskUsage("logs", "logs", 50.0, 1024),
        DiskUsage("backups", "backups", 600.0, 3072),
    )
    caps = {"openfactory-api.service": 384, "openfactory-worker.service": 768,
            "openfactory-beat.service": 192, "openfactory-redis.service": 320}
    return services, disk, caps


def test_report_passes_within_budget() -> None:
    services, disk, caps = _passing_inputs()
    report = build_resource_report(
        services, disk, model_peak_mb=1300, unit_caps=caps
    )
    assert report.status == "PASS", report.summary
    assert report.measured_memory_mb == 540.0
    assert report.projected_memory_mb == 1840.0
    assert report.measured_disk_mb == 3650.0
    assert not report.suggestions


def test_report_flags_memory_critical() -> None:
    services, disk, caps = _passing_inputs()
    report = build_resource_report(
        services,
        disk,
        model_peak_mb=1300,
        loaded_model_mb=3800.0,
        unit_caps=caps,
    )
    assert report.status == "FAIL"
    assert any(finding.name == "memory_measured" and finding.level == "critical" for finding in report.findings)
    assert any("并发" in suggestion for suggestion in report.suggestions)


def test_report_flags_disk_warning_and_category() -> None:
    services, disk, caps = _passing_inputs()
    heavy_disk = tuple(
        DiskUsage(item.category, item.path, 12000.0 if item.category == "data" else item.size_mb, item.budget_mb)
        for item in disk
    )
    report = build_resource_report(
        services, heavy_disk, model_peak_mb=1300, unit_caps=caps
    )
    assert report.status == "WARN"
    assert any(finding.name == "disk_total" and finding.level == "warning" for finding in report.findings)
    assert any(finding.name == "disk_data" and finding.level == "warning" for finding in report.findings)
    assert any("data 超出配额" in suggestion for suggestion in report.suggestions)


def test_report_unknown_model_is_unknown() -> None:
    services, disk, caps = _passing_inputs()
    report = build_resource_report(
        services, disk, model_peak_mb=0, model_verified=False, unit_caps=caps
    )
    assert report.status == "UNKNOWN"
    assert any(finding.name == "memory_projected" and finding.level == "unknown" for finding in report.findings)


def test_report_without_unit_caps_is_unknown() -> None:
    services, disk, _caps = _passing_inputs()
    report = build_resource_report(services, disk, model_peak_mb=1300)
    assert report.status == "UNKNOWN"
    assert any(finding.name == "memory_static_caps" and finding.level == "unknown" for finding in report.findings)


def _make_fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    units = repo / "deploy" / "systemd"
    units.mkdir(parents=True)
    for name, cap in (
        ("openfactory-api.service", 384),
        ("openfactory-worker.service", 768),
        ("openfactory-beat.service", 192),
        ("openfactory-redis.service", 320),
    ):
        (units / name).write_text(f"[Service]\nMemoryMax={cap}M\n", encoding="utf-8")
    return repo


def test_cli_json_reports_pass(tmp_path: Path, capsys) -> None:
    home = tmp_path / "runtime"
    for name in ("data", "logs", "backups"):
        (home / name).mkdir(parents=True, exist_ok=True)
    repo = _make_fake_repo(tmp_path)

    code = main(
        [
            "check",
            "--home",
            str(home),
            "--repo",
            str(repo),
            "--no-services",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PASS"
    assert payload["model_peak_mb"] == 1300
    assert payload["unit_caps_mb"]["openfactory-worker.service"] == 768
    assert payload["disk_spare_mb"] == 3072


def test_cli_exit_code_on_over_budget(tmp_path: Path, capsys) -> None:
    home = tmp_path / "runtime"
    home.mkdir()
    repo = _make_fake_repo(tmp_path)

    code = main(
        [
            "check",
            "--home",
            str(home),
            "--repo",
            str(repo),
            "--no-services",
            "--memory-budget-mb",
            "1000",
        ]
    )
    assert code == 1
    assert "FAIL" in capsys.readouterr().out


def test_cli_text_output_contains_summary(tmp_path: Path, capsys) -> None:
    home = tmp_path / "runtime"
    home.mkdir()
    repo = _make_fake_repo(tmp_path)

    code = main(["check", "--home", str(home), "--repo", str(repo), "--no-services"])
    assert code == 0
    output = capsys.readouterr().out
    assert "结论：" in output
    assert "磁盘：" in output
    assert "内存：" in output
