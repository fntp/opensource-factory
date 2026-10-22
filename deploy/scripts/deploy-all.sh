#!/usr/bin/env bash
# 一键部署 OpenFactory 三端（REQ-202610-0939 / M5-01）
#
# 用法：
#   deploy/scripts/deploy-all.sh [--env-file <path>] [--dry-run]
#                                [--skip-edge] [--skip-admin] [--skip-vps]
#
# 顺序：预检 → edge（D1 迁移 + Worker）→ admin（Pages）→ vps（systemd）→ 三端冒烟。
# 任一步失败立即停止；重活由各子脚本串行执行，不并发。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
DRY_RUN=0
SKIP_EDGE=0
SKIP_ADMIN=0
SKIP_VPS=0

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --skip-edge) SKIP_EDGE=1; shift ;;
    --skip-admin) SKIP_ADMIN=1; shift ;;
    --skip-vps) SKIP_VPS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

ENV_FILE="$(resolve_env_file "$ENV_FILE" "$DRY_RUN")"
COMMON_ARGS=(--env-file "$ENV_FILE")
if [[ "$DRY_RUN" -eq 1 ]]; then COMMON_ARGS+=(--dry-run); fi

PREFLIGHT_ARGS=(--env-file "$ENV_FILE" --target all)
if [[ "$DRY_RUN" -eq 1 ]]; then PREFLIGHT_ARGS+=(--dry-run); fi
bash "$SCRIPT_DIR/preflight.sh" "${PREFLIGHT_ARGS[@]}"

if [[ "$SKIP_EDGE" -eq 0 ]]; then
  log "=== 1/3 部署 edge（Cloudflare Workers）==="
  bash "$SCRIPT_DIR/deploy-edge.sh" "${COMMON_ARGS[@]}"
else
  log "=== 1/3 跳过 edge ==="
fi

if [[ "$SKIP_ADMIN" -eq 0 ]]; then
  log "=== 2/3 部署 admin（Cloudflare Pages）==="
  bash "$SCRIPT_DIR/deploy-admin.sh" "${COMMON_ARGS[@]}" --create-project
else
  log "=== 2/3 跳过 admin ==="
fi

if [[ "$SKIP_VPS" -eq 0 ]]; then
  log "=== 3/3 部署 VPS 节点 ==="
  bash "$SCRIPT_DIR/deploy-vps.sh" "${COMMON_ARGS[@]}"
else
  log "=== 3/3 跳过 VPS ==="
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "DRY-RUN 将执行三端冒烟测试"
else
  log "=== 三端冒烟测试 ==="
  bash "$SCRIPT_DIR/smoke-test.sh" --env-file "$ENV_FILE"
fi

log "全部部署完成"
