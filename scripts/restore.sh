#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
cd "$PROJECT_ROOT"
require_environment

if [[ $# -ne 1 ]]; then
  echo "用法: ./restore.sh <备份文件路径>" >&2
  exit 2
fi
if server_pid="$(managed_pid)" || health_check; then
  echo "请先运行 ./stop.sh 停止服务，再执行恢复。当前 PID=${server_pid}。" >&2
  exit 1
fi

"$PYTHON_BIN" manage.py restore_data --input "$1"
"$PYTHON_BIN" manage.py migrate --noinput
"$PROJECT_ROOT/scripts/start.sh"
