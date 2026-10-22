#!/usr/bin/env bash
# 一次完成 SQLite 快照 + D1 导出 + 恢复演练（REQ-202610-0942 / M5-04）
#
# 用法：
#   deploy/scripts/backup-all.sh [--env-file <path>] [--label <name>]
#                                [--skip-d1] [--skip-sqlite] [--skip-drill] [--dry-run]
#
# 建议由 cron / systemd timer 每日调用；任一步失败不影响其他步骤，最终以非零退出码告警。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
LABEL=""
SKIP_D1=0
SKIP_SQLITE=0
SKIP_DRILL=0
DRY_RUN=0

usage() {
  sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --label) LABEL="${2:?--label 需要值}"; shift 2 ;;
    --skip-d1) SKIP_D1=1; shift ;;
    --skip-sqlite) SKIP_SQLITE=1; shift ;;
    --skip-drill) SKIP_DRILL=1; shift ;;
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

FAILED=0
COMMON_ARGS=(--env-file "$ENV_FILE")
[[ "$DRY_RUN" -eq 1 ]] && COMMON_ARGS+=(--dry-run)

if [[ "$SKIP_SQLITE" -eq 0 ]]; then
  log "=== 1/3 SQLite 快照 ==="
  CREATE_ARGS=(create --backup-dir "$BACKUP_DIR")
  [[ -n "$LABEL" ]] && CREATE_ARGS+=(--label "$LABEL")
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "DRY-RUN 将执行：cd $APP_DIR/vps && $PYTHON_BIN -m app.backup ${CREATE_ARGS[*]}"
  elif ! (cd "$APP_DIR/vps" && "$PYTHON_BIN" -m app.backup "${CREATE_ARGS[@]}"); then
    warn "SQLite 快照失败"
    FAILED=1
  fi
fi

if [[ "$SKIP_D1" -eq 0 ]]; then
  log "=== 2/3 D1 导出 ==="
  D1_ARGS=("${COMMON_ARGS[@]}")
  [[ -n "$LABEL" ]] && D1_ARGS+=(--label "$LABEL")
  if ! bash "$SCRIPT_DIR/backup-d1.sh" "${D1_ARGS[@]}"; then
    warn "D1 导出失败（不影响 SQLite 快照）"
    FAILED=1
  fi
fi

if [[ "$SKIP_DRILL" -eq 0 ]]; then
  log "=== 3/3 恢复演练 ==="
  DRILL_ARGS=("${COMMON_ARGS[@]}")
  if ! bash "$SCRIPT_DIR/backup-drill.sh" "${DRILL_ARGS[@]}"; then
    warn "恢复演练失败"
    FAILED=1
  fi
fi

if [[ "$FAILED" -ne 0 ]]; then
  warn "备份流程存在失败项，请检查上方日志"
  exit 1
fi
log "备份流程全部完成：$BACKUP_DIR"
