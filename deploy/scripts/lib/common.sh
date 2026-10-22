#!/usr/bin/env bash
# 部署脚本共享函数（不单独执行）。
#
# 约定：
#   - 只解析 KEY=VALUE 形式的 env 文件，不 source 任意脚本；
#   - 日志绝不打印密钥值；
#   - 重活（npm ci / pip install / build）统一走 bacs-heavy 或 nice + ionice。

log() { printf '[deploy] %s\n' "$*"; }
warn() { printf '[deploy] 警告：%s\n' "$*" >&2; }
die() { printf '[deploy] 错误：%s\n' "$*" >&2; exit 1; }

# load_env_file <path>
# 解析 KEY=VALUE（忽略注释 / 空行 / 非法键），导出为环境变量。
load_env_file() {
  local file="$1"
  [[ -f "$file" ]] || die "配置文件不存在：$file"
  local raw key value
  while IFS= read -r raw || [[ -n "$raw" ]]; do
    raw="${raw%$'\r'}"
    [[ -z "${raw//[[:space:]]/}" ]] && continue
    [[ "$raw" =~ ^[[:space:]]*# ]] && continue
    [[ "$raw" != *=* ]] && continue
    key="${raw%%=*}"
    value="${raw#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ ${#value} -ge 2 && "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ ${#value} -ge 2 && "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    export "$key=$value"
  done < "$file"
}

# read_env_value <path> <key> —— 读取单个值，不回显。
read_env_value() {
  local file="$1" want="$2" raw key value
  [[ -f "$file" ]] || return 0
  while IFS= read -r raw || [[ -n "$raw" ]]; do
    raw="${raw%$'\r'}"
    [[ "$raw" =~ ^[[:space:]]*# ]] && continue
    [[ "$raw" != *=* ]] && continue
    key="${raw%%=*}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ "$key" == "$want" ]] || continue
    value="${raw#*=}"
    if [[ ${#value} -ge 2 && "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    fi
    printf '%s' "$value"
    return 0
  done < "$file"
}

# resolve_env_file <显式路径或空> <允许示例文件 0/1>
resolve_env_file() {
  local explicit="${1:-}" allow_example="${2:-0}" home="${OPENFACTORY_HOME:-/opt/openfactory}"
  if [[ -n "$explicit" ]]; then
    printf '%s' "$explicit"
    return 0
  fi
  if [[ -f "$home/deploy.env" ]]; then
    printf '%s' "$home/deploy.env"
    return 0
  fi
  if [[ -f "$DEPLOY_DIR/env/deploy.env" ]]; then
    printf '%s' "$DEPLOY_DIR/env/deploy.env"
    return 0
  fi
  if [[ "$allow_example" == "1" && -f "$DEPLOY_DIR/env/deploy.env.example" ]]; then
    printf '%s' "$DEPLOY_DIR/env/deploy.env.example"
    return 0
  fi
  die "未找到部署配置：请复制 deploy/env/deploy.env.example 到 $home/deploy.env（600）后填写，或用 --env-file 指定"
}

require_var() {
  local name="$1" hint="${2:-}"
  local value="${!name:-}"
  [[ -n "$value" ]] || die "缺少配置 $name${hint:+（$hint）}"
}

is_placeholder() {
  case "${1:-}" in
    *REPLACE_WITH*|*CHANGE_ME*|*'<your'*) return 0 ;;
    *) return 1 ;;
  esac
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "缺少命令：$1"
}

url_scheme() {
  local url="$1"
  printf '%s' "${url%%:*}"
}

url_host() {
  local url="$1"
  url="${url#*://}"
  url="${url%%/*}"
  printf '%s' "$url"
}

url_origin() {
  local url="$1"
  printf '%s' "${url%/}"
}

# run_heavy <cmd...> —— 重活降优先级 / 全机排队。
run_heavy() {
  if command -v bacs-heavy >/dev/null 2>&1; then
    bacs-heavy "$@"
    return $?
  fi
  if command -v ionice >/dev/null 2>&1; then
    nice -n 10 ionice -c3 "$@"
  else
    nice -n 10 "$@"
  fi
}

# wait_http_ok <url> <超时秒> —— 轮询 healthz。
wait_http_ok() {
  local url="$1" timeout="${2:-60}" elapsed=0
  while (( elapsed < timeout )); do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}
