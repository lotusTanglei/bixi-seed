#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
command -v npm >/dev/null 2>&1 || { echo "未找到 npm，请先安装 Node.js LTS。" >&2; exit 1; }
cd "$PROJECT_ROOT/frontend"
npm run build
cd "$PROJECT_ROOT"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  "$PROJECT_ROOT/.venv/bin/python" manage.py collectstatic --noinput
fi
