#!/bin/bash
# Weekly edge-revalidation job. Heavy universe backtest — runs OFF the monitor
# hot path (never inside poll_once). Signal-only, ccxt read-only.
#
# Run once now:
#   ./run_revalidate.sh
#   ./run_revalidate.sh --dry-run     # compute + report, change nothing
#
# Schedule weekly (Sunday 04:00 UTC) with cron — `crontab -e` and add:
#   0 4 * * 0  /Users/manusmclaughlin/Desktop/claude-trading-sytem/run_revalidate.sh >> /Users/manusmclaughlin/Desktop/claude-trading-sytem/data/revalidate.log 2>&1
#
# Or a launchd/systemd timer calling this script weekly. It exits after one run
# (unlike the always-on monitor), so a timer — not a loop — is the right tool.
cd /Users/manusmclaughlin/Desktop/claude-trading-sytem
./venv/bin/python revalidate.py "$@"
