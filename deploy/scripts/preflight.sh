#!/usr/bin/env bash
# OpenFactory 生产部署预检（REQ-202610-0939 / M5-01）
#
# 用法：
#   deploy/scripts/preflight.sh [--env-file <path>] [--target edge|admin|vps|all]
#                               [--allow-http] [--dry-run]
#
# 检查项：工具链、部署配置键、占位符、HTTPS、内部令牌、关键目录。
# 只读，不发起部署；失败退出码 1。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
TARGET="all"
DRY_RUN=0
ALLOW_HTTP=0

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --target) TARGET="${2:?--target 需要值}"; shift 2 ;;
    --allow-http) ALLOW_HTTP=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

case "$TARGET" in
  edge|admin|vps|all) ;;
  *) die "--target 只接受 edge / admin / vps / all" ;;
esac

ENV_FILE="$(resolve_env_file "$ENV_FILE" "$DRY_RUN")"
log "部署配置：$ENV_FILE"
load_env_file "$ENV_FILE"

FAILURES=0
fail_or_warn() {
  local message="$1"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    warn "$message（dry-run 仅提示）"
  else
    printf '[deploy] 失败：%s\n' "$message" >&2
    FAILURES=$((FAILURES + 1))
  fi
}

required_keys() {
  case "$1" in
    edge)
      printf '%s\n' CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_API_TOKEN D1_DATABASE_NAME \
        D1_DATABASE_ID WORKER_NAME VECTORIZE_INDEX_NAME API_ORIGIN ADMIN_ORIGIN \
        VPS_NODE_URL GITHUB_CLIENT_ID GITHUB_CLIENT_SECRET SESSION_SECRET
      ;;
    admin)
      printf '%s\n' CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_API_TOKEN PAGES_PROJECT_NAME \
        ADMIN_ORIGIN API_ORIGIN
      ;;
    vps)
      printf '%s\n' OPENFACTORY_HOME VPS_NODE_URL
      ;;
    all)
      required_keys edge
      required_keys admin
      required_keys vps
      ;;
  esac
}

commands_for_target() {
  case "$1" in
    edge|admin) printf '%s\n' node npm npx curl ;;
    vps) printf '%s\n' python3 systemctl curl ;;
    all) printf '%s\n' node npm npx python3 systemctl curl ;;
  esac
}

log "检查目标：$TARGET"

# 1. 工具链
while IFS= read -r cmd; do
  [[ -n "$cmd" ]] || continue
  if command -v "$cmd" >/dev/null 2>&1; then
    log "工具 $cmd：$(command -v "$cmd")"
  else
    fail_or_warn "缺少命令：$cmd"
  fi
done < <(commands_for_target "$TARGET" | sort -u)

# 2. 必填配置
while IFS= read -r key; do
  [[ -n "$key" ]] || continue
  if [[ -z "${!key:-}" ]]; then
    fail_or_warn "缺少配置 $key"
  fi
done < <(required_keys "$TARGET" | sort -u)

# 3. 占位符
while IFS= read -r key; do
  [[ -n "$key" ]] || continue
  if is_placeholder "${!key:-}"; then
    fail_or_warn "$key 仍为占位符"
  fi
done < <(required_keys "$TARGET" | sort -u)

# 4. HTTPS（生产域名必须 https；本地联调可 --allow-http）
if [[ "$ALLOW_HTTP" -eq 0 ]]; then
  for key in ADMIN_ORIGIN API_ORIGIN VPS_NODE_URL; do
    value="${!key:-}"
    [[ -n "$value" ]] || continue
    if [[ "$(url_scheme "$value")" != "https" ]]; then
      fail_or_warn "$key 必须为 https（当前：$value；本地联调可加 --allow-http）"
    fi
  done
fi

# 5. 内部令牌：edge 与 VPS 必须一致，优先读运行目录 .env
if [[ "$TARGET" == "edge" || "$TARGET" == "all" ]]; then
  runtime_env="${OPENFACTORY_HOME:-/opt/openfactory}/.env"
  token="${INTERNAL_TOKEN:-}"
  if [[ -z "$token" && -f "$runtime_env" ]]; then
    token="$(read_env_value "$runtime_env" INTERNAL_TOKEN)"
  fi
  if [[ ${#token} -lt 16 ]]; then
    fail_or_warn "INTERNAL_TOKEN 未生成（先运行 deploy/scripts/bootstrap-runtime.sh，或在部署配置中提供）"
  else
    log "内部令牌：已就绪（长度 ${#token}，未回显）"
  fi
fi

# 6. 代码目录
if [[ "$TARGET" == "vps" || "$TARGET" == "all" ]]; then
  vps_app_dir="${VPS_APP_DIR:-$APP_DIR}"
  if [[ -d "$vps_app_dir/vps" ]]; then
    log "VPS 代码目录：$vps_app_dir"
  else
    fail_or_warn "VPS_APP_DIR 下没有 vps/：$vps_app_dir"
  fi
fi

if [[ "$FAILURES" -gt 0 ]]; then
  die "预检失败：$FAILURES 项（修正后重试）"
fi

log "预检通过（target=$TARGET${DRY_RUN:+，dry-run}）"
