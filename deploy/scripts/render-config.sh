#!/usr/bin/env bash
# 渲染生产配置模板（REQ-202610-0939 / M5-01）
#
# 用法：
#   deploy/scripts/render-config.sh [--env-file <path>] [--wrangler-out <path>]
#                                   [--caddy-out <path>] [--dry-run]
#
# 输出：
#   - edge/wrangler.production.toml（默认，权限 600，已被 .gitignore 忽略）
#   - $OPENFACTORY_HOME/etc/Caddyfile（默认，权限 600）
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
WRANGLER_OUT="$APP_DIR/edge/wrangler.production.toml"
CADDY_OUT=""
DRY_RUN=0

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --wrangler-out) WRANGLER_OUT="${2:?--wrangler-out 需要路径}"; shift 2 ;;
    --caddy-out) CADDY_OUT="${2:?--caddy-out 需要路径}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

ENV_FILE="$(resolve_env_file "$ENV_FILE" "$DRY_RUN")"
log "部署配置：$ENV_FILE"
load_env_file "$ENV_FILE"

CADDY_OUT="${CADDY_OUT:-${OPENFACTORY_HOME:-/opt/openfactory}/etc/Caddyfile}"

for key in WORKER_NAME D1_DATABASE_NAME D1_DATABASE_ID VECTORIZE_INDEX_NAME \
  ADMIN_ORIGIN API_ORIGIN VPS_NODE_URL GITHUB_CLIENT_ID; do
  require_var "$key"
  if is_placeholder "${!key}"; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      warn "$key 仍为占位符（dry-run 仅提示）"
    else
      die "$key 仍为占位符，无法渲染生产配置"
    fi
  fi
done

API_ORIGIN_HOST="$(url_host "$API_ORIGIN")"
VPS_DOMAIN="$(url_host "$VPS_NODE_URL")"
CADDY_EMAIL="${CADDY_EMAIL:-admin@$VPS_DOMAIN}"
[[ -n "$API_ORIGIN_HOST" ]] || die "无法从 API_ORIGIN 解析域名"
[[ -n "$VPS_DOMAIN" ]] || die "无法从 VPS_NODE_URL 解析域名"

render_template() {
  local template="$1" out="$2"
  shift 2
  local content
  content="$(cat "$template")"
  local pair key value
  for pair in "$@"; do
    key="${pair%%=*}"
    value="${pair#*=}"
    content="${content//@${key}@/$value}"
  done
  if grep -qE '@[A-Z][A-Z0-9_]*@' <<<"$content"; then
    die "模板 $template 仍有未替换占位符"
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "DRY-RUN 将写入 $out（$(wc -c <<<"$content") 字节）"
    return 0
  fi
  mkdir -p "$(dirname "$out")"
  printf '%s\n' "$content" > "$out"
  chmod 600 "$out"
  log "已渲染：$out（600）"
}

log "Worker：$WORKER_NAME；D1：$D1_DATABASE_NAME；API：$API_ORIGIN_HOST"
log "VPS 域名：$VPS_DOMAIN；admin：$ADMIN_ORIGIN"

render_template "$DEPLOY_DIR/templates/wrangler.production.toml.tmpl" "$WRANGLER_OUT" \
  "WORKER_NAME=$WORKER_NAME" \
  "D1_DATABASE_NAME=$D1_DATABASE_NAME" \
  "D1_DATABASE_ID=$D1_DATABASE_ID" \
  "VECTORIZE_INDEX_NAME=$VECTORIZE_INDEX_NAME" \
  "ADMIN_ORIGIN=$ADMIN_ORIGIN" \
  "GITHUB_CLIENT_ID=$GITHUB_CLIENT_ID" \
  "VPS_NODE_URL=$VPS_NODE_URL" \
  "API_ORIGIN_HOST=$API_ORIGIN_HOST"

render_template "$DEPLOY_DIR/templates/Caddyfile.tmpl" "$CADDY_OUT" \
  "VPS_DOMAIN=$VPS_DOMAIN" \
  "CADDY_EMAIL=$CADDY_EMAIL"

log "渲染完成"
