#!/usr/bin/env bash
# 内部令牌轮换（REQ-202610-0943 / M5-05）
#
# 两阶段轮换，避免 edge / VPS 任一端短暂失配：
#   1) --apply：生成新令牌，旧令牌降为 INTERNAL_TOKEN_PREVIOUS，新令牌写入 INTERNAL_TOKEN；
#   2) 部署 edge（同步 Worker 机密）并重启 VPS 服务，验证两端 /api/security/status；
#   3) 全链路验证通过后，清空 INTERNAL_TOKEN_PREVIOUS 并再次部署。
#
# 用法：
#   deploy/scripts/rotate-internal-token.sh [--generate] [--apply]
#       [--env-file <path>] [--token-file <path>] [--status]
#
# 安全：令牌只写入 600 文件，stdout 仅输出路径与 sha-256 指纹，绝不回显明文。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
TOKEN_FILE=""
MODE="generate"

usage() {
  sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --generate) MODE="generate"; shift ;;
    --apply) MODE="apply"; shift ;;
    --status) MODE="status"; shift ;;
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --token-file) TOKEN_FILE="${2:?--token-file 需要路径}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

RUNTIME_DIR="${OPENFACTORY_HOME:-/opt/openfactory}"
ENV_FILE="${ENV_FILE:-$RUNTIME_DIR/.env}"
TOKEN_FILE="${TOKEN_FILE:-$RUNTIME_DIR/.internal-token.new}"

fingerprint() {
  # 只输出 sha-256 前 12 位，绝不输出令牌本身
  printf '%s' "$1" | sha256sum | cut -c1-12
}

read_token() {
  read_env_value "$ENV_FILE" "$1"
}

generate_token() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    python3 -c 'import secrets; print(secrets.token_hex(32))'
  fi
}

show_status() {
  [[ -f "$ENV_FILE" ]] || die "配置文件不存在：$ENV_FILE"
  local current previous
  current="$(read_token INTERNAL_TOKEN)"
  previous="$(read_token INTERNAL_TOKEN_PREVIOUS)"
  [[ -n "$current" ]] || die "INTERNAL_TOKEN 为空：先执行 deploy/scripts/bootstrap-runtime.sh"
  log "当前令牌指纹：$(fingerprint "$current")"
  if [[ -n "$previous" ]]; then
    log "上一枚令牌指纹：$(fingerprint "$previous")（轮换进行中）"
  else
    log "上一枚令牌：未配置（未在轮换）"
  fi
}

case "$MODE" in
  status)
    show_status
    exit 0
    ;;
  generate)
    [[ -f "$ENV_FILE" ]] || die "配置文件不存在：$ENV_FILE（先执行 bootstrap-runtime.sh）"
    umask 077
    install -d -m 700 "$(dirname -- "$TOKEN_FILE")"
    token="$(generate_token)"
    printf '%s\n' "$token" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    log "已生成新内部令牌（未回显），文件：$TOKEN_FILE（600）"
    log "新令牌指纹：$(fingerprint "$token")"
    log "下一步：deploy/scripts/rotate-internal-token.sh --apply --token-file $TOKEN_FILE"
    ;;
  apply)
    [[ -f "$ENV_FILE" ]] || die "配置文件不存在：$ENV_FILE（先执行 bootstrap-runtime.sh）"
    if [[ -f "$TOKEN_FILE" ]]; then
      token="$(head -n 1 "$TOKEN_FILE" | tr -d '[:space:]')"
    else
      token="$(generate_token)"
      umask 077
      printf '%s\n' "$token" > "$TOKEN_FILE"
      chmod 600 "$TOKEN_FILE"
      log "未提供令牌文件，已生成新令牌：$TOKEN_FILE（600）"
    fi
    [[ ${#token} -ge 32 ]] || die "新令牌长度不足（至少 32 字符）"
    old="$(read_token INTERNAL_TOKEN)"
    [[ -n "$old" ]] || die "当前 INTERNAL_TOKEN 为空：先执行 bootstrap-runtime.sh"
    [[ "$token" != "$old" ]] || die "新令牌与当前令牌相同，拒绝应用"

    tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
    chmod 600 "$tmp"
    awk -v current="$token" -v previous="$old" '
      BEGIN { seen_current = 0; seen_previous = 0 }
      /^INTERNAL_TOKEN=/ { print "INTERNAL_TOKEN=" current; seen_current = 1; next }
      /^INTERNAL_TOKEN_PREVIOUS=/ { print "INTERNAL_TOKEN_PREVIOUS=" previous; seen_previous = 1; next }
      { print }
      END {
        if (!seen_current) print "INTERNAL_TOKEN=" current
        if (!seen_previous) print "INTERNAL_TOKEN_PREVIOUS=" previous
      }
    ' "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    rm -f "$TOKEN_FILE"

    log "已应用双令牌配置：$ENV_FILE（600）"
    log "当前令牌指纹：$(fingerprint "$token")；上一枚指纹：$(fingerprint "$old")"
    log "下一步："
    log "  1) deploy/scripts/deploy-edge.sh --env-file <deploy.env>  # 同步 Worker 机密"
    log "  2) systemctl restart openfactory-api openfactory-worker openfactory-beat"
    log "  3) curl -H 'X-Internal-Token: <新令牌>' https://api.<domain>/api/internal/security/status"
    log "  4) 全链路验证通过后清空 INTERNAL_TOKEN_PREVIOUS 并再次部署"
    ;;
esac
