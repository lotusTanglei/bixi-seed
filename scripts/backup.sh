#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
cd "$PROJECT_ROOT"
require_environment
"$PYTHON_BIN" manage.py backup_data
