#!/usr/bin/env bash
# OpenFactory 部署基线自检入口（REQ-202610-0893）
#
# 用法：
#   deploy/scripts/doctor.sh [--home /opt/openfactory] [--services] [--json]
#
# 优先使用 vps/.venv 中的 Python；未建虚拟环境时退回系统 python3（模块仅依赖标准库）。
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
exec "$PYTHON" -m app.runtime check --home "$RUNTIME_DIR" "$@"
