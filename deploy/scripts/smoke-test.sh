#!/usr/bin/env bash
# 三端部署冒烟测试（REQ-202610-0939 / M5-01）
#
# 用法：
#   deploy/scripts/smoke-test.sh [--env-file <path>] [--json] [--dry-run] [--timeout 10]
#
# 检查：VPS /healthz、edge /healthz、admin 首页。全部通过退出码 0。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
JSON=0
DRY_RUN=0
TIMEOUT=10

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --json) JSON=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --timeout) TIMEOUT="${2:?--timeout 需要秒数}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

ENV_FILE="$(resolve_env_file "$ENV_FILE" "$DRY_RUN")"
load_env_file "$ENV_FILE"

VPS_URL="${VPS_NODE_URL%/}"
API_URL="${API_ORIGIN%/}"
ADMIN_URL="${ADMIN_ORIGIN%/}"
for pair in "VPS_NODE_URL=$VPS_URL" "API_ORIGIN=$API_URL" "ADMIN_ORIGIN=$ADMIN_URL"; do
  key="${pair%%=*}"
  value="${pair#*=}"
  [[ -n "$value" ]] || die "缺少 $key"
done

FAILURES=0
RESULTS=()

record() {
  local name="$1" url="$2" ok="$3" detail="$4"
  RESULTS+=("$name|$url|$ok|$detail")
  if [[ "$ok" == "1" ]]; then
    printf '[smoke] PASS %-12s %s %s\n' "$name" "$url" "$detail"
  else
    printf '[smoke] FAIL %-12s %s %s\n' "$name" "$url" "$detail" >&2
    FAILURES=$((FAILURES + 1))
  fi
}

check_health() {
  local name="$1" url="$2"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "DRY-RUN 检查 $name：$url（期望 200 + status=ok）"
    return 0
  fi
  local body status
  body="$(mktemp)"
  status="$(curl -sS -o "$body" -w '%{http_code}' --max-time "$TIMEOUT" "$url" 2>/dev/null || true)"
  if [[ "$status" == "200" ]] && grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' "$body"; then
    record "$name" "$url" 1 "HTTP $status"
  else
    record "$name" "$url" 0 "HTTP ${status:-000}"
  fi
  rm -f "$body"
}

check_page() {
  local name="$1" url="$2"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "DRY-RUN 检查 $name：$url（期望 200 + HTML）"
    return 0
  fi
  local body status
  body="$(mktemp)"
  status="$(curl -sS -o "$body" -w '%{http_code}' --max-time "$TIMEOUT" "$url" 2>/dev/null || true)"
  if [[ "$status" == "200" ]] && grep -qi '<div id="root"\|<title' "$body"; then
    record "$name" "$url" 1 "HTTP $status"
  else
    record "$name" "$url" 0 "HTTP ${status:-000}"
  fi
  rm -f "$body"
}

log "冒烟目标：vps=$VPS_URL edge=$API_URL admin=$ADMIN_URL"
check_health "vps" "$VPS_URL/healthz"
check_health "edge" "$API_URL/healthz"
check_page "admin" "$ADMIN_URL/"

if [[ "$JSON" -eq 1 ]]; then
  printf '{"ok":%s,"checks":[' "$([[ "$FAILURES" -eq 0 ]] && echo true || echo false)"
  first=1
  for item in "${RESULTS[@]}"; do
    IFS='|' read -r name url ok detail <<<"$item"
    [[ "$first" -eq 0 ]] && printf ','
    first=0
    printf '{"name":"%s","url":"%s","ok":%s,"detail":"%s"}' \
      "$name" "$url" "$([[ "$ok" == "1" ]] && echo true || echo false)" "$detail"
  done
  printf ']}\n'
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "DRY-RUN 冒烟计划完成"
  exit 0
fi

if [[ "$FAILURES" -gt 0 ]]; then
  die "冒烟失败：$FAILURES 项"
fi
log "三端冒烟全部通过"
