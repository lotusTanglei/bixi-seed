#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
cd "$PROJECT_ROOT"
require_environment
require_configuration

if server_pid="$(managed_pid)"; then
  echo "Bixi Seed 已经在运行，PID=${server_pid}。"
  exit 0
fi
rm -f "$PID_FILE"
check_port_available
"$PYTHON_BIN" manage.py check
"$PYTHON_BIN" manage.py migrate --noinput
nohup "$PROJECT_ROOT/scripts/run-core.sh" > "$LOG_DIR/server.out.log" 2> "$LOG_DIR/server.err.log" < /dev/null &

port="$(configured_port)"
bind_host="$(configured_bind_host)"
for _ in $(seq 1 20); do
  sleep 0.25
  if health_check; then
    echo "Bixi Seed 已在后台启动，地址: http://${bind_host}:${port}"
    exit 0
  fi
done
echo "服务进程已启动，但健康检查未通过，请运行 ./logs.sh 查看日志。" >&2
if server_pid="$(managed_pid)"; then
  kill "$server_pid" 2>/dev/null || true
  rm -f "$PID_FILE"
fi
exit 1
