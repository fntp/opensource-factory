#!/usr/bin/env bash
# 构建并发布 admin 到 Cloudflare Pages（REQ-202610-0939 / M5-01）
#
# 用法：
#   deploy/scripts/deploy-admin.sh [--env-file <path>] [--skip-install]
#                                  [--create-project] [--skip-smoke] [--dry-run]
#
# 生产构建强制：VITE_API_BASE_URL=$API_ORIGIN、VITE_DEMO_MODE=false。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

ENV_FILE=""
SKIP_INSTALL=0
CREATE_PROJECT=0
SKIP_SMOKE=0
DRY_RUN=0

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:?--env-file 需要路径}"; shift 2 ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --create-project) CREATE_PROJECT=1; shift ;;
    --skip-smoke) SKIP_SMOKE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

ENV_FILE="$(resolve_env_file "$ENV_FILE" "$DRY_RUN")"
PREFLIGHT_ARGS=(--env-file "$ENV_FILE" --target admin)
if [[ "$DRY_RUN" -eq 1 ]]; then PREFLIGHT_ARGS+=(--dry-run); fi
bash "$SCRIPT_DIR/preflight.sh" "${PREFLIGHT_ARGS[@]}"

load_env_file "$ENV_FILE"
cd "$APP_DIR/admin"

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  log "安装 admin 依赖（npm ci）"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "DRY-RUN 跳过 npm ci"
  else
    run_heavy npm ci
  fi
fi

log "生产构建：VITE_API_BASE_URL=$API_ORIGIN，VITE_DEMO_MODE=false"
if [[ "$DRY_RUN" -eq 1 ]]; then
  log "DRY-RUN 跳过 npm run build"
else
  VITE_API_BASE_URL="$API_ORIGIN" VITE_DEMO_MODE=false run_heavy npm run build
fi

if [[ "$CREATE_PROJECT" -eq 1 ]]; then
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "DRY-RUN 将创建 Pages 项目：$PAGES_PROJECT_NAME"
  else
    log "确保 Pages 项目存在：$PAGES_PROJECT_NAME"
    npx wrangler pages project create "$PAGES_PROJECT_NAME" --production-branch main >/dev/null 2>&1 \
      || warn "Pages 项目已存在或创建失败（继续发布）"
  fi
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "DRY-RUN 将执行：wrangler pages deploy dist --project-name $PAGES_PROJECT_NAME --branch main"
else
  log "发布到 Cloudflare Pages：$PAGES_PROJECT_NAME"
  npx wrangler pages deploy dist \
    --project-name "$PAGES_PROJECT_NAME" \
    --branch main \
    --commit-dirty=true
fi

if [[ "$SKIP_SMOKE" -eq 0 ]]; then
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "DRY-RUN 将冒烟：$ADMIN_ORIGIN"
  else
    log "冒烟检查：$ADMIN_ORIGIN"
    curl -fsS --max-time 10 "$ADMIN_ORIGIN" >/dev/null || die "admin 首页检查失败"
    log "admin 部署完成"
  fi
fi
