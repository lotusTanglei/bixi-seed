#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"

configured_data_dir() {
  local data_dir="${BIXI_DATA_DIR:-}"
  if [[ -z "$data_dir" && -f "$PROJECT_ROOT/.env" ]]; then
    data_dir="$(sed -n 's/^BIXI_DATA_DIR[[:space:]]*=[[:space:]]*//p' "$PROJECT_ROOT/.env" | head -n 1)"
    data_dir="$(printf '%s' "$data_dir" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g; s/^"(.*)"$/\1/; s/^\047(.*)\047$/\1/')"
  fi
  if [[ -z "$data_dir" ]]; then
    data_dir="$PROJECT_ROOT/data"
  elif [[ "$data_dir" != /* ]]; then
    data_dir="$PROJECT_ROOT/$data_dir"
  fi
  printf '%s\n' "$data_dir"
}

DATA_DIR="$(configured_data_dir)"
PID_FILE="$DATA_DIR/bixi-seed.pid"
LOG_DIR="$DATA_DIR/logs"

mkdir -p "$PROJECT_ROOT/data" "$LOG_DIR"

require_environment() {
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Python 虚拟环境不存在，请先运行 ./setup.sh。" >&2
    exit 1
  fi
}

configured_port() {
  local port="${BIXI_PORT:-}"
  if [[ -z "$port" && -f "$PROJECT_ROOT/.env" ]]; then
    port="$(sed -n 's/^BIXI_PORT[[:space:]]*=[[:space:]]*//p' "$PROJECT_ROOT/.env" | head -n 1 | sed -E 's/^[[:space:]]+|[[:space:]]+$//g; s/^"(.*)"$/\1/; s/^\047(.*)\047$/\1/')"
  fi
  echo "${port:-8000}"
}

require_configuration() {
  local env_file="$PROJECT_ROOT/.env"
  if [[ ! -f "$env_file" ]]; then
    echo "配置文件 .env 不存在，请先运行 ./setup.sh。" >&2
    exit 1
  fi
  local secret_key
  secret_key="${BIXI_SECRET_KEY:-}"
  if [[ -z "$secret_key" ]]; then
    secret_key="$(sed -n 's/^BIXI_SECRET_KEY[[:space:]]*=[[:space:]]*//p' "$env_file" | head -n 1 | sed -E 's/^[[:space:]]+|[[:space:]]+$//g; s/^"(.*)"$/\1/; s/^\047(.*)\047$/\1/')"
  fi
  if [[ -z "$secret_key" || "$secret_key" == "generate-during-setup" || "$secret_key" == "development-only-change-this-secret" ]]; then
    echo "Django Secret Key 尚未配置，请先运行 ./setup.sh。" >&2
    exit 1
  fi
  local port
  port="$(configured_port)"
  if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    echo "BIXI_PORT 必须是 1 到 65535 之间的数字。" >&2
    exit 1
  fi
}

check_port_available() {
  "$PYTHON_BIN" manage.py check_port --host "$(configured_bind_host)" --port "$(configured_port)" >/dev/null
}

health_check() {
  local payload
  payload="$(curl --fail --silent --max-time 2 "http://127.0.0.1:$(configured_port)/api/health/")" || return 1
  printf '%s' "$payload" | "$PYTHON_BIN" -c 'import json, sys; payload=json.load(sys.stdin); raise SystemExit(0 if payload.get("status") == "ok" and payload.get("service") == "bixi-seed-core" else 1)'
}

configured_bind_host() {
  local bind_host="${BIXI_BIND_HOST:-}"
  if [[ -z "$bind_host" && -f "$PROJECT_ROOT/.env" ]]; then
    bind_host="$(sed -n 's/^BIXI_BIND_HOST[[:space:]]*=[[:space:]]*\(.*\)$/\1/p' "$PROJECT_ROOT/.env" | head -n 1 | tr -d '\"\047' | xargs)"
  fi
  echo "${bind_host:-127.0.0.1}"
}

managed_pid() {
  [[ -f "$PID_FILE" ]] || return 1
  local server_pid
  server_pid="$(tr -d '[:space:]' < "$PID_FILE")"
  [[ "$server_pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$server_pid" 2>/dev/null || return 1
  ps -p "$server_pid" -o command= 2>/dev/null | grep -q "uvicorn.*config.asgi:application" || return 1
  echo "$server_pid"
}
