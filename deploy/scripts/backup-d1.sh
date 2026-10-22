#!/usr/bin/env bash
# 导出 Cloudflare D1 并归档（REQ-202610-0942 / M5-04）
#
# 用法：
#   deploy/scripts/backup-d1.sh [--env-file <path>] [--label <name>]
#                               [--keep <n>] [--max-total-mb <n>] [--dry-run]
#
# 说明：需要部署控制面的 Cloudflare 凭据（deploy.env）与 edge 依赖（wrangler）。
# 导出文件先落到临时目录，校验通过后才归档为 backups/d1/d1-*.sql.gz。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
LABEL=""
KEEP=""
MAX_TOTAL_MB=""
DRY_RUN=0
RAW_FILE=""

usage() {
  sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

cleanup() {
  if [[ -n "$RAW_FILE" && -f "$RAW_FILE" ]]; then
    rm -f "$RAW_FILE"
  fi
  return 0
}
trap cleanup EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --label) LABEL="${2:?--label 需要值}"; shift 2 ;;
    --keep) KEEP="${2:?--keep 需要数字}"; shift 2 ;;
    --max-total-mb) MAX_TOTAL_MB="${2:?--max-total-mb 需要数字}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

ENV_FILE="$(resolve_env_file "$ENV_FILE" "$DRY_RUN")"
load_env_file "$ENV_FILE"
export OPENFACTORY_HOME="${OPENFACTORY_HOME:-/opt/openfactory}"
runtime_env="$OPENFACTORY_HOME/.env"
if [[ -f "$runtime_env" ]]; then
  load_env_file "$runtime_env"
fi
BACKUP_DIR="${BACKUP_DIR:-$OPENFACTORY_HOME/backups}"
export BACKUP_DIR
require_var D1_DATABASE_NAME "deploy.env 中的 D1 数据库名"

WRANGLER_CONFIG="$APP_DIR/edge/wrangler.production.toml"
RENDER_ARGS=(--env-file "$ENV_FILE" --wrangler-out "$WRANGLER_CONFIG")
[[ "$DRY_RUN" -eq 1 ]] && RENDER_ARGS+=(--dry-run)
bash "$SCRIPT_DIR/render-config.sh" "${RENDER_ARGS[@]}"

PYTHON_BIN="${PYTHON_BIN:-$APP_DIR/vps/.venv/bin/python}"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="python3"
CLI_ARGS=(finalize-d1 --backup-dir "$BACKUP_DIR" --database-name "$D1_DATABASE_NAME")
[[ -n "$LABEL" ]] && CLI_ARGS+=(--label "$LABEL")
[[ -n "$KEEP" ]] && CLI_ARGS+=(--keep "$KEEP")
[[ -n "$MAX_TOTAL_MB" ]] && CLI_ARGS+=(--max-total-mb "$MAX_TOTAL_MB")
for table in users sessions categories my_repositories repo_tags tags recommendations recommendation_feedback trending_repositories trending_snapshots; do
  CLI_ARGS+=(--expected-table "$table")
done

RAW_FILE="$(mktemp "${TMPDIR:-/tmp}/openfactory-d1-export-XXXXXX.sql")"

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "DRY-RUN 将执行：npx wrangler d1 export $D1_DATABASE_NAME --remote --output <临时文件> --config $WRANGLER_CONFIG"
  log "DRY-RUN 将执行：cd $APP_DIR/vps && $PYTHON_BIN -m app.backup ${CLI_ARGS[*]} --raw <临时文件>"
  exit 0
fi

require_cmd npx
cd "$APP_DIR/edge"
log "导出 D1：$D1_DATABASE_NAME"
npx wrangler d1 export "$D1_DATABASE_NAME" --remote --output "$RAW_FILE" --config "$WRANGLER_CONFIG"
[[ -s "$RAW_FILE" ]] || die "D1 导出为空：$D1_DATABASE_NAME"

cd "$APP_DIR/vps"
log "校验并归档 D1 导出"
"$PYTHON_BIN" -m app.backup "${CLI_ARGS[@]}" --raw "$RAW_FILE"
log "D1 备份完成：$BACKUP_DIR/d1"
