#!/bin/bash
# Install the QuantCore launchd agents (auto-start + restart, reboot-proof).
#   monitor      — Telegram alert poller (KeepAlive, RunAtLoad)
#   app          — Streamlit UI on :8502 (KeepAlive, RunAtLoad)
#   morningbrief — daily 08:00 brief
#   revalidate   — weekly Sun 04:00 edge-decay watch
#
# NOTE: launchd writes its own stdout/stderr to ~/Library/Logs (NOT the project
# ~/Desktop path — launchd can't open log files under the TCC-protected Desktop,
# which fails with EX_CONFIG/78). The jobs themselves still read/write the
# project's data/ fine once running.
set -e
UID_N=$(id -u)
SRC="$(cd "$(dirname "$0")" && pwd)"
for a in monitor app morningbrief revalidate; do
  cp "$SRC/com.quantcore.$a.plist" "$HOME/Library/LaunchAgents/"
  launchctl bootout "gui/$UID_N/com.quantcore.$a" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_N" "$HOME/Library/LaunchAgents/com.quantcore.$a.plist"
  echo "loaded com.quantcore.$a"
done
echo "done. Check: launchctl list | grep quantcore"
