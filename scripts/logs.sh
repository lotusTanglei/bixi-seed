#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
log_file="$LOG_DIR/server.err.log"
[[ -f "$log_file" ]] || log_file="$LOG_DIR/django.log"
if [[ ! -f "$log_file" ]]; then echo "暂无日志。"; exit 0; fi
tail -f "$log_file"
