#!/usr/bin/env bash
# OpenFactory 安全审计入口（REQ-202610-0946 / M5-08）
#
# 用法：
#   deploy/scripts/security-audit.sh [--online] [--strict] [--json] [--output <path>]
#                                    [--runtime-env <path>] [--timeout <seconds>]
#
# 默认离线只读：检查依赖完整性、密钥泄露、配置基线、Cookie / 响应头与隐私边界。
# --online 额外执行 npm audit / pip-audit（需要网络与对应工具）。
# --strict 在 high / critical 时退出码 1，可直接用于 CI 门禁。
set -euo pipefail

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

if [[ -x "$APP_DIR/vps/.venv/bin/python" ]]; then
  PYTHON="$APP_DIR/vps/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

cd "$APP_DIR/vps"
exec "$PYTHON" -m app.security_audit --root "$APP_DIR" "$@"
