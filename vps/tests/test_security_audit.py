"""M5-08 安全审计工具测试（离线，不访问网络）。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.security_headers import SecurityHeadersMiddleware
from app.security_audit import (
    AuditContext,
    check_lockfiles,
    check_privacy_boundary,
    check_production_config,
    check_secrets,
    check_session_headers,
    check_tracked_env,
    main,
    run_audit,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _ctx(root: Path) -> AuditContext:
    return AuditContext(root=root)


def test_secret_scan_detects_github_token(tmp_path: Path) -> None:
    token = "ghp_" + "a" * 36
    _write(tmp_path / "edge" / "src" / "config.ts", f'const token = "{token}";\n')
    findings = check_secrets(_ctx(tmp_path))
    assert any(f.check == "secret-scan" and f.severity == "high" for f in findings)


def test_secret_scan_ignores_placeholders_and_test_fixtures(tmp_path: Path) -> None:
    _write(
        tmp_path / "deploy" / "env" / "app.env.example",
        "GITHUB_TOKEN=REPLACE_WITH_GITHUB_TOKEN\nAPI_KEY=\n",
    )
    fake = "ghp_" + "b" * 36
    _write(tmp_path / "vps" / "tests" / "fixture.py", f'TOKEN = "{fake}"\n')
    findings = check_secrets(_ctx(tmp_path))
    assert not [f for f in findings if f.severity == "high"]


def test_tracked_env_is_high(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path / ".gitignore", ".env\n**/.env\n!**/.env.example\n")
    monkeypatch.setattr("app.security_audit._git_tracked_files", lambda root: {".env"})
    findings = check_tracked_env(_ctx(tmp_path))
    assert any(f.severity == "high" and "运行环境文件" in f.title for f in findings)


def test_lockfile_http_source_and_missing_integrity(tmp_path: Path) -> None:
    _write(
        tmp_path / "admin" / "package-lock.json",
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "admin"},
                    "node_modules/a": {"version": "1.0.0", "resolved": "http://registry.example/a.tgz"},
                },
            }
        ),
    )
    _write(
        tmp_path / "edge" / "package-lock.json",
        json.dumps({"lockfileVersion": 3, "packages": {"": {"name": "edge"}}}),
    )
    findings = check_lockfiles(_ctx(tmp_path))
    assert any(f.severity == "high" and "HTTP" in f.title for f in findings)
    assert any(f.severity == "medium" and "integrity" in f.title for f in findings)


def test_unpinned_python_requirements_are_medium(tmp_path: Path) -> None:
    _write(tmp_path / "vps" / "requirements.txt", "fastapi>=0.115\npytest==8.0\n")
    findings = check_lockfiles(_ctx(tmp_path))
    assert any(f.severity == "medium" and "未锁定" in f.title for f in findings)


def test_production_config_rejects_wildcard_cors(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENFACTORY_HOME", raising=False)
    _write(
        tmp_path / "deploy" / "env" / "openfactory.env.example",
        "CORS_ORIGINS=*\nRATE_LIMIT_ENABLED=1\n",
    )
    _write(tmp_path / "deploy" / "env" / "deploy.env.example", "CLOUDFLARE_API_TOKEN=REPLACE_WITH_TOKEN\n")
    findings = check_production_config(_ctx(tmp_path))
    assert any(f.severity == "high" and "CORS" in f.title for f in findings)


def test_production_config_rejects_disabled_rate_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENFACTORY_HOME", raising=False)
    _write(
        tmp_path / "deploy" / "env" / "openfactory.env.example",
        "CORS_ORIGINS=https://admin.example.com\nRATE_LIMIT_ENABLED=0\n",
    )
    findings = check_production_config(_ctx(tmp_path))
    assert any(f.severity == "high" and "限流" in f.title for f in findings)


def test_cookie_and_security_headers(tmp_path: Path) -> None:
    _write(
        tmp_path / "edge" / "src" / "auth.ts",
        "function buildSetCookie() { return 'HttpOnly'; }\n",
    )
    _write(tmp_path / "edge" / "src" / "index.ts", "const app = new Hono();\n")
    _write(tmp_path / "vps" / "app" / "main.py", "app = FastAPI()\n")
    findings = check_session_headers(_ctx(tmp_path))
    titles = {f.title for f in findings}
    assert "会话 Cookie 缺少 SameSite=Lax" in titles
    assert "会话 Cookie 缺少 Secure 分支" in titles
    assert "edge 未启用安全响应头" in titles
    assert "VPS 未启用安全响应头" in titles


def test_privacy_log_detection_does_not_match_fingerprint(tmp_path: Path) -> None:
    _write(tmp_path / "vps" / "app" / "bad.py", 'logger.info("token=%s", token)\n')
    _write(
        tmp_path / "vps" / "app" / "good.py",
        "def token_fingerprint(token: str) -> str:\n"
        '    print("fingerprint only")\n'
        "    return token[:12]\n",
    )
    findings = check_privacy_boundary(_ctx(tmp_path))
    high = [f for f in findings if f.severity == "high"]
    assert len(high) == 1
    assert high[0].evidence == "vps/app/bad.py:1"


def test_report_json_and_strict_exit_code(tmp_path: Path, capsys) -> None:
    token = "ghp_" + "c" * 36
    _write(tmp_path / "edge" / "src" / "config.ts", f'const token = "{token}";\n')
    code = main(["--root", str(tmp_path), "--json", "--strict"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["status"] == "FAIL"
    assert payload["summary"]["high"] >= 1


def test_security_headers_middleware_sets_baseline_headers() -> None:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    response = TestClient(app).get("/healthz")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["permissions-policy"]


def test_current_repository_has_no_high_findings() -> None:
    result = run_audit(AuditContext(root=REPO_ROOT))
    assert not [f for f in result.findings if f.severity in ("critical", "high")], result.to_dict()
