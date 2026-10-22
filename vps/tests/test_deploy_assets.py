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


DEPLOY_CONTROL_KEYS = {
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "D1_DATABASE_NAME",
    "D1_DATABASE_ID",
    "WORKER_NAME",
    "VECTORIZE_INDEX_NAME",
    "PAGES_PROJECT_NAME",
    "ADMIN_ORIGIN",
    "API_ORIGIN",
    "VPS_NODE_URL",
    "CADDY_EMAIL",
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "SESSION_SECRET",
    "OPENFACTORY_HOME",
}

PRODUCTION_SCRIPTS = (
    "preflight.sh",
    "render-config.sh",
    "deploy-edge.sh",
    "deploy-admin.sh",
    "deploy-vps.sh",
    "deploy-all.sh",
    "smoke-test.sh",
    "setup-https.sh",
    "backup-d1.sh",
    "backup-all.sh",
    "backup-drill.sh",
    "restore-sqlite.sh",
    "security-audit.sh",
)


def test_deploy_control_template_covers_required_keys() -> None:
    env = parse_env_file(DEPLOY / "env" / "deploy.env.example")
    missing = DEPLOY_CONTROL_KEYS - set(env)
    assert not missing, f"deploy.env.example 缺少字段：{sorted(missing)}"
    # 模板只允许占位符，不能带真实凭据
    assert env["CLOUDFLARE_API_TOKEN"].startswith("REPLACE_WITH_")
    assert env["D1_DATABASE_ID"].startswith("REPLACE_WITH_")
    assert env["GITHUB_CLIENT_SECRET"].startswith("REPLACE_WITH_")
    assert env["SESSION_SECRET"].startswith("REPLACE_WITH_")


def test_wrangler_production_template_is_safe() -> None:
    text = (DEPLOY / "templates" / "wrangler.production.toml.tmpl").read_text(encoding="utf-8")
    assert 'binding = "DB"' in text
    assert 'database_id = "@D1_DATABASE_ID@"' in text
    assert 'binding = "VECTORIZE"' in text
    assert "custom_domain = true" in text
    assert "@API_ORIGIN_HOST@" in text
    # 机密只能走 wrangler secret put，不得作为配置项写入模板
    for secret in ("GITHUB_CLIENT_SECRET", "SESSION_SECRET", "INTERNAL_TOKEN"):
        assert not re.search(rf"^\s*{secret}\s*=", text, re.MULTILINE), secret


def test_caddy_template_terminates_tls_and_proxies_local_api() -> None:
    text = (DEPLOY / "templates" / "Caddyfile.tmpl").read_text(encoding="utf-8")
    assert "@VPS_DOMAIN@" in text
    assert "@CADDY_EMAIL@" in text
    assert "reverse_proxy 127.0.0.1:8000" in text
    assert "Strict-Transport-Security" in text


def test_deploy_workflow_is_guarded_and_serialized() -> None:
    text = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "environment: production" in text
    assert "cancel-in-progress: true" in text
    assert "vars.DEPLOY_ENABLED == 'true'" in text
    assert "deploy/scripts/deploy-edge.sh" in text
    assert "deploy/scripts/deploy-admin.sh" in text
    assert "deploy/scripts/smoke-test.sh" in text


def test_production_scripts_support_help() -> None:
    for name in PRODUCTION_SCRIPTS:
        proc = subprocess.run(
            ["bash", str(DEPLOY / "scripts" / name), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "用法" in proc.stdout, name


def test_resource_budget_script_help() -> None:
    proc = subprocess.run(
        ["bash", str(DEPLOY / "scripts" / "resource-budget.sh"), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "usage:" in proc.stdout.lower() or "资源预算" in proc.stdout


def test_preflight_and_smoke_dry_run_pass_with_example(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["OPENFACTORY_HOME"] = str(tmp_path / "runtime")
    example = str(DEPLOY / "env" / "deploy.env.example")
    for args in (
        ["preflight.sh", "--env-file", example, "--target", "all", "--dry-run"],
        ["smoke-test.sh", "--env-file", example, "--dry-run"],
    ):
        proc = subprocess.run(
            ["bash", str(DEPLOY / "scripts" / args[0]), *args[1:]],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "DRY-RUN" in proc.stdout or "dry-run" in proc.stdout, proc.stdout


def test_render_config_replaces_placeholders(tmp_path: Path) -> None:
    env_file = tmp_path / "deploy.env"
    env_file.write_text(
        "\n".join(
            [
                "WORKER_NAME=opensource-factory-api",
                "D1_DATABASE_NAME=opensource-factory",
                "D1_DATABASE_ID=11111111-2222-3333-4444-555555555555",
                "VECTORIZE_INDEX_NAME=opensource-factory-vectors",
                "ADMIN_ORIGIN=https://admin.example.com",
                "API_ORIGIN=https://api.example.com",
                "VPS_NODE_URL=https://node.example.com",
                "GITHUB_CLIENT_ID=Iv1abcdef",
                "CADDY_EMAIL=ops@example.com",
                f"OPENFACTORY_HOME={tmp_path / 'runtime'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    wrangler_out = tmp_path / "wrangler.production.toml"
    caddy_out = tmp_path / "Caddyfile"
    subprocess.run(
        [
            "bash",
            str(DEPLOY / "scripts" / "render-config.sh"),
            "--env-file",
            str(env_file),
            "--wrangler-out",
            str(wrangler_out),
            "--caddy-out",
            str(caddy_out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wrangler = wrangler_out.read_text(encoding="utf-8")
    caddy = caddy_out.read_text(encoding="utf-8")
    assert "11111111-2222-3333-4444-555555555555" in wrangler
    assert 'pattern = "api.example.com"' in wrangler
    assert "admin.example.com" in wrangler
    assert "node.example.com {" in caddy
    assert "ops@example.com" in caddy
    assert not re.search(r"@[A-Z][A-Z0-9_]*@", wrangler)
    assert not re.search(r"@[A-Z][A-Z0-9_]*@", caddy)
    assert _mode(wrangler_out) == 0o600
    assert _mode(caddy_out) == 0o600


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
