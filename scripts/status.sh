#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_configuration
port="$(configured_port)"
if server_pid="$(managed_pid)"; then
  echo "进程状态: 运行中 (PID=${server_pid})"
  if health_check; then
    curl --fail --silent --show-error --max-time 2 "http://127.0.0.1:${port}/api/health/"
    echo
    echo "健康状态: 正常"
  else
    echo "健康状态: 不可用" >&2
    exit 1
  fi
else
  echo "进程状态: 已停止"
  rm -f "$PID_FILE"
  exit 1
fi
