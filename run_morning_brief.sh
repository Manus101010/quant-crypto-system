#!/bin/bash
# Scheduled Morning Brief. Reliable code/ccxt path — does NOT need TradingView
# open. Signal-only. Runs once and exits (a timer, not a loop).
#
#   ./run_morning_brief.sh              # build + send to Telegram
#   ./run_morning_brief.sh --dry-run    # print, don't send
#
# Schedule daily at 08:00 local with cron — `crontab -e` and add:
#   0 8 * * *  /Users/manusmclaughlin/Desktop/claude-trading-sytem/run_morning_brief.sh >> /Users/manusmclaughlin/Desktop/claude-trading-sytem/data/morning_brief.log 2>&1
cd /Users/manusmclaughlin/Desktop/claude-trading-sytem
./venv/bin/python morning_brief.py "$@"
