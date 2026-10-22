#!/usr/bin/env bash
# 部署 Cloudflare Workers 边缘 API（REQ-202610-0939 / M5-01）
#
# 用法：
#   deploy/scripts/deploy-edge.sh [--env-file <path>] [--skip-install]
#                                 [--skip-smoke] [--dry-run]
#
# 流程：预检 → 渲染生产配置 → 写入 Worker 机密 → D1 远端迁移 → wrangler deploy → /healthz 冒烟。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
SKIP_INSTALL=0
SKIP_SMOKE=0
DRY_RUN=0

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --skip-smoke) SKIP_SMOKE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

ENV_FILE="$(resolve_env_file "$ENV_FILE" "$DRY_RUN")"
PREFLIGHT_ARGS=(--env-file "$ENV_FILE" --target edge)
[[ "$DRY_RUN" -eq 1 ]] && PREFLIGHT_ARGS+=(--dry-run)
bash "$SCRIPT_DIR/preflight.sh" "${PREFLIGHT_ARGS[@]}"

load_env_file "$ENV_FILE"
WRANGLER_CONFIG="$APP_DIR/edge/wrangler.production.toml"

RENDER_ARGS=(--env-file "$ENV_FILE" --wrangler-out "$WRANGLER_CONFIG")
[[ "$DRY_RUN" -eq 1 ]] && RENDER_ARGS+=(--dry-run)
bash "$SCRIPT_DIR/render-config.sh" "${RENDER_ARGS[@]}"

# 内部令牌：优先运行目录 .env，保证 edge 与 VPS 一致
runtime_env="${OPENFACTORY_HOME:-/opt/openfactory}/.env"
INTERNAL_TOKEN_VALUE="${INTERNAL_TOKEN:-}"
if [[ -z "$INTERNAL_TOKEN_VALUE" && -f "$runtime_env" ]]; then
  INTERNAL_TOKEN_VALUE="$(read_env_value "$runtime_env" INTERNAL_TOKEN)"
fi
if [[ ${#INTERNAL_TOKEN_VALUE} -lt 16 ]]; then
  die "INTERNAL_TOKEN 未就绪（先初始化运行目录或显式提供）"
fi

cd "$APP_DIR/edge"

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  log "安装 edge 依赖（npm ci）"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "DRY-RUN 跳过 npm ci"
  else
    run_heavy npm ci
  fi
fi

put_secret() {
  local name="$1" value="$2"
  [[ -n "$value" ]] || die "机密 $name 为空"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "DRY-RUN 将写入 Worker 机密 $name（不回显）"
    return 0
  fi
  log "写入 Worker 机密 $name"
  printf '%s' "$value" | npx wrangler secret put "$name" --config "$WRANGLER_CONFIG" >/dev/null
}

put_secret GITHUB_CLIENT_SECRET "$GITHUB_CLIENT_SECRET"
put_secret SESSION_SECRET "$SESSION_SECRET"
put_secret INTERNAL_TOKEN "$INTERNAL_TOKEN_VALUE"

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "DRY-RUN 将执行：wrangler d1 migrations apply $D1_DATABASE_NAME --remote"
  log "DRY-RUN 将执行：wrangler deploy --config $WRANGLER_CONFIG"
else
  log "应用 D1 远端迁移：$D1_DATABASE_NAME"
  npx wrangler d1 migrations apply "$D1_DATABASE_NAME" --remote --config "$WRANGLER_CONFIG"

  log "发布 Worker：$WORKER_NAME"
  npx wrangler deploy --config "$WRANGLER_CONFIG"
fi

if [[ "$SKIP_SMOKE" -eq 0 ]]; then
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "DRY-RUN 将冒烟：$API_ORIGIN/healthz"
  else
    log "冒烟检查：$API_ORIGIN/healthz"
    curl -fsS --max-time 10 "$API_ORIGIN/healthz" >/dev/null || die "edge /healthz 检查失败"
    log "edge 部署完成"
  fi
fi
