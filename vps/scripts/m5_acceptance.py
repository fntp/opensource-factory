#!/usr/bin/env python3
"""M5 验收 · 上线硬化端到端走查（零额外依赖）。

在临时运行目录 + 临时 SQLite 上启动真实 `uvicorn`，逐项验证 M5-01~M5-08
交付物，并给出 v1.0 发布门禁结论：

    M5-01 正式部署工具链（脚本 / 模板 / systemd / CI / dry-run）
    M5-02 本机一体化（LOCAL_MODE 静态托管 + 只读 API）
    M5-03 监控与告警（状态 / 检查 / 历史 / 告警确认 / 日志）
    M5-04 备份与恢复（快照 / 校验 / 恢复演练 / 保留策略）
    M5-05 安全加固（双令牌 / 401 / 限流 429 / 安全响应头）
    M5-06 资源预算（4G 内存 / 15G 磁盘 CLI 判定）
    M5-07 运维手册（runbook / 诊断脚本）
    M5-08 安全审计（CLI 无 critical / high）
    M5-09 版本与发布说明（三端 1.0.0）

用法（在 vps/ 下）：

    python scripts/m5_acceptance.py
    python scripts/m5_acceptance.py --strict
    python scripts/m5_acceptance.py --report-md docs/planning/acceptance-m5-report.md \
        --report-json docs/planning/acceptance-m5-report.json
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib import error, request

VPS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = VPS_ROOT.parent
sys.path.insert(0, str(VPS_ROOT))

TMP_DIR = Path(tempfile.mkdtemp(prefix="m5-acceptance-"))
HOME = TMP_DIR / "runtime"
BACKUP_DIR = HOME / "backups"
LOG_DIR = HOME / "logs"
ADMIN_DIR = TMP_DIR / "admin-dist"
DB_PATH = TMP_DIR / "m5.db"

INTERNAL_TOKEN = "e2e-m5-internal-token"
PREVIOUS_TOKEN = "e2e-m5-previous-token"
LOCAL_USER = "m5-local"

# 必须在导入 app.* 之前设置环境变量：app.db / app.config 在模块加载时读取配置。
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{DB_PATH}",
        "INTERNAL_TOKEN": INTERNAL_TOKEN,
        "INTERNAL_TOKEN_PREVIOUS": PREVIOUS_TOKEN,
        "RATE_LIMIT_ENABLED": "1",
        "RATE_LIMIT_WINDOW_SECONDS": "60",
        "RATE_LIMIT_MAX_REQUESTS": "8",
        "RATE_LIMIT_HEAVY_MAX_REQUESTS": "2",
        "RATE_LIMIT_TRUST_PROXY": "0",
        "LOCAL_MODE": "0",
        "LOCAL_USER_ID": LOCAL_USER,
        "LOCAL_USER_LOGIN": LOCAL_USER,
        "LOCAL_USER_NAME": "M5 验收用户",
        "BACKUP_ENABLED": "1",
        "BACKUP_DIR": str(BACKUP_DIR),
        "BACKUP_RETENTION_COUNT": "2",
        "BACKUP_MAX_TOTAL_MB": "256",
        "BACKUP_DRILL_ENABLED": "1",
        "MONITOR_ENABLED": "1",
        "MONITOR_HOME": str(HOME),
        "MONITOR_LOG_RETENTION_DAYS": "1",
        "LOG_DIR": str(LOG_DIR),
        "LOG_LEVEL": "WARNING",
        "CELERY_TASK_ALWAYS_EAGER": "1",
    }
)

RESULTS: list[dict[str, object]] = []
STATE: dict[str, str] = {}

DEPLOY_SCRIPTS = (
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
    "resource-budget.sh",
    "ops-diagnose.sh",
    "local-allinone.sh",
    "bootstrap-runtime.sh",
    "doctor.sh",
    "rotate-internal-token.sh",
)

GUIDES = (
    "docs/guides/production-deployment.md",
    "docs/guides/local-allinone-deployment.md",
    "docs/guides/backup-restore.md",
    "docs/guides/security-hardening.md",
    "docs/guides/security-audit.md",
    "docs/guides/resource-budget-verification.md",
    "docs/guides/operations-runbook.md",
)


# ---------------------------------------------------------------------------
# HTTP / 断言工具
# ---------------------------------------------------------------------------
def http_json_full(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = INTERNAL_TOKEN,
) -> tuple[int, object, str, float, dict[str, str]]:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Internal-Token"] = token
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(f"{base}{path}", data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8")
            status = resp.status
            response_headers = {key.lower(): value for key, value in resp.headers.items()}
    except error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        status = exc.code
        response_headers = {key.lower(): value for key, value in exc.headers.items()}
    duration_ms = (time.perf_counter() - started) * 1000
    try:
        payload = json.loads(text) if text else None
    except json.JSONDecodeError:
        payload = None
    return status, payload, text, duration_ms, response_headers


def http_json(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = INTERNAL_TOKEN,
) -> tuple[int, object, str, float]:
    status, payload, text, duration, _headers = http_json_full(
        base, path, method=method, body=body, token=token
    )
    return status, payload, text, duration


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}：期望 {expected!r}，实际 {actual!r}")


def check(cid: str, title: str, fn) -> None:
    started = time.perf_counter()
    try:
        detail = fn() or ""
        RESULTS.append(
            {
                "id": cid,
                "title": title,
                "status": "PASS",
                "detail": str(detail),
                "durationMs": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        print(f"  ✔ [PASS] {title}" + (f" — {detail}" if detail else ""))
    except Exception as exc:  # noqa: BLE001 - 单项失败不影响其余检查
        RESULTS.append(
            {
                "id": cid,
                "title": title,
                "status": "FAIL",
                "detail": str(exc),
                "durationMs": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        print(f"  ✖ [FAIL] {title} — {exc}")


# ---------------------------------------------------------------------------
# 静态检查（部署资产 / 文档 / 版本）
# ---------------------------------------------------------------------------
def run_command(args: list[str], *, cwd: Path = REPO_ROOT, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )


def check_deploy_scripts() -> str:
    missing: list[str] = []
    not_executable: list[str] = []
    for name in DEPLOY_SCRIPTS:
        path = REPO_ROOT / "deploy" / "scripts" / name
        if not path.is_file():
            missing.append(name)
        elif not os.access(path, os.X_OK):
            not_executable.append(name)
    assert_true(not missing, f"缺少脚本：{missing}")
    assert_true(not not_executable, f"脚本不可执行：{not_executable}")
    return f"{len(DEPLOY_SCRIPTS)} 个部署脚本齐全且可执行"


def check_shell_syntax() -> str:
    scripts = sorted((REPO_ROOT / "deploy" / "scripts").glob("*.sh"))
    assert_true(len(scripts) >= len(DEPLOY_SCRIPTS), "部署脚本数量不足")
    for script in scripts:
        run_command(["bash", "-n", str(script)])
    return f"{len(scripts)} 个脚本 bash -n 通过"


def check_systemd_units() -> str:
    units_dir = REPO_ROOT / "deploy" / "systemd"
    expected = {
        "openfactory-api.service",
        "openfactory-worker.service",
        "openfactory-beat.service",
        "openfactory-redis.service",
    }
    actual = {path.name for path in units_dir.glob("*.service")}
    assert_equal(actual, expected, "systemd 单元集合")
    for name in sorted(expected):
        text = (units_dir / name).read_text(encoding="utf-8")
        for marker in ("@APP_DIR@", "@RUNTIME_DIR@", "@SERVICE_USER@", "Restart=on-failure", "NoNewPrivileges=true"):
            assert_true(marker in text, f"{name} 缺少 {marker}")
        assert_true(re.search(r"^MemoryMax=\d+M$", text, re.MULTILINE), f"{name} 缺少 MemoryMax")
        if name != "openfactory-redis.service":
            assert_true("EnvironmentFile=@RUNTIME_DIR@/.env" in text, f"{name} 缺少 EnvironmentFile")
    return "4 个 systemd 单元基线齐全（MemoryMax / NoNewPrivileges / 环境文件）"


def check_templates() -> str:
    wrangler = (REPO_ROOT / "deploy" / "templates" / "wrangler.production.toml.tmpl").read_text(encoding="utf-8")
    caddy = (REPO_ROOT / "deploy" / "templates" / "Caddyfile.tmpl").read_text(encoding="utf-8")
    for marker in ('binding = "DB"', 'binding = "VECTORIZE"', "@D1_DATABASE_ID@", "custom_domain = true"):
        assert_true(marker in wrangler, f"wrangler 模板缺少 {marker}")
    for secret in ("GITHUB_CLIENT_SECRET", "SESSION_SECRET", "INTERNAL_TOKEN"):
        assert_true(not re.search(rf"^\s*{secret}\s*=", wrangler, re.MULTILINE), f"wrangler 模板泄露 {secret}")
    for marker in ("@VPS_DOMAIN@", "@CADDY_EMAIL@", "reverse_proxy 127.0.0.1:8000", "Strict-Transport-Security"):
        assert_true(marker in caddy, f"Caddy 模板缺少 {marker}")
    return "wrangler / Caddy 模板占位符与安全约束齐全"


def check_render_config() -> str:
    env_file = TMP_DIR / "deploy.env"
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
                f"OPENFACTORY_HOME={HOME}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    wrangler_out = TMP_DIR / "wrangler.production.toml"
    caddy_out = TMP_DIR / "Caddyfile"
    run_command(
        [
            "bash",
            str(REPO_ROOT / "deploy" / "scripts" / "render-config.sh"),
            "--env-file",
            str(env_file),
            "--wrangler-out",
            str(wrangler_out),
            "--caddy-out",
            str(caddy_out),
        ]
    )
    wrangler = wrangler_out.read_text(encoding="utf-8")
    caddy = caddy_out.read_text(encoding="utf-8")
    assert_true("11111111-2222-3333-4444-555555555555" in wrangler, "D1 ID 未渲染")
    assert_true('pattern = "api.example.com"' in wrangler, "API 域名未渲染")
    assert_true("node.example.com {" in caddy, "VPS 域名未渲染")
    assert_true(not re.search(r"@[A-Z][A-Z0-9_]*@", wrangler), "wrangler 残留占位符")
    assert_true(not re.search(r"@[A-Z][A-Z0-9_]*@", caddy), "Caddy 残留占位符")
    assert_equal(stat.S_IMODE(wrangler_out.stat().st_mode), 0o600, "wrangler 产物权限")
    assert_equal(stat.S_IMODE(caddy_out.stat().st_mode), 0o600, "Caddy 产物权限")
    return "wrangler + Caddy 渲染无残留占位符，产物权限 600"


def check_deploy_dry_run() -> str:
    env = os.environ.copy()
    env["OPENFACTORY_HOME"] = str(HOME)
    example = str(REPO_ROOT / "deploy" / "env" / "deploy.env.example")
    preflight = run_command(
        ["bash", str(REPO_ROOT / "deploy" / "scripts" / "preflight.sh"), "--env-file", example, "--target", "all", "--dry-run"],
        env=env,
    )
    smoke = run_command(
        ["bash", str(REPO_ROOT / "deploy" / "scripts" / "smoke-test.sh"), "--env-file", example, "--dry-run"],
        env=env,
    )
    combined = preflight.stdout + smoke.stdout
    assert_true("DRY-RUN" in combined or "dry-run" in combined, "dry-run 输出缺少标记")
    return "preflight / smoke-test dry-run 通过"


def check_deploy_workflow() -> str:
    text = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    for marker in (
        "workflow_dispatch:",
        "environment: production",
        "cancel-in-progress: true",
        "vars.DEPLOY_ENABLED == 'true'",
        "deploy/scripts/deploy-edge.sh",
        "deploy/scripts/deploy-admin.sh",
        "deploy/scripts/smoke-test.sh",
    ):
        assert_true(marker in text, f"deploy.yml 缺少 {marker}")
    return "部署工作流受 DEPLOY_ENABLED 门禁保护且串行"


def check_guides() -> str:
    missing = [name for name in GUIDES if not (REPO_ROOT / name).is_file()]
    assert_true(not missing, f"缺少运维文档：{missing}")
    runbook = (REPO_ROOT / "docs" / "guides" / "operations-runbook.md").read_text(encoding="utf-8")
    for keyword in ("日常巡检", "升级", "回滚", "故障", "备份", "密钥轮换"):
        assert_true(keyword in runbook, f"运维手册缺少章节：{keyword}")
    return f"{len(GUIDES)} 份运维指南齐全，runbook 关键章节完整"


def check_ops_scripts_help() -> str:
    for name in ("ops-diagnose.sh", "resource-budget.sh", "local-allinone.sh"):
        proc = run_command(["bash", str(REPO_ROOT / "deploy" / "scripts" / name), "--help"])
        assert_true("用法" in proc.stdout or "usage:" in proc.stdout.lower(), f"{name} --help 输出异常")
    return "ops-diagnose / resource-budget / local-allinone 帮助可用"


def check_versions() -> str:
    admin = json.loads((REPO_ROOT / "admin" / "package.json").read_text(encoding="utf-8"))
    edge = json.loads((REPO_ROOT / "edge" / "package.json").read_text(encoding="utf-8"))
    config_text = (REPO_ROOT / "vps" / "app" / "config.py").read_text(encoding="utf-8")
    match = re.search(r'VERSION:\s*str\s*=\s*"([^"]+)"', config_text)
    assert_true(match is not None, "config.py 未找到 VERSION")
    versions = {
        "admin/package.json": admin.get("version"),
        "edge/package.json": edge.get("version"),
        "vps/app/config.py": match.group(1),
    }
    for env_name in ("vps/.env.example", "deploy/env/openfactory.env.example"):
        env_text = (REPO_ROOT / env_name).read_text(encoding="utf-8")
        env_match = re.search(r"^VERSION=([^\s#]+)$", env_text, re.MULTILINE)
        assert_true(env_match is not None, f"{env_name} 未找到 VERSION")
        versions[env_name] = env_match.group(1)
    wrong = {name: value for name, value in versions.items() if value != "1.0.0"}
    assert_true(not wrong, f"版本不一致：{wrong}")
    return "admin / edge / vps / 两份环境模板均为 1.0.0"


def check_release_notes() -> str:
    path = REPO_ROOT / "docs" / "planning" / "release-v1.0.md"
    assert_true(path.is_file(), "缺少 docs/planning/release-v1.0.md")
    text = path.read_text(encoding="utf-8")
    for keyword in ("v1.0.0", "已知限制", "回滚"):
        assert_true(keyword in text, f"发布说明缺少：{keyword}")
    return "发布说明包含版本、已知限制与回滚说明"


# ---------------------------------------------------------------------------
# 数据种子
# ---------------------------------------------------------------------------
def seed_database() -> None:
    from app.db import SessionLocal, init_db
    from app.models import Category, MyRepository

    init_db()
    db = SessionLocal()
    try:
        db.add(Category(id="cat-m5", name="M5 验收"))
        db.add(
            MyRepository(
                id="me/m5-repo",
                name="m5-repo",
                description="M5 验收用仓库",
                html_url="https://github.com/me/m5-repo",
                stars=42,
                language="Python",
                readme_summary="Python 验收样例",
                category_id="cat-m5",
            )
        )
        db.commit()
    finally:
        db.close()


def create_alert() -> str:
    from uuid import uuid4

    from app.db import SessionLocal
    from app.models import MonitoringAlert

    alert_id = f"accept-{uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        db.add(
            MonitoringAlert(
                id=alert_id,
                kind="service",
                severity="warning",
                message="M5 验收告警：由 m5_acceptance.py 注入，用于验证告警确认接口",
                dedupe_key=f"manual:{alert_id}",
                status="open",
            )
        )
        db.commit()
    finally:
        db.close()
    return alert_id


# ---------------------------------------------------------------------------
# 运行时检查（主进程：部署 / 监控 / 备份 / 安全）
# ---------------------------------------------------------------------------
def run_static_checks() -> None:
    check("M5-A01", "部署脚本齐全且可执行", check_deploy_scripts)
    check("M5-A02", "部署脚本语法检查", check_shell_syntax)
    check("M5-A03", "systemd 单元资源与安全基线", check_systemd_units)
    check("M5-A04", "部署模板占位符与安全约束", check_templates)
    check("M5-A05", "配置渲染（wrangler / Caddy）", check_render_config)
    check("M5-A06", "preflight / smoke-test dry-run", check_deploy_dry_run)
    check("M5-A07", "部署工作流门禁", check_deploy_workflow)
    check("M5-G01", "运维手册与指南齐全", check_guides)
    check("M5-G02", "运维脚本帮助可用", check_ops_scripts_help)
    check("M5-I01", "三端版本号 1.0.0", check_versions)
    check("M5-I02", "v1.0 发布说明", check_release_notes)


def check_health(base: str) -> str:
    status, payload, _, _ = http_json(base, "/healthz", token=None)
    assert_equal(status, 200, "/healthz 状态码")
    assert_equal(payload.get("status"), "ok", "/healthz status")
    assert_equal(payload.get("version"), "1.0.0", "/healthz version")
    ready_status, ready, _, _ = http_json(base, "/healthz/ready", token=None)
    assert_equal(ready_status, 200, "/healthz/ready 状态码")
    assert_equal(ready.get("status"), "ok", "/healthz/ready status")
    return "healthz + ready 均 200"


def check_local_disabled(base: str) -> str:
    for path in ("/local/api/auth/me", "/local/api/repos", "/local/api/local/status"):
        status, _, _, _ = http_json(base, path, token=None)
        assert_equal(status, 404, f"{path} 非本机模式状态码")
    return "LOCAL_MODE=0 时 /local/api/* 全部 404"


def check_monitoring_status(base: str) -> str:
    status, payload, text, _ = http_json(base, "/api/monitoring/status")
    assert_equal(status, 200, "/api/monitoring/status 状态码")
    for key in ("status", "checkedAt", "checks", "resources", "findings", "thresholds"):
        assert_true(key in payload, f"监控状态缺少 {key}")
    assert_equal(payload["thresholds"]["memoryCriticalMb"], 4096, "内存红线")
    assert_equal(payload["thresholds"]["diskWarnMb"], 13312, "磁盘预警线")
    assert_true(INTERNAL_TOKEN not in text, "监控响应泄露内部令牌")
    return f"status={payload['status']}，{len(payload['checks'])} 项健康检查"


def check_monitoring_run(base: str) -> str:
    status, payload, _, _ = http_json(base, "/api/monitoring/check", method="POST", body={})
    assert_equal(status, 200, "/api/monitoring/check 状态码")
    for key in ("id", "status", "checkedAt", "checks", "resources", "findings"):
        assert_true(key in payload, f"监控检查结果缺少 {key}")
    run_id = payload["id"]
    hist_status, history, _, _ = http_json(base, "/api/monitoring/history?limit=5")
    assert_equal(hist_status, 200, "/api/monitoring/history 状态码")
    assert_true(history["count"] >= 1, "监控历史为空")
    assert_true(any(item["id"] == run_id for item in history["items"]), "最新检查未落库")
    return f"检查 {run_id[:8]} 落库，历史 {history['count']} 条"


def check_monitoring_alerts(base: str) -> str:
    alert_id = create_alert()
    status, payload, _, _ = http_json(base, "/api/monitoring/alerts?status=open&limit=50")
    assert_equal(status, 200, "告警列表状态码")
    assert_true(any(item["id"] == alert_id for item in payload["items"]), "注入告警未出现在列表")
    ack_status, ack, _, _ = http_json(
        base, f"/api/monitoring/alerts/{alert_id}/ack", method="POST", body={}
    )
    assert_equal(ack_status, 200, "告警确认状态码")
    assert_equal(ack["status"], "acknowledged", "告警确认后状态")
    status, payload, _, _ = http_json(base, "/api/monitoring/alerts?status=acknowledged&limit=50")
    assert_true(any(item["id"] == alert_id for item in payload["items"]), "已确认告警未出现在列表")
    return f"告警 {alert_id} 确认成功"


def check_monitoring_logs(base: str) -> str:
    status, payload, _, _ = http_json(base, "/api/monitoring/logs")
    assert_equal(status, 200, "日志状态码")
    for key in ("path", "exists", "files", "totalMb", "budgetMb", "retentionDays"):
        assert_true(key in payload, f"日志状态缺少 {key}")
    status, cleanup, _, _ = http_json(
        base, "/api/monitoring/logs/cleanup?dry_run=true", method="POST", body={}
    )
    assert_equal(status, 200, "日志清理状态码")
    assert_equal(cleanup["dryRun"], True, "日志清理 dryRun")
    return f"日志目录 {payload['files']} 个文件 / {payload['totalMb']} MB"


def check_backup_create(base: str) -> str:
    status, payload, _, _ = http_json(base, "/api/backup/status")
    assert_equal(status, 200, "备份状态码")
    assert_equal(payload["retention"], 2, "备份保留份数")
    assert_equal(payload["withinBudget"], True, "备份预算")
    status, entry, _, _ = http_json(base, "/api/backup/sqlite", method="POST", body={})
    assert_equal(status, 200, "创建 SQLite 快照状态码")
    assert_equal(entry["kind"], "sqlite", "快照类型")
    assert_true(entry["sizeBytes"] > 0, "快照大小为 0")
    STATE["snapshot"] = entry["name"]
    return f"快照 {entry['name']}（{entry['sizeBytes']} bytes）"


def check_backup_verify(base: str) -> str:
    name = STATE["snapshot"]
    status, payload, _, _ = http_json(
        base, "/api/backup/sqlite/verify", method="POST", body={"name": name}
    )
    assert_equal(status, 200, "快照校验状态码")
    assert_equal(payload["ok"], True, "快照校验结果")
    assert_true(payload["checks"], "快照校验无检查项")
    assert_true(payload["tableCounts"], "快照校验无表行数")
    return f"{len(payload['checks'])} 项校验通过，{len(payload['tableCounts'])} 张表"


def check_backup_drill(base: str) -> str:
    name = STATE["snapshot"]
    status, payload, _, _ = http_json(
        base, "/api/backup/sqlite/drill", method="POST", body={"name": name}
    )
    assert_equal(status, 200, "恢复演练状态码")
    assert_equal(payload["ok"], True, f"恢复演练失败：{payload.get('error')}")
    assert_true(payload["tableCounts"], "恢复演练无表行数")
    return f"恢复到临时库成功，{len(payload['tableCounts'])} 张表行数一致"


def check_backup_files(base: str) -> str:
    status, payload, _, _ = http_json(base, "/api/backup/files?kind=sqlite")
    assert_equal(status, 200, "备份文件列表状态码")
    assert_true(payload["count"] >= 1, "备份文件列表为空")
    assert_true(any(item["name"] == STATE["snapshot"] for item in payload["items"]), "快照未出现在列表")
    return f"{payload['count']} 份 SQLite 备份"


def check_security_status(base: str) -> str:
    status, payload, text, _ = http_json(base, "/api/security/status")
    assert_equal(status, 200, "安全状态码")
    assert_equal(payload["internalToken"]["configured"], True, "当前令牌未配置")
    assert_equal(payload["internalToken"]["previousConfigured"], True, "旧令牌未配置")
    assert_equal(payload["internalToken"]["rotationPending"], True, "轮换过渡状态")
    assert_equal(payload["rateLimit"]["enabled"], True, "限流未启用")
    assert_equal(payload["rateLimit"]["maxRequests"], 8, "普通接口限额")
    assert_true(INTERNAL_TOKEN not in text and PREVIOUS_TOKEN not in text, "安全状态泄露令牌明文")
    return "双令牌轮换状态正确，限流参数可见，无明文泄露"


def check_dual_token(base: str) -> str:
    status, _, _, _ = http_json(base, "/api/security/status", token=PREVIOUS_TOKEN)
    assert_equal(status, 200, "旧令牌应被接受")
    status, _, _, _ = http_json(base, "/api/security/status", token="wrong-token")
    assert_equal(status, 401, "错误令牌状态码")
    return "旧令牌可用，错误令牌 401"


def check_rate_limit(base: str) -> str:
    saw_429 = False
    retry_after = ""
    for _ in range(20):
        status, _, _, _, headers = http_json_full(base, "/api/security/status")
        if status == 429:
            saw_429 = True
            retry_after = headers.get("retry-after", "")
            break
    assert_true(saw_429, "连续请求未触发 429")
    return f"限流触发 429，Retry-After={retry_after or '未返回'}"


def check_security_headers(base: str) -> str:
    status, _, _, _, headers = http_json_full(base, "/healthz", token=None)
    assert_equal(status, 200, "/healthz 状态码")
    expected = {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "strict-origin-when-cross-origin",
    }
    for key, value in expected.items():
        assert_equal(headers.get(key), value, f"响应头 {key}")
    assert_true("camera=()" in headers.get("permissions-policy", ""), "permissions-policy 缺失")
    return "安全响应头基线齐全"


def run_runtime_checks(base: str) -> None:
    check("M5-B01", "默认模式关闭本机接口", lambda: check_local_disabled(base))
    check("M5-C01", "健康检查 / 就绪探针", lambda: check_health(base))
    check("M5-C02", "监控实时状态", lambda: check_monitoring_status(base))
    check("M5-C03", "监控检查与历史落库", lambda: check_monitoring_run(base))
    check("M5-C04", "告警列表与确认", lambda: check_monitoring_alerts(base))
    check("M5-C05", "日志状态与保留清理", lambda: check_monitoring_logs(base))
    check("M5-D01", "SQLite 快照创建与预算", lambda: check_backup_create(base))
    check("M5-D02", "快照完整性校验", lambda: check_backup_verify(base))
    check("M5-D03", "恢复演练", lambda: check_backup_drill(base))
    check("M5-D04", "备份产物列表", lambda: check_backup_files(base))
    check("M5-E01", "安全加固状态", lambda: check_security_status(base))
    check("M5-E02", "内部令牌双令牌与 401", lambda: check_dual_token(base))
    check("M5-E03", "接口限流 429", lambda: check_rate_limit(base))
    check("M5-E04", "安全响应头", lambda: check_security_headers(base))


# ---------------------------------------------------------------------------
# 本机一体化检查（LOCAL_MODE=1）
# ---------------------------------------------------------------------------
def check_local_ui(base: str) -> str:
    status, _, text, _ = http_json(base, "/", token=None)
    assert_equal(status, 200, "本机首页状态码")
    assert_true("M5-LOCAL-OK" in text, "首页未返回 admin 构建产物")
    status, _, text, _ = http_json(base, "/dashboard/repos", token=None)
    assert_equal(status, 200, "SPA 回退状态码")
    assert_true("M5-LOCAL-OK" in text, "SPA 回退未返回 index.html")
    return "首页与 SPA 回退均命中 admin 构建产物"


def check_local_api(base: str) -> str:
    status, user, _, _ = http_json(base, "/local/api/auth/me", token=None)
    assert_equal(status, 200, "本机用户状态码")
    assert_equal(user["login"], LOCAL_USER, "本机用户 login")
    status, repos, _, _ = http_json(base, "/local/api/repos", token=None)
    assert_equal(status, 200, "本机仓库状态码")
    assert_true(isinstance(repos, list) and any(item["id"] == "me/m5-repo" for item in repos), "本机仓库列表为空")
    status, stats, _, _ = http_json(base, "/local/api/dashboard/stats", token=None)
    assert_equal(status, 200, "仪表盘统计状态码")
    assert_true(stats["totalRepos"] >= 1, "仪表盘仓库数异常")
    status, local, _, _ = http_json(base, "/local/api/local/status", token=None)
    assert_equal(status, 200, "本机状态码")
    assert_equal(local["mode"], "local", "本机模式")
    assert_equal(local["readOnly"], True, "只读标记")
    assert_equal(local["adminReady"], True, "admin 构建就绪")
    assert_equal(local["version"], "1.0.0", "本机版本")
    return f"用户 {user['login']} / 仓库 {len(repos)} 个 / 版本 {local['version']}"


def run_local_checks(base: str) -> None:
    check("M5-B02", "本机静态托管与 SPA 回退", lambda: check_local_ui(base))
    check("M5-B03", "本机只读 API 契约", lambda: check_local_api(base))


# ---------------------------------------------------------------------------
# CLI 检查（资源预算 / 安全审计）
# ---------------------------------------------------------------------------
def check_resource_budget() -> str:
    proc = run_command(
        [
            sys.executable,
            "-m",
            "app.resource_budget",
            "check",
            "--json",
            "--no-services",
            "--home",
            str(HOME),
            "--repo",
            str(REPO_ROOT),
        ],
        cwd=VPS_ROOT,
    )
    payload = json.loads(proc.stdout)
    assert_equal(payload["memory_budget_mb"], 4096, "内存预算")
    assert_equal(payload["disk_budget_mb"], 15360, "磁盘预算")
    assert_equal(payload["status"], "PASS", f"资源预算判定：{payload.get('summary')}")
    assert_true(len(payload["unit_caps_mb"]) == 4, "systemd 单元上限缺失")
    return payload["summary"]


def check_security_audit() -> str:
    proc = run_command(
        [sys.executable, "-m", "app.security_audit", "--root", str(REPO_ROOT), "--json"],
        cwd=VPS_ROOT,
    )
    payload = json.loads(proc.stdout)
    summary = payload["summary"]
    assert_equal(summary["critical"], 0, "安全审计 critical")
    assert_equal(summary["high"], 0, "安全审计 high")
    assert_true(payload["status"] in ("PASS", "WARN"), f"安全审计状态：{payload['status']}")
    return f"status={payload['status']}，medium={summary['medium']}，checks={payload['checks_run']}"


def run_cli_checks() -> None:
    check("M5-F01", "资源预算 4G / 15G 判定", check_resource_budget)
    check("M5-H01", "安全审计无 critical / high", check_security_audit)


# ---------------------------------------------------------------------------
# 服务生命周期 / 报告
# ---------------------------------------------------------------------------
def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(base: str, process: subprocess.Popen, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout is not None else ""
            raise RuntimeError(f"uvicorn 提前退出（code={process.returncode}）：\n{output[-3000:]}")
        try:
            status, payload, _, _ = http_json(base, "/healthz", token=None)
            if status == 200 and isinstance(payload, dict):
                return
        except Exception:  # noqa: BLE001 - 尚未就绪
            pass
        time.sleep(0.3)
    raise RuntimeError("等待 uvicorn 就绪超时")


def start_server(extra_env: dict[str, str]) -> tuple[subprocess.Popen, str]:
    port = get_free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    env.update(extra_env)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=VPS_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    wait_for_health(base, process)
    return process, base


def stop_server(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def summarize() -> dict[str, int]:
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for item in RESULTS:
        counts[str(item["status"])] = counts.get(str(item["status"]), 0) + 1
    return counts


def git_info() -> tuple[str, str]:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return branch, commit
    except Exception:  # noqa: BLE001 - 报告不因 git 缺失失败
        return "unknown", "unknown"


def build_markdown(meta: dict[str, str]) -> str:
    rows = "\n".join(
        f"| {item['id']} | {item['title']} | {item['status']} | {item['detail']} | {item['durationMs']}ms |"
        for item in RESULTS
    )
    summary = summarize()
    conclusion = "全部通过，可发布 v1.0.0" if summary["FAIL"] == 0 else "存在失败项，验收不通过"
    return f"""# M5 验收报告（自动生成）

