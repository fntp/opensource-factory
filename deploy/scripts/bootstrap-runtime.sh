#!/usr/bin/env bash
# OpenFactory 运行目录引导（REQ-202610-0893 / M1-01）
#
# 默认行为（可重复执行，幂等）：
#   1) 创建 $OPENFACTORY_HOME（默认 /opt/openfactory）及 etc/data/logs/backups/run 子目录（700）；
#   2) 首次生成 .env（600，来自 deploy/env/openfactory.env.example）并自动生成 INTERNAL_TOKEN；
#   3) 首次生成 etc/redis.conf（600，来自 deploy/redis/redis.conf）。
#
# 可选：
#   --create-user      创建系统用户并 chown 运行目录（需 root）
#   --install-units    渲染并安装 systemd 单元到 /etc/systemd/system（需 root，隐含 --create-user）
#   --with-redis       缺少 redis-server 时用 apt 安装，并停用发行版默认实例（需 root）
#   --force            覆盖已有 .env / redis.conf
#   --check            结束后运行 doctor.sh 自检
#
# 用法：deploy/scripts/bootstrap-runtime.sh [--home /opt/openfactory] [--user openfactory]
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
RUNTIME_DIR="${OPENFACTORY_HOME:-/opt/openfactory}"
SERVICE_USER="${OPENFACTORY_USER:-openfactory}"

CREATE_USER=0
INSTALL_UNITS=0
WITH_REDIS=0
FORCE=0
RUN_CHECK=0

usage() {
  sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

log() { printf '[bootstrap] %s\n' "$*"; }
die() { printf '[bootstrap] 错误：%s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --home) RUNTIME_DIR="${2:?--home 需要路径}"; shift 2 ;;
    --user) SERVICE_USER="${2:?--user 需要用户名}"; shift 2 ;;
    --create-user) CREATE_USER=1; shift ;;
    --install-units) INSTALL_UNITS=1; CREATE_USER=1; shift ;;
    --with-redis) WITH_REDIS=1; shift ;;
    --force) FORCE=1; shift ;;
    --check) RUN_CHECK=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知参数：$1（--help 查看用法）" ;;
  esac
done

render() {
  sed -e "s|@APP_DIR@|${APP_DIR}|g" \
      -e "s|@RUNTIME_DIR@|${RUNTIME_DIR}|g" \
      -e "s|@SERVICE_USER@|${SERVICE_USER}|g" "$1"
}

# ---------- 1. 运行目录 ----------
install -d -m 700 "$RUNTIME_DIR"
for sub in etc data data/redis logs backups run; do
  install -d -m 700 "$RUNTIME_DIR/$sub"
done
chmod 700 "$RUNTIME_DIR"
log "运行目录就绪：$RUNTIME_DIR"

# ---------- 2. .env ----------
if [[ ! -f "$RUNTIME_DIR/.env" || "$FORCE" -eq 1 ]]; then
  render "$APP_DIR/deploy/env/openfactory.env.example" > "$RUNTIME_DIR/.env"
  chmod 600 "$RUNTIME_DIR/.env"
  log "已生成 $RUNTIME_DIR/.env（600）"
else
  log "保留已有 $RUNTIME_DIR/.env"
fi

if grep -qE '^INTERNAL_TOKEN=[[:space:]]*$' "$RUNTIME_DIR/.env"; then
  if command -v openssl >/dev/null 2>&1; then
    token="$(openssl rand -hex 32)"
  else
    token="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  fi
  sed -i "s|^INTERNAL_TOKEN=.*$|INTERNAL_TOKEN=${token}|" "$RUNTIME_DIR/.env"
  log "已生成 INTERNAL_TOKEN（仅写入本机 .env，未回显）"
fi
chmod 600 "$RUNTIME_DIR/.env"

# ---------- 3. Redis 配置 ----------
if [[ ! -f "$RUNTIME_DIR/etc/redis.conf" || "$FORCE" -eq 1 ]]; then
  render "$APP_DIR/deploy/redis/redis.conf" > "$RUNTIME_DIR/etc/redis.conf"
  chmod 600 "$RUNTIME_DIR/etc/redis.conf"
  log "已生成 $RUNTIME_DIR/etc/redis.conf（600）"
else
  log "保留已有 $RUNTIME_DIR/etc/redis.conf"
fi

# ---------- 4. 系统用户 ----------
if [[ "$CREATE_USER" -eq 1 ]]; then
  [[ "$EUID" -eq 0 ]] || die "--create-user 需要 root"
  if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$RUNTIME_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
    log "已创建系统用户：$SERVICE_USER"
  fi
  chown -R "$SERVICE_USER:$SERVICE_USER" "$RUNTIME_DIR"
  log "运行目录属主：$SERVICE_USER"
fi

# ---------- 5. Redis 安装（可选） ----------
if [[ "$WITH_REDIS" -eq 1 ]] && ! command -v redis-server >/dev/null 2>&1; then
  [[ "$EUID" -eq 0 ]] || die "--with-redis 需要 root"
  command -v apt-get >/dev/null 2>&1 || die "未找到 apt-get，请手动安装 redis-server"
  log "安装 redis-server（apt）..."
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq redis-server
  # 发行版默认实例会占用 6379，交给 openfactory-redis 接管
  systemctl disable --now redis-server >/dev/null 2>&1 || true
  log "redis-server 安装完成；默认 redis.service 已停用"
fi

# ---------- 6. systemd 单元（可选） ----------
if [[ "$INSTALL_UNITS" -eq 1 ]]; then
  [[ "$EUID" -eq 0 ]] || die "--install-units 需要 root"
  units=(openfactory-redis.service openfactory-api.service openfactory-worker.service openfactory-beat.service)
  for unit in "${units[@]}"; do
    render "$APP_DIR/deploy/systemd/$unit" > "/etc/systemd/system/$unit"
    chmod 644 "/etc/systemd/system/$unit"
  done
  systemctl daemon-reload
  log "已安装 systemd 单元：${units[*]}"
  log "启用命令：systemctl enable --now ${units[*]}"
fi

# ---------- 7. 收尾权限 ----------
chmod 700 "$RUNTIME_DIR" "$RUNTIME_DIR/etc" "$RUNTIME_DIR/data" "$RUNTIME_DIR/data/redis" \
  "$RUNTIME_DIR/logs" "$RUNTIME_DIR/backups" "$RUNTIME_DIR/run"
chmod 600 "$RUNTIME_DIR/.env" "$RUNTIME_DIR/etc/redis.conf"

log "完成。运行目录布局："
find "$RUNTIME_DIR" -maxdepth 2 -mindepth 1 -printf '  %M %p\n' | sort

if [[ "$RUN_CHECK" -eq 1 ]]; then
  "$APP_DIR/deploy/scripts/doctor.sh" --home "$RUNTIME_DIR"
fi
