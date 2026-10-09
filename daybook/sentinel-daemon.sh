#!/bin/sh
# Keep the sentinel running.
# Manual: sh sentinel-daemon.sh
# Start at login: add this script under System Settings → General → Login Items.
cd "$(dirname "$0")" || exit 1
pkill -f "sentinel.sh" 2>/dev/null
nohup sh sentinel.sh 卷/*.txt >> .sentinel.log 2>&1 &
echo "Sentinel daemon started, PID $!"
