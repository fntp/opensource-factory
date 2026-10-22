"""运行目录与部署基线自检（REQ-202610-0893）。

仅使用标准库，便于在未安装应用依赖的系统 Python 下直接运行：

    cd vps
    python3 -m app.runtime layout --home /opt/openfactory
    python3 -m app.runtime check  --home /opt/openfactory --services

`check` 的检查项与 `deploy/scripts/bootstrap-runtime.sh` 创建的布局一一对应；
`--services` 会额外探测 Redis 端口（默认不探测，便于开发机 / CI 使用）。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_HOME = Path(os.environ.get("OPENFACTORY_HOME", "/opt/openfactory"))

SUBDIRS: tuple[str, ...] = ("etc", "data", "data/redis", "logs", "backups", "run")

# 与 app.config.Settings 字段保持一致；tests/test_deploy_assets.py 会校验不漂移。
REQUIRED_ENV_KEYS: tuple[str, ...] = (
    "APP_NAME",
    "VERSION",
    "LOG_LEVEL",
    "LOG_DIR",
    "DATABASE_URL",
    "REDIS_URL",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "EMBEDDING_MODEL",
    "EMBEDDING_FORCE_FALLBACK",
    "VECTORIZE_BATCH_SIZE",
    "VECTORIZE_MAX_PER_RUN",
    "VECTORIZE_AUTO",
    "EDGE_BASE_URL",
    "VECTORIZE_SYNC_ENABLED",
    "VECTORIZE_INDEX_NAME",
    "VECTORIZE_INDEX_DIM",
    "VECTORIZE_SYNC_BATCH_SIZE",
    "VECTORIZE_SYNC_MAX_PER_RUN",
    "VECTORIZE_SYNC_MAX_RETRIES",
    "VECTORIZE_SYNC_RETRY_BASE_MS",
    "VECTORIZE_SYNC_TIMEOUT_SECONDS",
    "VECTORIZE_SYNC_DELETE_ORPHANS",
    "VECTORIZE_SYNC_MAX_ORPHANS",
    "RECOMMEND_MIN_SCORE",
    "RECOMMEND_DAILY_TOP_K",
    "RECOMMEND_CANDIDATE_LIMIT",
    "RECOMMEND_SIMILARITY_WEIGHT",
    "RECOMMEND_TRENDING_WEIGHT",
    "EVAL_MATCH_THRESHOLD",
    "EVAL_QUALITY_THRESHOLD",
    "EVAL_REPO_WEIGHT",
    "EVAL_REASON_WEIGHT",
    "EMAIL_ENABLED",
    "EMAIL_SMTP_HOST",
    "EMAIL_SMTP_PORT",
    "EMAIL_SMTP_USERNAME",
    "EMAIL_SMTP_PASSWORD",
    "EMAIL_FROM",
    "EMAIL_FROM_NAME",
    "EMAIL_TO",
    "EMAIL_STARTTLS",
    "EMAIL_SSL",
    "EMAIL_TIMEOUT_SECONDS",
    "EMAIL_MAX_RETRIES",
    "EMAIL_RETRY_BASE_SECONDS",
    "EMAIL_DAILY_LIMIT",
    "EMAIL_DIGEST_WINDOW_HOURS",
    "BARK_ENABLED",
    "BARK_SERVER_URL",
    "BARK_DEVICE_KEY",
    "BARK_GROUP",
    "BARK_SOUND",
    "BARK_ICON",
    "BARK_LEVEL",
    "BARK_TIMEOUT_SECONDS",
    "BARK_MAX_PER_RUN",
    "BARK_DRY_RUN",

    "TELEGRAM_ENABLED",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_API_BASE",
    "TELEGRAM_TIMEOUT_SECONDS",
    "TELEGRAM_MAX_RETRIES",
    "TELEGRAM_RETRY_BASE_SECONDS",
    "TELEGRAM_DAILY_LIMIT",
    "TELEGRAM_DIGEST_WINDOW_HOURS",
    "INTERNAL_TOKEN",
    "CELERY_TASK_ALWAYS_EAGER",
    "GITHUB_TOKEN",
    "CORS_ORIGINS",
)

PLACEHOLDER_MARKERS: tuple[str, ...] = ("CHANGE_ME", "REPLACE_WITH", "<your")


@dataclass(frozen=True)
class CheckResult:
    """单项检查结果。"""

    name: str
    ok: bool
    detail: str


def parse_env_file(path: Path) -> dict[str, str]:
    """解析 KEY=VALUE 形式的 .env（忽略注释与空行，不去除引号）。"""
    values: dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _is_private(mode: int) -> bool:
    """仅属主可访问（不向 group / other 开放任何权限）。"""
    return mode & 0o077 == 0


def check_runtime(home: Path = DEFAULT_HOME, *, services: bool = False) -> list[CheckResult]:
    """校验运行目录基线，返回逐项结果（不抛异常）。"""
    home = Path(home)
    results: list[CheckResult] = []

    if not home.exists():
        results.append(CheckResult("home", False, f"运行目录不存在：{home}"))
        return results
    if not home.is_dir():
        results.append(CheckResult("home", False, f"不是目录：{home}"))
        return results
    results.append(CheckResult("home", True, str(home)))

    mode = stat.S_IMODE(home.stat().st_mode)
    results.append(
        CheckResult("home_permissions", _is_private(mode), f"{oct(mode)}（期望 700 或更严格）")
    )

    missing = [name for name in SUBDIRS if not (home / name).is_dir()]
    results.append(
        CheckResult("layout", not missing, "齐全" if not missing else f"缺少：{', '.join(missing)}")
    )

    env_path = home / ".env"
    if not env_path.is_file():
        results.append(CheckResult("env_file", False, f"缺少 {env_path}"))
        return results
    env_mode = stat.S_IMODE(env_path.stat().st_mode)
    results.append(
        CheckResult("env_permissions", _is_private(env_mode), f"{oct(env_mode)}（期望 600）")
    )

    env = parse_env_file(env_path)
    missing_keys = [key for key in REQUIRED_ENV_KEYS if key not in env]
    results.append(
        CheckResult(
            "env_keys",
            not missing_keys,
            "齐全" if not missing_keys else f"缺少：{', '.join(missing_keys)}",
        )
    )

    placeholders = sorted(
        key for key, value in env.items() if any(marker in value for marker in PLACEHOLDER_MARKERS)
    )
    results.append(
        CheckResult(
            "env_placeholders",
            not placeholders,
            "无占位符" if not placeholders else f"仍为占位符：{', '.join(placeholders)}",
        )
    )

    token = env.get("INTERNAL_TOKEN", "")
    results.append(
        CheckResult(
            "internal_token",
            len(token) >= 16,
            "已生成" if len(token) >= 16 else "为空或过短（应使用 openssl rand -hex 32 生成）",
        )
    )

    data_dir = home / "data"
    results.append(
        CheckResult("data_writable", data_dir.is_dir() and os.access(data_dir, os.W_OK), str(data_dir))
    )

    if services:
        results.append(_check_redis(env.get("REDIS_URL", "")))

    return results


def _check_redis(redis_url: str) -> CheckResult:
    """探测 Redis TCP 端口（不发送协议命令，避免依赖 redis 客户端）。"""
    parsed = urlparse(redis_url or "")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=2):
            return CheckResult("redis", True, f"{host}:{port} 可连接")
    except OSError as exc:
        return CheckResult("redis", False, f"{host}:{port} 不可连接：{exc}")


def render_layout(home: Path = DEFAULT_HOME) -> str:
    """以文本树形式展示运行目录布局。"""
    home = Path(home)
    lines = [f"{home}/"]
    for name in SUBDIRS:
        path = home / name
        state = "存在" if path.is_dir() else "缺失"
        lines.append(f"├── {name}/  ({state})")
    env_path = home / ".env"
    env_state = "存在" if env_path.is_file() else "缺失"
    lines.append(f"└── .env  ({env_state})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.runtime",
        description="OpenFactory 运行目录与部署基线自检",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    layout_parser = subparsers.add_parser("layout", help="打印运行目录布局")
    layout_parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="运行目录")

    check_parser = subparsers.add_parser("check", help="校验运行目录基线")
    check_parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="运行目录")
    check_parser.add_argument("--services", action="store_true", help="额外探测 Redis 连通性")
    check_parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")

    args = parser.parse_args(argv)

    if args.command == "layout":
        print(render_layout(args.home))
        return 0

    results = check_runtime(args.home, services=args.services)
    if args.json:
        print(json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2))
    else:
        for item in results:
            print(f"[{'OK' if item.ok else 'FAIL'}] {item.name}: {item.detail}")
    return 0 if all(item.ok for item in results) else 1


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    sys.exit(main())
