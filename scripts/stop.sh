#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"

if server_pid="$(managed_pid)"; then
  kill "$server_pid"
  for _ in $(seq 1 20); do
    kill -0 "$server_pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$server_pid" 2>/dev/null; then kill -9 "$server_pid"; fi
  echo "Bixi Seed 已停止。"
else
  echo "Bixi Seed 当前未运行。"
fi
rm -f "$PID_FILE"
