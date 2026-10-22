#!/usr/bin/env bash
# OpenFactory 资源预算实测入口（REQ-202610-0944 / M5-06）
#
# 用法：
#   deploy/scripts/resource-budget.sh [--home /opt/openfactory] [--json] [--strict]
#   deploy/scripts/resource-budget.sh --no-services --json
#
# 只读采集：不启动 / 停止服务，不修改任何配置。优先使用 vps/.venv 中的 Python；
# 未建虚拟环境时退回系统 python3（模块仅依赖标准库）。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
RUNTIME_DIR="${OPENFACTORY_HOME:-/opt/openfactory}"

if [[ -x "$APP_DIR/vps/.venv/bin/python" ]]; then
  PYTHON="$APP_DIR/vps/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

cd "$APP_DIR/vps"
exec "$PYTHON" -m app.resource_budget check --home "$RUNTIME_DIR" --repo "$APP_DIR" "$@"