- 生成时间：{meta['finishedAt']}
- 分支 / 提交：{meta['branch']} / {meta['commit']}
- 运行环境：{meta['platform']} · Python {meta['python']}
- 验收方式：临时 SQLite + 临时运行目录 + 真实 uvicorn + 部署资产 dry-run
- 判定口径：PASS 通过 · FAIL 行为错误 · SKIP 跳过

## 检查结果

| # | 检查 | 结果 | 说明 | 耗时 |
| --- | --- | --- | --- | --- |
{rows}

## 汇总

- PASS：{summary['PASS']}
- FAIL：{summary['FAIL']}
- SKIP：{summary['SKIP']}
- 结论：{conclusion}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="M5 验收脚本")
    parser.add_argument("--strict", action="store_true", help="存在 SKIP 时也返回非零")
    parser.add_argument("--keep", action="store_true", help="保留临时目录")
    parser.add_argument("--report-md", default=None, help="Markdown 报告输出路径")
    parser.add_argument("--report-json", default=None, help="JSON 报告输出路径")
    args = parser.parse_args()

    server = None
    local_server = None
    try:
        for path in (HOME, HOME / "data", BACKUP_DIR, LOG_DIR, ADMIN_DIR):
            path.mkdir(parents=True, exist_ok=True)
        (ADMIN_DIR / "index.html").write_text(
            "<!doctype html><html><body><div id=\"root\">M5-LOCAL-OK</div></body></html>",
            encoding="utf-8",
        )

        print("• 种入 M5 验收数据…")
        seed_database()

        print("• 静态部署资产检查…")
        run_static_checks()

        print("• 启动主服务（监控 / 备份 / 安全）…")
        server, base = start_server({})
        print(f"  · {base}")
        run_runtime_checks(base)
        stop_server(server)
        server = None

        print("• 启动本机一体化服务（LOCAL_MODE=1）…")
        local_server, local_base = start_server(
            {"LOCAL_MODE": "1", "LOCAL_ADMIN_DIR": str(ADMIN_DIR)}
        )
        print(f"  · {local_base}")
        run_local_checks(local_base)
        stop_server(local_server)
        local_server = None

        print("• CLI 检查（资源预算 / 安全审计）…")
        run_cli_checks()

        summary = summarize()
        print(f"\n汇总：PASS {summary['PASS']} · FAIL {summary['FAIL']} · SKIP {summary['SKIP']}")

        branch, commit = git_info()
        meta = {
            "branch": branch,
            "commit": commit,
            "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "platform": platform.platform(),
            "python": platform.python_version(),
        }
        if args.report_md:
            target = (REPO_ROOT / args.report_md).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(build_markdown(meta), encoding="utf-8")
            print(f"• 已写入 Markdown 报告：{target}")
        if args.report_json:
            target = (REPO_ROOT / args.report_json).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps({"meta": meta, "results": RESULTS}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"• 已写入 JSON 报告：{target}")

        if summary["FAIL"] > 0 or (args.strict and summary["SKIP"] > 0):
            return 1
        return 0
    finally:
        stop_server(server)
        stop_server(local_server)
        if args.keep:
            print(f"• 保留临时目录：{TMP_DIR}")
        else:
            shutil.rmtree(TMP_DIR, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
