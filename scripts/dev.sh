#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
cd "$PROJECT_ROOT"
require_environment
require_configuration
"$PYTHON_BIN" -m uvicorn config.asgi:application --host 127.0.0.1 --port 8000 --reload > "$LOG_DIR/dev-server.log" 2>&1 &
backend_pid=$!
cleanup() {
  kill "$backend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
cd "$PROJECT_ROOT/frontend"
npm run dev
