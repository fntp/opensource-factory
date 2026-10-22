#!/usr/bin/env bash
# 部署本机 VPS 节点（FastAPI + Celery + Redis，REQ-202610-0939 / M5-01）
#
# 用法：
#   deploy/scripts/deploy-vps.sh [--env-file <path>] [--app-dir <path>]
#                                [--skip-deps] [--no-restart] [--dry-run]
#
# 流程：预检 → 创建运行目录 / 安装 systemd 单元 → 安装依赖（可选）→ 重启服务 → /healthz 冒烟。
# 注意：需 root（安装单元 / 重启服务）；依赖安装走 bacs-heavy 排队。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
APP_DIR=""
SKIP_DEPS=0
NO_RESTART=0
DRY_RUN=0

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --app-dir) APP_DIR="${2:?--app-dir 需要路径}"; shift 2 ;;
    --skip-deps) SKIP_DEPS=1; shift ;;
    --no-restart) NO_RESTART=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

ENV_FILE="$(resolve_env_file "$ENV_FILE" "$DRY_RUN")"
load_env_file "$ENV_FILE"
APP_DIR="${APP_DIR:-${VPS_APP_DIR:-$REPO_DIR}}"
export OPENFACTORY_HOME="${OPENFACTORY_HOME:-/opt/openfactory}"
export VPS_APP_DIR="$APP_DIR"

PREFLIGHT_ARGS=(--env-file "$ENV_FILE" --target vps)
if [[ "$DRY_RUN" -eq 1 ]]; then PREFLIGHT_ARGS+=(--dry-run); fi
bash "$SCRIPT_DIR/preflight.sh" "${PREFLIGHT_ARGS[@]}"

[[ -d "$APP_DIR/vps" ]] || die "VPS 代码目录不存在：$APP_DIR/vps"
[[ -d "$APP_DIR/deploy" ]] || die "部署资产不存在：$APP_DIR/deploy"

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "DRY-RUN 将执行：bootstrap-runtime.sh --install-units（home=$OPENFACTORY_HOME）"
  log "DRY-RUN 将执行：systemctl enable --now openfactory-redis openfactory-api openfactory-worker openfactory-beat"
  log "DRY-RUN 将冒烟：http://127.0.0.1:8000/healthz"
  exit 0
fi

[[ "$EUID" -eq 0 ]] || die "deploy-vps.sh 需要 root（安装 systemd 单元 / 重启服务）"

log "初始化运行目录与 systemd 单元"
bash "$APP_DIR/deploy/scripts/bootstrap-runtime.sh" --install-units --home "$OPENFACTORY_HOME"

cd "$APP_DIR/vps"
if [[ ! -x .venv/bin/python ]]; then
  log "创建 Python 虚拟环境"
  python3 -m venv .venv
fi
if [[ "$SKIP_DEPS" -eq 0 ]]; then
  log "安装 VPS 依赖（pip install -r requirements.txt）"
  run_heavy .venv/bin/pip install -q -r requirements.txt
fi

if [[ "$NO_RESTART" -eq 0 ]]; then
  log "启用并重启服务"
  systemctl enable openfactory-redis openfactory-api openfactory-worker openfactory-beat >/dev/null
  systemctl restart openfactory-redis openfactory-api openfactory-worker openfactory-beat
else
  log "跳过服务重启（--no-restart）"
fi

log "等待 API 健康检查"
wait_http_ok "http://127.0.0.1:8000/healthz" 60 || die "API /healthz 未在 60 秒内就绪"
log "VPS 节点部署完成（4 个单元均已启动）"
systemctl is-active openfactory-redis openfactory-api openfactory-worker openfactory-beat
