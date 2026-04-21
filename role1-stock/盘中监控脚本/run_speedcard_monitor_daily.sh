#!/usr/bin/env bash
# 交易日 9:15 启动速查早盘监控（9:15～9:50 循环，写入 outputs/cache/dashboard_latest.json）
set -euo pipefail
export TZ=Asia/Shanghai
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
exec flock -n /tmp/speedcard_monitor_cron.lock -c "cd \"$SCRIPT_DIR\" && exec /usr/bin/python3 \"$SCRIPT_DIR/speedcard_monitor.py\""
