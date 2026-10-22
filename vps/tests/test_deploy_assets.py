"""部署资产一致性测试（REQ-202610-0893）。

保证环境模板、配置字段、systemd 单元与脚本不漂移；不访问网络。
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

from app.config import Settings
from app.runtime import REQUIRED_ENV_KEYS, SUBDIRS, check_runtime, parse_env_file

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
UNITS = (
    "openfactory-api.service",
    "openfactory-beat.service",
    "openfactory-redis.service",
    "openfactory-worker.service",
)


def _env_keys(path: Path) -> set[str]:
    return set(parse_env_file(path))


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_runtime_required_keys_match_settings() -> None:
    assert set(REQUIRED_ENV_KEYS) == set(Settings.model_fields)


def test_vps_env_template_covers_all_settings() -> None:
    keys = _env_keys(ROOT / "vps" / ".env.example")
    missing = set(Settings.model_fields) - keys
    assert not missing, f"vps/.env.example 缺少字段：{sorted(missing)}"


def test_deploy_env_template_covers_all_settings() -> None:
    keys = _env_keys(DEPLOY / "env" / "openfactory.env.example")
    missing = set(Settings.model_fields) - keys
    assert not missing, f"生产模板缺少字段：{sorted(missing)}"
    assert "OPENFACTORY_HOME" in keys


def test_deploy_env_template_is_production_safe() -> None:
    env = parse_env_file(DEPLOY / "env" / "openfactory.env.example")
    assert env["CORS_ORIGINS"] != "*"
    assert env["CELERY_TASK_ALWAYS_EAGER"] == "0"
    assert env["DATABASE_URL"].startswith("sqlite:///@RUNTIME_DIR@/data/")
    assert env["LOG_DIR"] == "@RUNTIME_DIR@/logs"
    # 由 bootstrap 随机生成，模板本身保持空白
    assert env["INTERNAL_TOKEN"] == ""


def test_systemd_units_have_baseline_directives() -> None:
    files = sorted(path.name for path in (DEPLOY / "systemd").glob("*.service"))
    assert files == sorted(UNITS)
    for name in UNITS:
        text = (DEPLOY / "systemd" / name).read_text(encoding="utf-8")
        assert "@APP_DIR@" in text
        assert "@RUNTIME_DIR@" in text
        assert "@SERVICE_USER@" in text
        if name != "openfactory-redis.service":
            assert "EnvironmentFile=@RUNTIME_DIR@/.env" in text
        assert "Restart=on-failure" in text
        assert re.search(r"^MemoryMax=\d+M$", text, re.MULTILINE), name
        assert "NoNewPrivileges=true" in text


def test_redis_config_matches_budget() -> None:
    text = (DEPLOY / "redis" / "redis.conf").read_text(encoding="utf-8")
    assert "bind 127.0.0.1 ::1" in text
    assert "protected-mode yes" in text
    assert "maxmemory 256mb" in text
    assert "maxmemory-policy noeviction" in text
    assert 'save ""' in text
    assert "appendonly no" in text


def test_shell_scripts_are_valid_bash() -> None:
    scripts = sorted((DEPLOY / "scripts").glob("*.sh"))
    assert scripts
    for script in scripts:
        subprocess.run(["bash", "-n", str(script)], check=True, capture_output=True, text=True)


def test_bootstrap_creates_runtime_layout_and_is_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    env = os.environ.copy()
    env["OPENFACTORY_HOME"] = str(home)
    script = DEPLOY / "scripts" / "bootstrap-runtime.sh"

    subprocess.run(["bash", str(script)], env=env, check=True, capture_output=True, text=True)

    for name in SUBDIRS:
        assert (home / name).is_dir(), name
    assert _mode(home) == 0o700
    assert _mode(home / ".env") == 0o600
    assert _mode(home / "etc" / "redis.conf") == 0o600

    values = parse_env_file(home / ".env")
    assert len(values["INTERNAL_TOKEN"]) == 64
    assert values["LOG_DIR"] == f"{home}/logs"
    assert f"dir {home}/data/redis" in (home / "etc" / "redis.conf").read_text(encoding="utf-8")

    # 幂等：重复执行不重置已生成的 token / 配置
    token = values["INTERNAL_TOKEN"]
    subprocess.run(["bash", str(script)], env=env, check=True, capture_output=True, text=True)
    assert parse_env_file(home / ".env")["INTERNAL_TOKEN"] == token

    results = check_runtime(home)
    assert all(item.ok for item in results), results


def test_doctor_script_reports_green_runtime(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    env = os.environ.copy()
    env["OPENFACTORY_HOME"] = str(home)
    subprocess.run(
        ["bash", str(DEPLOY / "scripts" / "bootstrap-runtime.sh")],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    proc = subprocess.run(
        ["bash", str(DEPLOY / "scripts" / "doctor.sh"), "--home", str(home)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "FAIL" not in proc.stdout
