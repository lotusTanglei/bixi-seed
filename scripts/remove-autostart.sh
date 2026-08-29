#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
uname_name="$(uname -s)"
if [[ "$uname_name" == "Darwin" ]]; then
  plist="$HOME/Library/LaunchAgents/com.bixi.seed.plist"
  launchctl bootout "gui/$(id -u)/com.bixi.seed" 2>/dev/null || true
  rm -f "$plist"
  echo "已移除 macOS 自动启动。"
elif [[ "$uname_name" == "Linux" ]]; then
  systemctl --user disable --now bixi-seed.service 2>/dev/null || true
  rm -f "$HOME/.config/systemd/user/bixi-seed.service"
  systemctl --user daemon-reload 2>/dev/null || true
  echo "已移除 Linux 自动启动。"
else
  echo "不支持的系统: $uname_name" >&2
  exit 1
fi
