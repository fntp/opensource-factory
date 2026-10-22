#!/usr/bin/env bash
# 安装 VPS 节点 HTTPS 反代（Caddy，REQ-202610-0939 / M5-01）
#
# 用法：
#   deploy/scripts/setup-https.sh [--env-file <path>] [--dry-run] [--allow-missing]
#
# 前置：域名已解析到本机，80/443 可达，Caddy 已安装（apt install caddy）。
# 行为：渲染 Caddyfile → caddy validate → 安装到 /etc/caddy/Caddyfile.d/ → reload caddy。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
DRY_RUN=0
ALLOW_MISSING=0

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --allow-missing) ALLOW_MISSING=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

ENV_FILE="$(resolve_env_file "$ENV_FILE" "$DRY_RUN")"
load_env_file "$ENV_FILE"
OPENFACTORY_HOME="${OPENFACTORY_HOME:-/opt/openfactory}"
CADDY_FILE="$OPENFACTORY_HOME/etc/Caddyfile"

RENDER_ARGS=(--env-file "$ENV_FILE" --caddy-out "$CADDY_FILE")
if [[ "$DRY_RUN" -eq 1 ]]; then RENDER_ARGS+=(--dry-run); fi
bash "$SCRIPT_DIR/render-config.sh" "${RENDER_ARGS[@]}"

if ! command -v caddy >/dev/null 2>&1; then
  warn "未安装 Caddy：请执行 apt-get install -y caddy（或使用 Cloudflare 代理终止 TLS）"
  if [[ "$ALLOW_MISSING" -eq 1 || "$DRY_RUN" -eq 1 ]]; then
    log "跳过 Caddy 安装（--allow-missing / dry-run）"
    exit 0
  fi
  die "缺少 caddy 命令"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "DRY-RUN 将校验并安装：$CADDY_FILE"
  exit 0
fi

caddy validate --config "$CADDY_FILE" --adapter caddyfile

[[ "$EUID" -eq 0 ]] || die "安装 Caddyfile 需要 root"
install -d -m 755 /etc/caddy/Caddyfile.d
install -m 644 "$CADDY_FILE" /etc/caddy/Caddyfile.d/openfactory.caddy

# 确保主配置引用了 Caddyfile.d（Caddy 官方包默认包含 import）
if ! grep -q 'import /etc/caddy/Caddyfile.d/\*' /etc/caddy/Caddyfile 2>/dev/null; then
  printf '\nimport /etc/caddy/Caddyfile.d/*\n' >> /etc/caddy/Caddyfile
fi

systemctl reload caddy
log "Caddy 已 reload，HTTPS 证书将自动申请（域名：$(url_host "$VPS_NODE_URL")）"
