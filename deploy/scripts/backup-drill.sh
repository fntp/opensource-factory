#!/usr/bin/env bash
# 恢复演练：SQLite 快照 + 最新 D1 导出（REQ-202610-0942 / M5-04）
#
# 用法：
#   deploy/scripts/backup-drill.sh [--env-file <path>] [--name <snapshot>]
#                                   [--skip-d1] [--dry-run]
#
# 演练只恢复到临时库，不触碰生产数据库；D1 导出会导入临时 SQLite 校验。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
NAME=""
SKIP_D1=0
DRY_RUN=0

usage() {
  sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --name) NAME="${2:?--name 需要值}"; shift 2 ;;
    --skip-d1) SKIP_D1=1; shift ;;
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

PYTHON_BIN="${PYTHON_BIN:-$APP_DIR/vps/.venv/bin/python}"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="python3"

SQLITE_ARGS=(drill --backup-dir "$BACKUP_DIR")
[[ -n "$NAME" ]] && SQLITE_ARGS+=(--name "$NAME")

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "DRY-RUN 将执行：cd $APP_DIR/vps && $PYTHON_BIN -m app.backup ${SQLITE_ARGS[*]}"
  [[ "$SKIP_D1" -eq 0 ]] && log "DRY-RUN 将校验最新 D1 导出（若存在）"
  exit 0
fi

cd "$APP_DIR/vps"
log "执行 SQLite 恢复演练"
"$PYTHON_BIN" -m app.backup "${SQLITE_ARGS[@]}"

if [[ "$SKIP_D1" -eq 0 ]]; then
  D1_FILES="$("$PYTHON_BIN" -m app.backup list --backup-dir "$BACKUP_DIR" --kind d1 --json)"
  if [[ "$D1_FILES" != "[]" && -n "$D1_FILES" ]]; then
    log "校验最新 D1 导出"
    "$PYTHON_BIN" -m app.backup verify-d1 --backup-dir "$BACKUP_DIR"
  else
    log "暂无 D1 导出，跳过"
  fi
fi
log "恢复演练完成"
