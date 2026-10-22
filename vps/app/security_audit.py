"""M5-08 安全审计：依赖完整性、配置基线、密钥泄露与隐私边界只读检查。

设计目标：

- **离线优先**：默认只读扫描仓库，不访问网络，测试与 CI 可稳定运行；
- **只读**：不修改运行配置、不启动 / 停止服务、不输出任何密钥明文；
- **可回归**：每条发现都带 `check / category / severity / evidence / recommendation`，
  `--strict` 在 high / critical 时返回非零，可直接作为 CI 门禁。

用法（在 `vps/` 目录或通过部署脚本）：

    python -m app.security_audit --root .. --json
    python -m app.security_audit --root .. --strict
    python -m app.security_audit --root .. --online --json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
SEVERITY_LABEL = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "info": "INFO",
}

EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "coverage",
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".wrangler",
    ".next",
    ".turbo",
    "data",
    "logs",
    ".idea",
    ".vscode",
}

TEXT_SUFFIXES = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".md",
    ".sh",
    ".bash",
    ".sql",
    ".txt",
    ".ini",
    ".cfg",
    ".conf",
    ".example",
    ".env",
}

LOCKFILE_NAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb"}

# 高置信度密钥格式。只匹配真实格式，避免把文档中的示例全部报出来。
SECRET_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b"),
        "high",
    ),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "high"),
    (
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
        "high",
    ),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "high"),
    ("stripe-live-key", re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b"), "high"),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"), "high"),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "high"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "high"),
)

GENERIC_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|secret|token|password|passwd|access[_-]?key)\b"
    r"\s*[:=]\s*['\"]?([A-Za-z0-9_./+=\-]{16,})['\"]?"
)

PLACEHOLDER_MARKERS = (
    "replace_with",
    "replace-with",
    "placeholder",
    "changeme",
    "change_me",
    "change-me",
    "your_",
    "your-",
    "dummy",
    "fake",
    "redacted",
    "example",
    "sample",
    "todo",
    "xxxx",
    "****",
    "...",
    "<",
    ">",
    "${",
    "%(",
)

PII_COLUMNS: dict[str, tuple[str, ...]] = {
    "users": ("id", "login", "name", "email", "avatar_url"),
    "sessions": ("id", "user_id"),
    "login_attempts": ("ip_hash",),
    "recommendations": ("user_id",),
}

SENSITIVE_LOG_RE = re.compile(
    r"(?i)\b(?:logger\.(?:debug|info|warning|error|exception)|console\.(?:log|warn|error)|print)\s*\("
    r"[^\n]*(?:email|e-mail|token|cookie|authorization|password|passwd|secret|api[_-]?key)"
)


@dataclass
class Finding:
    """一条审计发现。"""

    check: str
    category: str
    severity: str
    title: str
    detail: str
    evidence: str
    recommendation: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "check": self.check,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass
class AuditContext:
    """审计上下文。"""

    root: Path
    online: bool = False
    runtime_env: Path | None = None
    timeout: int = 120
    inventory: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class AuditResult:
    """审计结果。"""

    root: Path
    findings: list[Finding]
    checks_run: int
    generated_at: str
    online: bool
    inventory: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        counts = {key: 0 for key in SEVERITY_ORDER}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        counts["total"] = len(self.findings)
        return counts

    @property
    def status(self) -> str:
        if any(f.severity in ("critical", "high") for f in self.findings):
            return "FAIL"
        if any(f.severity in ("medium", "low") for f in self.findings):
            return "WARN"
        return "PASS"

    def sorted_findings(self) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (-SEVERITY_ORDER.get(f.severity, 0), f.check, f.evidence),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "generated_at": self.generated_at,
            "online": self.online,
            "status": self.status,
            "checks_run": self.checks_run,
            "summary": self.summary,
            "inventory": self.inventory,
            "errors": self.errors,
            "findings": [f.to_dict() for f in self.sorted_findings()],
        }


# ── 通用工具 ────────────────────────────────────────────────────────


def _read_text(path: Path, max_bytes: int = 2_000_000) -> str:
    try:
        if path.stat().st_size > max_bytes:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _iter_files(root: Path, suffixes: set[str] | None = None) -> Iterator[Path]:
    """遍历仓库文件，跳过依赖 / 构建 / 缓存目录。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            if suffixes is not None:
                if path.suffix.lower() not in suffixes and path.name not in suffixes:
                    continue
            yield path


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {ch: value.count(ch) for ch in set(value)}
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _is_test_fixture(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return "tests" in parts or name.startswith("test_") or name.endswith(".test.ts") or name.endswith(".test.tsx")


def _parse_env_file(path: Path) -> dict[str, tuple[str, int]]:
    """解析 KEY=VALUE 环境文件，返回键 -> (值, 行号)。"""
    result: dict[str, tuple[str, int]] = {}
    text = _read_text(path)
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        result[key] = (value, lineno)
    return result


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _run_json(command: Sequence[str], cwd: Path, timeout: int) -> tuple[object | None, str | None]:
    """执行命令并解析 JSON；失败返回 (None, 错误信息)。"""
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    output = proc.stdout.strip()
    if not output:
        return None, (proc.stderr or f"命令退出码 {proc.returncode}，无输出").strip()
    try:
        return json.loads(output), None
    except json.JSONDecodeError as exc:
        return None, f"JSON 解析失败：{exc}"


def _git_tracked_files(root: Path) -> set[str]:
    """返回 git 跟踪的相对路径；非 git 目录返回空集合。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if proc.returncode != 0:
        return set()
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


# ── 检查：密钥与敏感文件 ────────────────────────────────────────────


def check_secrets(ctx: AuditContext) -> list[Finding]:
    """扫描源码 / 配置 / 文档中的高置信度密钥与疑似密钥赋值。"""
    findings: list[Finding] = []
    for path in _iter_files(ctx.root, TEXT_SUFFIXES):
        if path.name in LOCKFILE_NAMES:
            continue
        if _is_test_fixture(path):
            # 测试夹具允许构造假 token；真实密钥仍应通过 .env 管理。
            continue
        text = _read_text(path)
        if not text:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if len(line) > 4000:
                continue
            occupied: list[tuple[int, int]] = []
            for rule_id, regex, severity in SECRET_RULES:
                for match in regex.finditer(line):
                    value = match.group(0)
                    if _is_placeholder(value):
                        continue
                    occupied.append(match.span())
                    findings.append(
                        Finding(
                            check="secret-scan",
                            category="secret",
                            severity=severity,
                            title=f"疑似泄露的 {rule_id}",
                            detail="源码 / 配置中出现高置信度密钥格式，密钥可能已进入版本历史。",
                            evidence=f"{_rel(ctx.root, path)}:{lineno}",
                            recommendation="立即吊销并轮换该密钥，改用运行目录 .env / Worker secret 注入；清理 git 历史后复扫。",
                        )
                    )
            generic = GENERIC_SECRET_RE.search(line)
            if generic:
                value = generic.group(2)
                start, end = generic.span(2)
                if any(s <= start < e or s < end <= e for s, e in occupied):
                    continue
                if _is_placeholder(value) or _entropy(value) < 3.0 or len(set(value)) < 8:
                    continue
                findings.append(
                    Finding(
                        check="secret-scan",
                        category="secret",
                        severity="medium",
                        title="疑似硬编码凭据赋值",
                        detail=f"变量 `{generic.group(1)}` 被赋予以高熵字符串，需人工确认是否为真实密钥。",
                        evidence=f"{_rel(ctx.root, path)}:{lineno}",
                        recommendation="确认后迁移到 .env / secret 管理；若为占位符请在变量名或值中标注 example。",
                    )
                )
    return _dedupe(findings)


def check_tracked_env(ctx: AuditContext) -> list[Finding]:
    """检查 .env 是否被 git 跟踪，以及 .gitignore 是否覆盖敏感文件。"""
    findings: list[Finding] = []
    tracked = _git_tracked_files(ctx.root)
    for rel in sorted(tracked):
        name = Path(rel).name
        if name == ".env" or (name.startswith(".env.") and not name.endswith(".example")):
            findings.append(
                Finding(
                    check="tracked-env",
                    category="secret",
                    severity="high",
                    title="运行环境文件被 git 跟踪",
                    detail=f"`{rel}` 可能包含真实密钥，且已进入版本历史。",
                    evidence=rel,
                    recommendation="从索引移除并加入 .gitignore；轮换其中所有密钥；必要时清理历史。",
                )
            )
    gitignore = _read_text(ctx.root / ".gitignore")
    if gitignore:
        if not re.search(r"(?m)^\s*\*\*/?\.env\s*$|^\s*\.env\s*$", gitignore):
            findings.append(
                Finding(
                    check="tracked-env",
                    category="secret",
                    severity="medium",
                    title=".gitignore 未显式忽略 .env",
                    detail="缺少 `.env` / `**/.env` 忽略规则，运行配置存在误提交风险。",
                    evidence=".gitignore",
                    recommendation="加入 `.env`、`.env.local`、`**/.env`，并保留 `!**/.env.example`。",
                )
            )
    return findings


# ── 检查：依赖完整性与漏洞 ──────────────────────────────────────────


def check_lockfiles(ctx: AuditContext) -> list[Finding]:
    """检查 npm lockfile 完整性与 Python 依赖固定情况。"""
    findings: list[Finding] = []
    for package in ("admin", "edge"):
        path = ctx.root / package / "package-lock.json"
        if not path.exists():
            findings.append(
                Finding(
                    check="dependency-lock",
                    category="dependency",
                    severity="high",
                    title=f"{package} 缺少 package-lock.json",
                    detail="无法保证依赖可复现，CI 与生产可能安装到不同版本。",
                    evidence=f"{package}/package-lock.json",
                    recommendation="提交 package-lock.json，并在 CI 使用 `npm ci`。",
                )
            )
            continue
        try:
            data = json.loads(_read_text(path))
        except json.JSONDecodeError:
            findings.append(
                Finding(
                    check="dependency-lock",
                    category="dependency",
                    severity="high",
                    title=f"{package} package-lock.json 无法解析",
                    detail="锁文件损坏会导致依赖安装不可复现。",
                    evidence=f"{package}/package-lock.json",
                    recommendation="重新生成并提交 lockfile。",
                )
            )
            continue
        version = data.get("lockfileVersion", 0)
        if not isinstance(version, int) or version < 2:
            findings.append(
                Finding(
                    check="dependency-lock",
                    category="dependency",
                    severity="medium",
                    title=f"{package} lockfile 版本过旧",
                    detail=f"lockfileVersion={version}，缺少完整性元数据。",
                    evidence=f"{package}/package-lock.json",
                    recommendation="使用 npm 10+ 重新生成 lockfile（lockfileVersion 3）。",
                )
            )
        packages = data.get("packages", {})
        missing_integrity = 0
        http_resolved: list[str] = []
        for name, meta in packages.items():
            if not name or not isinstance(meta, dict) or meta.get("link"):
                continue
            resolved = str(meta.get("resolved", ""))
            if resolved.startswith("http://"):
                http_resolved.append(name)
            if not meta.get("integrity") and not meta.get("optional"):
                missing_integrity += 1
        if http_resolved:
            findings.append(
                Finding(
                    check="dependency-lock",
                    category="dependency",
                    severity="high",
                    title=f"{package} 依赖使用明文 HTTP 源",
                    detail=f"{len(http_resolved)} 个包从 http:// 下载，存在中间人篡改风险：{', '.join(http_resolved[:5])}",
                    evidence=f"{package}/package-lock.json",
                    recommendation="改用 https:// registry，重新生成 lockfile。",
                )
            )
        if missing_integrity:
            findings.append(
                Finding(
                    check="dependency-lock",
                    category="dependency",
                    severity="medium",
                    title=f"{package} 依赖缺少 integrity 校验",
                    detail=f"{missing_integrity} 个包没有 integrity 字段，无法校验下载内容。",
                    evidence=f"{package}/package-lock.json",
                    recommendation="使用官方 npm registry 重新生成 lockfile。",
                )
            )

    unpinned: list[str] = []
    for name in ("requirements.txt", "requirements-ml.txt"):
        path = ctx.root / "vps" / name
        if not path.exists():
            continue
        for lineno, line in enumerate(_read_text(path).splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(("--index-url", "--extra-index-url", "-i ")):
                if "http://" in stripped:
                    findings.append(
                        Finding(
                            check="dependency-lock",
                            category="dependency",
                            severity="high",
                            title="Python 依赖使用明文 HTTP 源",
                            detail="pip index 使用 http://，存在中间人篡改风险。",
                            evidence=f"vps/{name}:{lineno}",
                            recommendation="改用 https:// 源，或配置哈希校验。",
                        )
                    )
                continue
            requirement = stripped.split("#", 1)[0].strip()
            if not requirement:
                continue
            if "==" not in requirement:
                unpinned.append(requirement)
    if unpinned:
        preview = "、".join(unpinned[:6])
        findings.append(
            Finding(
                check="dependency-lock",
                category="dependency",
                severity="medium",
                title="Python 依赖未锁定精确版本",
                detail=(
                    f"{len(unpinned)} 条依赖仅声明下限（如 `{preview}`），"
                    "不同时间安装可能得到不同版本，漏洞扫描结果不可复现。"
                ),
                evidence="vps/requirements.txt",
                recommendation="生成并提交 `requirements.lock`（pip freeze / uv lock），部署使用 `-r requirements.lock`；本需求先记录为遗留项。",
            )
        )
    return findings


def _npm_audit(ctx: AuditContext, package: str) -> list[Finding]:
    path = ctx.root / package
    if not (path / "package-lock.json").exists():
        return []
    data, error = _run_json(
        ["npm", "audit", "--package-lock-only", "--json"],
        cwd=path,
        timeout=ctx.timeout,
    )
    if error or not isinstance(data, dict):
        return [
            Finding(
                check="dependency-vuln",
                category="dependency",
                severity="info",
                title=f"{package} npm audit 未执行",
                detail=f"在线依赖扫描不可用：{error or '未知错误'}",
                evidence=f"{package}/package-lock.json",
                recommendation="在可联网环境运行 `npm audit --package-lock-only`，或安装 npm 后复扫。",
            )
        ]
    findings: list[Finding] = []
    vulnerabilities = data.get("vulnerabilities", {})
    if not isinstance(vulnerabilities, dict):
        return findings
    for name, meta in vulnerabilities.items():
        if not isinstance(meta, dict):
            continue
        severity = str(meta.get("severity", "info")).lower()
        if severity not in ("high", "critical"):
            continue
        via = meta.get("via", [])
        titles: list[str] = []
        if isinstance(via, list):
            for item in via:
                if isinstance(item, dict) and item.get("title"):
                    titles.append(str(item["title"]))
        findings.append(
            Finding(
                check="dependency-vuln",
                category="dependency",
                severity=severity,
                title=f"{package} 依赖 {name} 存在 {severity} 漏洞",
                detail="；".join(titles[:3]) or f"npm audit 标记 {name} 为 {severity}。",
                evidence=f"{package}/package-lock.json",
                recommendation=f"在 {package}/ 运行 `npm audit fix`，或升级 {name} 到修复版本后重新构建 / 测试。",
            )
        )
    return findings


def _pip_audit(ctx: AuditContext) -> list[Finding]:
    executable = None
    site_packages = None
    venv = ctx.root / "vps" / ".venv"
    if (venv / "bin" / "python").exists():
        candidates = list((venv / "lib").glob("python*/site-packages"))
        if candidates:
            site_packages = candidates[0]
    for candidate in ("pip-audit",):
        found = _which(candidate)
        if found:
            executable = found
            break
    if executable is None:
        return [
            Finding(
                check="dependency-vuln",
                category="dependency",
                severity="info",
                title="pip-audit 未安装",
                detail="未找到 pip-audit，Python 依赖漏洞扫描跳过。",
                evidence="vps/requirements.txt",
                recommendation="`pip install pip-audit` 后运行 `pip-audit -r vps/requirements.txt`，或使用 `uvx pip-audit`。",
            )
        ]
    command = [executable]
    if site_packages is not None:
        command += ["--path", str(site_packages)]
    else:
        command += ["-r", str(ctx.root / "vps" / "requirements.txt")]
    command += ["--format", "json"]
    data, error = _run_json(command, cwd=ctx.root, timeout=ctx.timeout)
    if error or not isinstance(data, dict):
        return [
            Finding(
                check="dependency-vuln",
                category="dependency",
                severity="info",
                title="pip-audit 执行失败",
                detail=f"在线依赖扫描不可用：{error or '未知错误'}",
                evidence="vps/requirements.txt",
                recommendation="检查网络 / pip-audit 版本后复扫。",
            )
        ]
    findings: list[Finding] = []
    for dependency in data.get("dependencies", []):
        if not isinstance(dependency, dict):
            continue
        name = dependency.get("name", "?")
        version = dependency.get("version", "?")
        for vuln in dependency.get("vulns", []) or []:
            if not isinstance(vuln, dict):
                continue
            vuln_id = vuln.get("id", "UNKNOWN")
            fix_versions = vuln.get("fix_versions", [])
            findings.append(
                Finding(
                    check="dependency-vuln",
                    category="dependency",
                    severity="high",
                    title=f"VPS 依赖 {name}=={version} 存在漏洞 {vuln_id}",
                    detail=str(vuln.get("description", ""))[:300],
                    evidence="vps/requirements.txt",
                    recommendation=(
                        f"升级到 {', '.join(fix_versions)} 或更高版本后运行 pytest。"
                        if fix_versions
                        else "评估替换 / 缓解措施，并跟踪上游修复。"
                    ),
                )
            )
    return findings


def check_dependency_vulnerabilities(ctx: AuditContext) -> list[Finding]:
    """在线依赖漏洞扫描（--online 时启用）。"""
    if not ctx.online:
        return []
    findings: list[Finding] = []
    findings.extend(_npm_audit(ctx, "admin"))
    findings.extend(_npm_audit(ctx, "edge"))
    findings.extend(_pip_audit(ctx))
    return findings


# ── 检查：配置基线 ──────────────────────────────────────────────────


def check_production_config(ctx: AuditContext) -> list[Finding]:
    """检查生产环境模板与运行配置的安全开关。"""
    findings: list[Finding] = []
    prod_env = ctx.root / "deploy" / "env" / "openfactory.env.example"
    if prod_env.exists():
        env = _parse_env_file(prod_env)
        cors = env.get("CORS_ORIGINS")
        if not cors or not cors[0].strip():
            findings.append(
                Finding(
                    check="config-cors",
                    category="configuration",
                    severity="high",
                    title="生产模板未设置 CORS 白名单",
                    detail="CORS_ORIGINS 为空时会回退到 `*`，浏览器跨域策略失效。",
                    evidence="deploy/env/openfactory.env.example",
                    recommendation="设置为实际管理后台 origin（多个用英文逗号分隔），禁止 `*`。",
                )
            )
        elif cors[0].strip() == "*":
            findings.append(
                Finding(
                    check="config-cors",
                    category="configuration",
                    severity="high",
                    title="生产模板允许任意 CORS 来源",
                    detail="CORS_ORIGINS=* 允许任意站点携带用户凭据调用本机 API。",
                    evidence=f"deploy/env/openfactory.env.example:{cors[1]}",
                    recommendation="改为实际管理后台 origin。",
                )
            )
        rate = env.get("RATE_LIMIT_ENABLED")
        if rate and not _truthy(rate[0]):
            findings.append(
                Finding(
                    check="config-rate-limit",
                    category="configuration",
                    severity="high",
                    title="生产模板关闭了接口限流",
                    detail="RATE_LIMIT_ENABLED 为关闭值，登录 / 写接口可被高频刷取。",
                    evidence=f"deploy/env/openfactory.env.example:{rate[1]}",
                    recommendation="生产保持 RATE_LIMIT_ENABLED=1。",
                )
            )

    deploy_env = ctx.root / "deploy" / "env" / "deploy.env.example"
    if deploy_env.exists():
        env = _parse_env_file(deploy_env)
        for key in ("CLOUDFLARE_API_TOKEN", "GITHUB_CLIENT_SECRET", "SESSION_SECRET"):
            item = env.get(key)
            if item and item[0] and not _is_placeholder(item[0]):
                findings.append(
                    Finding(
                        check="config-secret-template",
                        category="configuration",
                        severity="high",
                        title=f"部署模板 {key} 疑似包含真实值",
                        detail="模板应只保存占位符，真实密钥由部署时注入。",
                        evidence=f"deploy/env/deploy.env.example:{item[1]}",
                        recommendation=f"将 {key} 改回 REPLACE_WITH_* 占位符并轮换已暴露值。",
                    )
                )

    prod_wrangler = ctx.root / "deploy" / "templates" / "wrangler.production.toml.tmpl"
    if prod_wrangler.exists():
        text = _read_text(prod_wrangler)
        if re.search(r'(?m)^\s*ALLOWED_ORIGIN\s*=\s*"\*"', text):
            findings.append(
                Finding(
                    check="config-cors",
                    category="configuration",
                    severity="high",
                    title="生产 Worker 允许任意 CORS 来源",
                    detail="ALLOWED_ORIGIN 为 * 时，任意站点可携带会话 cookie 调用边缘 API。",
                    evidence="deploy/templates/wrangler.production.toml.tmpl",
                    recommendation="渲染时填入实际管理后台 origin。",
                )
            )
        if re.search(r'(?m)^\s*RATE_LIMIT_ENABLED\s*=\s*"false"', text, re.IGNORECASE):
            findings.append(
                Finding(
                    check="config-rate-limit",
                    category="configuration",
                    severity="high",
                    title="生产 Worker 关闭了接口限流",
                    detail="RATE_LIMIT_ENABLED=false 会使 edge 限流完全失效。",
                    evidence="deploy/templates/wrangler.production.toml.tmpl",
                    recommendation="生产保持 RATE_LIMIT_ENABLED=true。",
                )
            )

    dev_wrangler = ctx.root / "edge" / "wrangler.toml"
    if dev_wrangler.exists():
        text = _read_text(dev_wrangler)
        if re.search(r'(?m)^\s*ALLOWED_ORIGIN\s*=\s*"\*"', text):
            findings.append(
                Finding(
                    check="config-cors",
                    category="configuration",
                    severity="high",
                    title="edge 开发配置允许任意 CORS 来源",
                    detail="ALLOWED_ORIGIN=* 会使本地 / 预发环境的会话可被任意站点调用。",
                    evidence="edge/wrangler.toml",
                    recommendation="改为具体前端 origin。",
                )
            )

    runtime_env = _resolve_runtime_env(ctx)
    if runtime_env is not None and runtime_env.exists():
        findings.extend(_check_runtime_env(ctx, runtime_env))
    return findings


def _resolve_runtime_env(ctx: AuditContext) -> Path | None:
    if ctx.runtime_env is not None:
        return ctx.runtime_env
    home = os.environ.get("OPENFACTORY_HOME", "").strip()
    if home:
        return Path(home) / ".env"
    return None


def _check_runtime_env(ctx: AuditContext, path: Path) -> list[Finding]:
    findings: list[Finding] = []
    env = _parse_env_file(path)
    cors = env.get("CORS_ORIGINS")
    if cors and cors[0].strip() == "*":
        findings.append(
            Finding(
                check="config-cors",
                category="configuration",
                severity="high",
                title="运行配置允许任意 CORS 来源",
                detail="生产运行 .env 中 CORS_ORIGINS=*，任意站点可调用本机 API。",
                evidence=f"{path}:{cors[1]}",
                recommendation="改为实际管理后台 origin 并重启 openfactory-api。",
            )
        )
    rate = env.get("RATE_LIMIT_ENABLED")
    if rate and not _truthy(rate[0]):
        findings.append(
            Finding(
                check="config-rate-limit",
                category="configuration",
                severity="high",
                title="运行配置关闭了接口限流",
                detail="RATE_LIMIT_ENABLED 为关闭值。",
                evidence=f"{path}:{rate[1]}",
                recommendation="改为 1 并重启服务。",
            )
        )
    token = env.get("INTERNAL_TOKEN")
    if token:
        value = token[0].strip()
        if not value:
            findings.append(
                Finding(
                    check="config-internal-token",
                    category="configuration",
                    severity="medium",
                    title="运行配置未设置内部令牌",
                    detail="INTERNAL_TOKEN 为空，内部接口鉴权关闭（仅建议本地开发）。",
                    evidence=f"{path}:{token[1]}",
                    recommendation="生产由 bootstrap-runtime.sh 生成 32 字节令牌。",
                )
            )
        elif len(value) < 32:
            findings.append(
                Finding(
                    check="config-internal-token",
                    category="configuration",
                    severity="high",
                    title="内部令牌长度不足",
                    detail=f"INTERNAL_TOKEN 长度 {len(value)}，低于 32 字符基线。",
                    evidence=f"{path}:{token[1]}",
                    recommendation="重新生成至少 32 字节随机令牌并轮换。",
                )
            )
    eager = env.get("CELERY_TASK_ALWAYS_EAGER")
    if eager and _truthy(eager[0]):
        findings.append(
            Finding(
                check="config-runtime",
                category="configuration",
                severity="medium",
                title="生产运行配置启用 Celery eager 模式",
                detail="CELERY_TASK_ALWAYS_EAGER=1 会让任务在 API 进程内同步执行，影响可用性。",
                evidence=f"{path}:{eager[1]}",
                recommendation="生产改为 0。",
            )
        )
    log_level = env.get("LOG_LEVEL")
    if log_level and log_level[0].strip().upper() == "DEBUG":
        findings.append(
            Finding(
                check="config-runtime",
                category="configuration",
                severity="low",
                title="运行日志级别为 DEBUG",
                detail="DEBUG 日志可能包含请求细节，增加隐私暴露面。",
                evidence=f"{path}:{log_level[1]}",
                recommendation="生产使用 INFO。",
            )
        )
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            findings.append(
                Finding(
                    check="config-runtime",
                    category="configuration",
                    severity="medium",
                    title="运行配置权限过宽",
                    detail=f"{path} 权限为 {oct(mode)}，其他用户可读，可能泄露密钥。",
                    evidence=str(path),
                    recommendation="chmod 600 运行目录 .env。",
                )
            )
    except OSError:
        pass
    return findings


def check_session_headers(ctx: AuditContext) -> list[Finding]:
    """检查会话 Cookie 标记与 edge 安全响应头。"""
    findings: list[Finding] = []
    auth = ctx.root / "edge" / "src" / "auth.ts"
    if auth.exists():
        text = _read_text(auth)
        for marker, title in (
            ("HttpOnly", "会话 Cookie 缺少 HttpOnly"),
            ("SameSite=Lax", "会话 Cookie 缺少 SameSite=Lax"),
            ("Secure", "会话 Cookie 缺少 Secure 分支"),
        ):
            if marker not in text:
                findings.append(
                    Finding(
                        check="session-cookie",
                        category="configuration",
                        severity="high",
                        title=title,
                        detail="Cookie 安全属性缺失会增加 XSS 窃取 / CSRF 风险。",
                        evidence="edge/src/auth.ts",
                        recommendation="在 buildSetCookie 中补齐 HttpOnly、SameSite=Lax，并在 HTTPS 下设置 Secure。",
                    )
                )
    else:
        findings.append(
            Finding(
                check="session-cookie",
                category="configuration",
                severity="high",
                title="未找到 edge 会话实现",
                detail="无法校验 Cookie 安全属性。",
                evidence="edge/src/auth.ts",
                recommendation="确认会话实现路径后更新审计规则。",
            )
        )
    index = ctx.root / "edge" / "src" / "index.ts"
    if index.exists() and "secureHeaders" not in _read_text(index):
        findings.append(
            Finding(
                check="security-headers",
                category="configuration",
                severity="high",
                title="edge 未启用安全响应头",
                detail="缺少 X-Content-Type-Options / X-Frame-Options / Referrer-Policy 等基线响应头。",
                evidence="edge/src/index.ts",
                recommendation="引入 `hono/secure-headers` 的 secureHeaders 中间件。",
            )
        )
    vps_main = ctx.root / "vps" / "app" / "main.py"
    if vps_main.exists() and "SecurityHeadersMiddleware" not in _read_text(vps_main):
        findings.append(
            Finding(
                check="security-headers",
                category="configuration",
                severity="medium",
                title="VPS 未启用安全响应头",
                detail="本机 API 响应缺少 nosniff / frame / referrer 基线头。",
                evidence="vps/app/main.py",
                recommendation="挂载 SecurityHeadersMiddleware。",
            )
        )
    return findings


# ── 检查：隐私边界 ──────────────────────────────────────────────────


def check_privacy_boundary(ctx: AuditContext) -> list[Finding]:
    """复核 PII 字段、敏感日志与保留期缺口。"""
    findings: list[Finding] = []
    inventory: list[str] = []
    for table, columns in PII_COLUMNS.items():
        inventory.append(f"{table}: {', '.join(columns)}")
    ctx.inventory["pii"] = inventory

    egress: set[str] = set()
    for path in _iter_files(ctx.root, TEXT_SUFFIXES):
        if _is_test_fixture(path):
            continue
        text = _read_text(path)
        for match in re.finditer(r"https?://([A-Za-z0-9.-]+)", text):
            host = match.group(1).lower()
            if host.endswith(("github.com", "githubusercontent.com", "deepseek.com", "cloudflare.com")):
                egress.add(host)
    ctx.inventory["egress"] = sorted(egress)

    for path in _iter_files(ctx.root, {".py", ".ts", ".tsx", ".js", ".mjs"}):
        if _is_test_fixture(path):
            continue
        text = _read_text(path)
        for lineno, line in enumerate(text.splitlines(), 1):
            if SENSITIVE_LOG_RE.search(line):
                findings.append(
                    Finding(
                        check="privacy-log",
                        category="privacy",
                        severity="high",
                        title="日志可能输出敏感字段",
                        detail="日志调用中包含 email / token / cookie / authorization / password 等关键词，需确认未打印明文。",
                        evidence=f"{_rel(ctx.root, path)}:{lineno}",
                        recommendation="改为记录脱敏标识（如 user_id / 哈希前缀），禁止打印完整 token / cookie / 邮箱。",
                    )
                )

    # 保留期清单：security 数据由 edge 清理任务处理，业务 PII 尚无删除 / 导出接口（M9-06）。
    ctx.inventory["retention"] = [
        "sessions: 30 天（edge auth.ts SESSION_TTL_SECONDS）",
        "login_attempts: 30 天（edge security cleanup）",
        "security_events: 90 天（edge security cleanup）",
        "trending_snapshots: TRENDING_RETENTION_DAYS=90",
        "users / recommendations: 未定义自动清理，待 M9-06",
    ]
    api_text = ""
    for path in (ctx.root / "vps" / "app" / "api").glob("*.py"):
        api_text += _read_text(path)
    edge_routes = ""
    for path in (ctx.root / "edge" / "src" / "routes").glob("*.ts"):
        edge_routes += _read_text(path)
    has_delete = bool(re.search(r"@router\.(delete|get)\([^)]*(?:export|delete|erase|purge)", api_text, re.IGNORECASE))
    has_delete = has_delete or bool(re.search(r"\.(?:delete|get)\(['\"][^'\"]*(?:export|delete|erase|purge)", edge_routes, re.IGNORECASE))
    if not has_delete:
        findings.append(
            Finding(
                check="privacy-lifecycle",
                category="privacy",
                severity="medium",
                title="缺少用户数据导出 / 删除接口",
                detail="users / sessions / recommendations 中的个人数据目前只能人工清理，不满足数据主体权利请求。",
                evidence="vps/app/api, edge/src/routes",
                recommendation="按 M9-06 数据保留与隐私策略落地，补充导出 / 删除接口与审计记录。",
            )
        )
    return findings


# ── 汇总 ────────────────────────────────────────────────────────────


def _dedupe(findings: Iterable[Finding]) -> list[Finding]:
    seen: set[tuple[str, str, str]] = set()
    result: list[Finding] = []
    for finding in findings:
        key = (finding.check, finding.evidence, finding.title)
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return result


def _which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


CHECKS = (
    check_secrets,
    check_tracked_env,
    check_lockfiles,
    check_production_config,
    check_session_headers,
    check_privacy_boundary,
    check_dependency_vulnerabilities,
)


def run_audit(ctx: AuditContext) -> AuditResult:
    findings: list[Finding] = []
    errors: list[str] = []
    checks_run = 0
    for check in CHECKS:
        try:
            findings.extend(check(ctx))
            checks_run += 1
        except Exception as exc:  # 审计工具本身不能因单条检查崩溃
            errors.append(f"{check.__name__}: {exc}")
    return AuditResult(
        root=ctx.root,
        findings=_dedupe(findings),
        checks_run=checks_run,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        online=ctx.online,
        inventory=ctx.inventory,
        errors=errors,
    )


def render_text(result: AuditResult) -> str:
    lines: list[str] = []
    lines.append("OpenFactory 安全审计报告")
    lines.append("=" * 60)
    lines.append(f"根目录: {result.root}")
    lines.append(f"生成时间: {result.generated_at}")
    lines.append(f"模式: {'在线（含依赖漏洞扫描）' if result.online else '离线（静态检查）'}")
    lines.append(f"结果: {result.status}")
    lines.append(f"检查项: {result.checks_run}")
    summary = result.summary
    lines.append(
        "发现: "
        + " / ".join(
            f"{SEVERITY_LABEL[key]} {summary[key]}"
            for key in ("critical", "high", "medium", "low", "info")
        )
        + f" / 合计 {summary['total']}"
    )
    if result.inventory:
        lines.append("")
        lines.append("清单:")
        for key in ("pii", "egress", "retention"):
            values = result.inventory.get(key)
            if not values:
                continue
            lines.append(f"- {key}:")
            for value in values:
                lines.append(f"  - {value}")
    if result.findings:
        lines.append("")
        lines.append("发现明细:")
        for finding in result.sorted_findings():
            lines.append(
                f"[{SEVERITY_LABEL.get(finding.severity, finding.severity.upper())}] "
                f"{finding.check} · {finding.title}"
            )
            lines.append(f"  证据: {finding.evidence}")
            lines.append(f"  说明: {finding.detail}")
            if finding.recommendation:
                lines.append(f"  建议: {finding.recommendation}")
    else:
        lines.append("")
        lines.append("未发现需要处理的问题。")
    if result.errors:
        lines.append("")
        lines.append("检查执行错误:")
        for error in result.errors:
            lines.append(f"- {error}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.security_audit",
        description="OpenFactory 安全审计（依赖 / 配置 / 隐私边界，只读）",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="仓库根目录（默认：本文件所在仓库根）",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    parser.add_argument("--output", type=Path, help="写入报告文件（默认 stdout）")
    parser.add_argument("--online", action="store_true", help="启用 npm audit / pip-audit 在线依赖扫描")
    parser.add_argument(
        "--runtime-env",
        type=Path,
        help="额外检查真实运行 .env（默认读取 $OPENFACTORY_HOME/.env）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="存在 high / critical 时退出码 1（默认仅 critical）",
    )
    parser.add_argument("--timeout", type=int, default=120, help="在线命令超时秒数（默认 120）")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"错误：根目录不存在：{root}", file=sys.stderr)
        return 2
    ctx = AuditContext(
        root=root,
        online=args.online,
        runtime_env=args.runtime_env.resolve() if args.runtime_env else None,
        timeout=max(1, args.timeout),
    )
    result = run_audit(ctx)
    payload = json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n" if args.json else render_text(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"报告已写入 {args.output}")
    else:
        sys.stdout.write(payload)
    has_critical = any(f.severity == "critical" for f in result.findings)
    has_high = any(f.severity == "high" for f in result.findings)
    if has_critical or (args.strict and has_high):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
