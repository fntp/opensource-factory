#!/usr/bin/env bash
# OpenFactory 本机一体化部署（REQ-202610-0940 / M5-02）
#
# 子命令：
#   build   构建 admin（VITE_API_BASE_URL=/local）并复制到 $RUNTIME_DIR/admin
#   enable  在 .env 打开 LOCAL_MODE 并重启 openfactory-api（需 root）
#   disable 关闭 LOCAL_MODE 并重启 openfactory-api（需 root）
#   status  查看开关 / 构建产物 / 健康状态
#   verify  离线冒烟：/healthz、/local/api/*、admin 首页
#
# 用法：deploy/scripts/local-allinone.sh <build|enable|disable|status|verify> [--home /opt/openfactory]
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
RUNTIME_DIR="${OPENFACTORY_HOME:-/opt/openfactory}"
SERVICE_USER="${OPENFACTORY_USER:-openfactory}"
BASE_URL="${OPENFACTORY_LOCAL_URL:-http://127.0.0.1:8000}"

usage() {
  sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

log() { printf '[local-allinone] %s\n' "$*"; }
die() { printf '[local-allinone] 错误：%s\n' "$*" >&2; exit 1; }

# 重活统一走 bacs-heavy（同机资源自律）；未安装时直接执行
run_heavy() {
  if command -v bacs-heavy >/dev/null 2>&1; then
    bacs-heavy "$@"
  else
    "$@"
  fi
}

need_env() {
  [[ -f "$RUNTIME_DIR/.env" ]] || die "缺少 $RUNTIME_DIR/.env，请先执行 deploy/scripts/bootstrap-runtime.sh"
}

set_env() {
  local key="$1" value="$2" file="$RUNTIME_DIR/.env"
  if grep -qE "^${key}=" "$file"; then
    sed -i "s|^${key}=.*$|${key}=${value}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

restart_api() {
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files openfactory-api.service >/dev/null 2>&1; then
    [[ "$EUID" -eq 0 ]] || die "重启 openfactory-api 需要 root"
    systemctl restart openfactory-api.service
    log "已重启 openfactory-api.service"
  else
    log "未安装 openfactory-api.service；请手动重启 uvicorn"
  fi
}

cmd_build() {
  local dist="$APP_DIR/admin/dist"
  log "构建 admin（同源 API 前缀 /local，关闭演示模式）..."
  (
    cd "$APP_DIR/admin"
    if [[ -f package-lock.json ]]; then
      run_heavy npm ci
    else
      run_heavy npm install
    fi
    export VITE_API_BASE_URL=/local
    export VITE_DEMO_MODE=false
    run_heavy npm run build
  )
  [[ -f "$dist/index.html" ]] || die "构建失败：缺少 $dist/index.html"

  install -d -m 700 "$RUNTIME_DIR/admin"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "$dist/" "$RUNTIME_DIR/admin/"
  else
    rm -rf "$RUNTIME_DIR/admin"
    install -d -m 700 "$RUNTIME_DIR/admin"
    cp -a "$dist/." "$RUNTIME_DIR/admin/"
  fi
  if id -u "$SERVICE_USER" >/dev/null 2>&1; then
    chown -R "$SERVICE_USER:$SERVICE_USER" "$RUNTIME_DIR/admin"
  fi
  log "admin 构建产物已复制：$RUNTIME_DIR/admin"
}

cmd_enable() {
  need_env
  set_env LOCAL_MODE 1
  set_env LOCAL_ADMIN_DIR "$RUNTIME_DIR/admin"
  chmod 600 "$RUNTIME_DIR/.env"
  log "已开启 LOCAL_MODE=1（LOCAL_ADMIN_DIR=$RUNTIME_DIR/admin）"
  [[ -f "$RUNTIME_DIR/admin/index.html" ]] || log "提示：尚未找到 admin 构建产物，请先执行 build"
  restart_api
}

cmd_disable() {
  need_env
  set_env LOCAL_MODE 0
  chmod 600 "$RUNTIME_DIR/.env"
  log "已关闭 LOCAL_MODE=0（混合架构恢复）"
  restart_api
}

cmd_status() {
  need_env
  local mode admin_dir
  mode="$(grep -E '^LOCAL_MODE=' "$RUNTIME_DIR/.env" | tail -1 | cut -d= -f2-)"
  admin_dir="$(grep -E '^LOCAL_ADMIN_DIR=' "$RUNTIME_DIR/.env" | tail -1 | cut -d= -f2-)"
  printf 'LOCAL_MODE=%s\nLOCAL_ADMIN_DIR=%s\n' "${mode:-0}" "${admin_dir:-}"
  if [[ -n "$admin_dir" && -f "$admin_dir/index.html" ]]; then
    printf 'admin_build=ready\n'
  else
    printf 'admin_build=missing\n'
  fi
  if command -v curl >/dev/null 2>&1; then
    printf 'healthz=%s\n' "$(curl -fsS -m 5 "$BASE_URL/healthz" 2>/dev/null || echo unavailable)"
    printf 'local_status=%s\n' "$(curl -fsS -m 5 "$BASE_URL/local/api/local/status" 2>/dev/null || echo unavailable)"
  fi
}

check_json() {
  local path="$1" key="$2" body
  body="$(curl -fsS -m 10 "$BASE_URL$path")" || die "请求失败：$path"
  python3 -c 'import json,sys; data=json.load(sys.stdin); key=sys.argv[1]; assert key in data, f"响应缺少字段 {key}"' "$key" <<<"$body" \
    || die "响应异常：$path"
  log "OK $path"
}

check_list() {
  local path="$1" body
  body="$(curl -fsS -m 10 "$BASE_URL$path")" || die "请求失败：$path"
  python3 -c 'import json,sys; assert isinstance(json.load(sys.stdin), list)' <<<"$body" \
    || die "响应不是数组：$path"
  log "OK $path"
}

cmd_verify() {
  command -v curl >/dev/null 2>&1 || die "verify 需要 curl"
  command -v python3 >/dev/null 2>&1 || die "verify 需要 python3"

  local health
  health="$(curl -fsS -m 10 "$BASE_URL/healthz")" || die "健康检查失败：$BASE_URL/healthz"
  grep -q '"status":"ok"' <<<"$health" || die "健康检查返回异常：$health"
  log "OK /healthz"

  check_json "/local/api/local/status" "mode"
  check_json "/local/api/dashboard/stats" "totalRepos"
  check_list "/local/api/repos"
  check_list "/local/api/trending"

  curl -fsS -m 10 "$BASE_URL/" | grep -qi '<!doctype html\|<html' || die "admin 首页不是 HTML"
  log "OK /（admin 静态页）"
  log "离线验收通过：$BASE_URL"
}

COMMAND="${1:-}"
[[ $# -gt 0 ]] && shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --home) RUNTIME_DIR="${2:?--home 需要路径}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

case "$COMMAND" in
  build) cmd_build ;;
  enable) cmd_enable ;;
  disable) cmd_disable ;;
  status) cmd_status ;;
  verify) cmd_verify ;;
  -h|--help|help|"") usage ;;
  *) die "未知子命令：$COMMAND（--help 查看用法）" ;;
esac
