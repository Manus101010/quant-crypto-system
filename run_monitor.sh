#!/bin/bash
# Always-on trigger monitor. Signal-only: reads public ccxt data, sends Telegram
# alerts, never trades. Auto-restarts if it crashes (mirrors start.sh).
#
#   ./run_monitor.sh                 # 120s poll, heartbeat log every poll
#   ./run_monitor.sh 60              # 60s poll
#   HEARTBEAT_HOURS=6 ./run_monitor.sh   # + a 'still alive' Telegram every 6h
#
# Confirm it's running:   ps aux | grep "[m]onitor.py"
cd /Users/manusmclaughlin/Desktop/claude-trading-sytem
INTERVAL="${1:-120}"
HB="${HEARTBEAT_HOURS:-0}"
while true; do
  ./venv/bin/python monitor.py --interval "$INTERVAL" --heartbeat-telegram-hours "$HB"
  echo "monitor crashed — restarting in 3s..."
  sleep 3
done
