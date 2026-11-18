#!/bin/sh
# Keep the sentinel running.
# 让哨常驻运行。
# Manual: sh sentinel-daemon.sh
# 手动运行：sh sentinel-daemon.sh
# Start at login: add this script under System Settings → General → Login Items.
# 开机自启：在「系统设置 → 通用 → 登录项」里加入本脚本。
cd "$(dirname "$0")" || exit 1
pkill -f "sentinel.sh" 2>/dev/null
nohup sh sentinel.sh 卷/*.txt >> .sentinel.log 2>&1 &
echo "Sentinel daemon started, PID $!"
