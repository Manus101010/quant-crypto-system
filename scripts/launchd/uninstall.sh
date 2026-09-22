#!/bin/bash
# Remove the QuantCore launchd agents (stops auto-start; nothing else touched).
UID_N=$(id -u)
for a in monitor app morningbrief revalidate; do
  launchctl bootout "gui/$UID_N/com.quantcore.$a" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/com.quantcore.$a.plist"
  echo "removed com.quantcore.$a"
done
echo "done."
