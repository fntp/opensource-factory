#!/usr/bin/env bash
# 受保护的 SQLite 恢复（REQ-202610-0942 / M5-04）
#
# 用法：
#   deploy/scripts/restore-sqlite.sh --name <snapshot> --target <db-path>
#                                    [--force] [--stop-services] [--env-file <path>] [--dry-run]
#
# 注意：恢复生产库前必须停 openfactory-api / worker / beat；--force 覆盖前会自动生成
# pre-restore 安全快照。默认拒绝覆盖现有目标库。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
NAME=""
TARGET=""
FORCE=0
STOP_SERVICES=0
DRY_RUN=0

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --name) NAME="${2:?--name 需要值}"; shift 2 ;;
    --target) TARGET="${2:?--target 需要路径}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --stop-services) STOP_SERVICES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

[[ -n "$NAME" ]] || die "缺少 --name（快照文件名，可从 backup-all 输出或 app.backup list 获取）"
[[ -n "$TARGET" ]] || die "缺少 --target（生产库路径，例如 /opt/openfactory/data/opensource_factory.db）"

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
RESTORE_ARGS=(restore --backup-dir "$BACKUP_DIR" --name "$NAME" --target "$TARGET")
[[ "$FORCE" -eq 1 ]] && RESTORE_ARGS+=(--force)

if [[ "$DRY_RUN" -eq 1 ]]; then
  [[ "$STOP_SERVICES" -eq 1 ]] && log "DRY-RUN 将停止 openfactory-api openfactory-worker openfactory-beat"
  log "DRY-RUN 将执行：cd $APP_DIR/vps && $PYTHON_BIN -m app.backup ${RESTORE_ARGS[*]}"
  [[ "$STOP_SERVICES" -eq 1 ]] && log "DRY-RUN 将重启 openfactory-api openfactory-worker openfactory-beat"
  exit 0
fi

if [[ "$STOP_SERVICES" -eq 1 ]]; then
  [[ "$EUID" -eq 0 ]] || die "restore-sqlite.sh --stop-services 需要 root"
  log "停止服务：openfactory-api openfactory-worker openfactory-beat"
  systemctl stop openfactory-api openfactory-worker openfactory-beat
  trap 'systemctl start openfactory-api openfactory-worker openfactory-beat' EXIT
fi

cd "$APP_DIR/vps"
log "恢复 SQLite：$NAME → $TARGET"
"$PYTHON_BIN" -m app.backup "${RESTORE_ARGS[@]}"

if [[ "$STOP_SERVICES" -eq 1 ]]; then
  log "重启服务"
  systemctl start openfactory-api openfactory-worker openfactory-beat
  trap - EXIT
fi
log "恢复完成；请执行部署冒烟测试并核对业务数据"
