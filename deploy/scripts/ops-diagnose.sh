#!/usr/bin/env bash
# OpenFactory 现场诊断信息采集（REQ-202610-0945 / M5-07）
#
# 用法：
#   deploy/scripts/ops-diagnose.sh [--env-file <path>] [--home <path>]
#                                  [--output <dir>] [--lines N] [--no-services]
#
# 只读采集：不修改配置、不重启服务、不读取 .env 明文；输出目录 700、文件 600。
# 生成 summary.txt 与 journal-*.log，供故障处理 / 复盘使用。外发前请人工审查日志内容。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
HOME_DIR="${OPENFACTORY_HOME:-/opt/openfactory}"
OUTPUT=""
LINES=50
NO_SERVICES=0

usage() {
  sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --home) HOME_DIR="${2:?--home 需要路径}"; shift 2 ;;
    --output) OUTPUT="${2:?--output 需要路径}"; shift 2 ;;
    --lines) LINES="${2:?--lines 需要行数}"; shift 2 ;;
    --no-services) NO_SERVICES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

[[ "$LINES" =~ ^[0-9]+$ ]] || die "--lines 必须是数字"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUTPUT="${OUTPUT:-${TMPDIR:-/tmp}/openfactory-diagnose-$STAMP}"
mkdir -p "$OUTPUT"
chmod 700 "$OUTPUT"

SUMMARY="$OUTPUT/summary.txt"
: > "$SUMMARY"
chmod 600 "$SUMMARY"

say() { printf '%s\n' "$*" >> "$SUMMARY"; }
section() { printf '\n===== %s =====\n' "$*" >> "$SUMMARY"; }

section "基本信息"
say "采集时间：$(date '+%Y-%m-%d %H:%M:%S %z')"
say "主机名：$(hostname 2>/dev/null || echo unknown)"
say "内核：$(uname -srm 2>/dev/null || echo unknown)"
say "运行目录：$HOME_DIR"
say "代码目录：$APP_DIR"
say "输出目录：$OUTPUT"

{
  echo "### git"
  if git -C "$APP_DIR" rev-parse --short HEAD >/dev/null 2>&1; then
    echo "commit: $(git -C "$APP_DIR" rev-parse --short HEAD)"
    echo "branch: $(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
    echo "dirty: $(git -C "$APP_DIR" status --porcelain 2>/dev/null | wc -l) 个文件"
  else
    echo "不是 git 工作区或 git 不可用"
  fi
  echo
  echo "### uptime / nproc"
  uptime 2>&1 || true
  nproc 2>&1 || true
  echo
  echo "### 内存"
  free -m 2>&1 || true
  echo
  echo "### 磁盘"
  df -h "$HOME_DIR" 2>&1 || true
  du -sh "$HOME_DIR"/* 2>/dev/null || true
} >> "$SUMMARY"

if [[ "$NO_SERVICES" -eq 0 ]]; then
  section "systemd 单元"
  {
    for unit in openfactory-redis openfactory-api openfactory-worker openfactory-beat; do
      echo "### $unit"
      systemctl is-active "$unit" 2>&1 || true
      systemctl show "$unit" -p ActiveState -p SubState -p MemoryCurrent -p MemoryMax 2>&1 || true
      echo
    done
  } >> "$SUMMARY"

  section "journal 尾部"
  for unit in openfactory-redis openfactory-api openfactory-worker openfactory-beat; do
    log_file="$OUTPUT/journal-$unit.log"
    if command -v journalctl >/dev/null 2>&1; then
      journalctl -u "$unit" -n "$LINES" --no-pager >"$log_file" 2>&1 || true
    else
      printf 'journalctl 不可用\n' >"$log_file"
    fi
    chmod 600 "$log_file"
    say "$unit → $(basename "$log_file")（$LINES 行）"
  done
else
  section "systemd / journal"
  say "已按 --no-services 跳过"
fi

section "健康检查"
{
  echo "### 本机 API"
  curl -sS -o /dev/null -w 'http_code=%{http_code} time=%{time_total}s\n' \
    --max-time 5 http://127.0.0.1:8000/healthz 2>&1 || true
  echo
} >> "$SUMMARY"

if [[ -n "$ENV_FILE" ]]; then
  if [[ -f "$ENV_FILE" ]]; then
    load_env_file "$ENV_FILE"
    {
      for pair in "edge=${API_ORIGIN:-}/healthz" "vps=${VPS_NODE_URL:-}/healthz" "admin=${ADMIN_ORIGIN:-}/"; do
        name="${pair%%=*}"
        url="${pair#*=}"
        echo "### $name"
        if [[ -n "$url" && "$url" != "/healthz" && "$url" != "/" ]]; then
          curl -sS -o /dev/null -w 'http_code=%{http_code} time=%{time_total}s\n' \
            --max-time 10 "$url" 2>&1 || true
        else
          echo "未配置 URL"
        fi
        echo
      done
    } >> "$SUMMARY"
  else
    say "警告：--env-file 不存在：$ENV_FILE"
  fi
else
  say "未指定 --env-file，跳过 edge / admin / 公网 VPS 检查"
fi

section "doctor"
if [[ -x "$SCRIPT_DIR/doctor.sh" || -f "$SCRIPT_DIR/doctor.sh" ]]; then
  {
    echo "### doctor.sh"
    if [[ "$NO_SERVICES" -eq 0 ]]; then
      bash "$SCRIPT_DIR/doctor.sh" --home "$HOME_DIR" --services 2>&1 || true
    else
      bash "$SCRIPT_DIR/doctor.sh" --home "$HOME_DIR" 2>&1 || true
    fi
    echo
  } >> "$SUMMARY"
else
  say "doctor.sh 不存在，跳过"
fi

section "资源预算"
if [[ -f "$SCRIPT_DIR/resource-budget.sh" ]]; then
  {
    echo "### resource-budget.sh"
    if [[ "$NO_SERVICES" -eq 0 ]]; then
      bash "$SCRIPT_DIR/resource-budget.sh" --home "$HOME_DIR" --json 2>&1 || true
    else
      bash "$SCRIPT_DIR/resource-budget.sh" --home "$HOME_DIR" --json --no-services 2>&1 || true
    fi
    echo
  } >> "$SUMMARY"
else
  say "resource-budget.sh 不存在，跳过"
fi

section "采集完成"
say "诊断包：$OUTPUT"
say "提示：summary.txt 与 journal-*.log 可能包含敏感信息，外发前请人工审查。"

printf '%s\n' "$OUTPUT"
