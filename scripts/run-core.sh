#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
cd "$PROJECT_ROOT"
require_environment
require_configuration
check_port_available
"$PYTHON_BIN" manage.py check
"$PYTHON_BIN" manage.py migrate --noinput

server_pid=""
cleanup() {
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  if [[ -f "$PID_FILE" ]] && [[ "$(tr -d '[:space:]' < "$PID_FILE")" == "${server_pid}" ]]; then
    rm -f "$PID_FILE"
  fi
}
trap cleanup EXIT
trap 'exit 0' INT TERM

"$PYTHON_BIN" -m uvicorn config.asgi:application --host "$(configured_bind_host)" --port "$(configured_port)" --no-access-log &
server_pid=$!
echo "$server_pid" > "$PID_FILE"
wait "$server_pid"
