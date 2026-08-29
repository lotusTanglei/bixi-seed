#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
cd "$PROJECT_ROOT"
require_environment
require_configuration
uname_name="$(uname -s)"

if [[ "$uname_name" == "Darwin" ]]; then
  launch_agents="$HOME/Library/LaunchAgents"
  plist="$launch_agents/com.bixi.seed.plist"
  mkdir -p "$launch_agents"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.bixi.seed</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$PROJECT_ROOT/scripts/run-core.sh</string></array>
  <key>WorkingDirectory</key><string>$PROJECT_ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG_DIR/server.out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/server.err.log</string>
</dict></plist>
EOF
  launchctl bootout "gui/$(id -u)/com.bixi.seed" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
  echo "已设置 macOS 登录后自动启动。"
elif [[ "$uname_name" == "Linux" ]]; then
  unit_dir="$HOME/.config/systemd/user"
  unit="$unit_dir/bixi-seed.service"
  mkdir -p "$unit_dir"
  cat > "$unit" <<EOF
[Unit]
Description=Bixi Seed 核心服务
After=default.target

[Service]
WorkingDirectory=$PROJECT_ROOT
ExecStart=/bin/bash $PROJECT_ROOT/scripts/run-core.sh
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now bixi-seed.service
  echo "已设置 Linux 登录后自动启动。"
else
  echo "不支持的系统: $uname_name" >&2
  exit 1
fi
