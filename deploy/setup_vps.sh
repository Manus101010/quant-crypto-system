#!/usr/bin/env bash
# One-shot VPS installer (Ubuntu 22.04, x86 or ARM). Idempotent — safe to re-run.
# Installs Python + deps, builds the venv, and registers the systemd services
# (Linux equivalent of the Mac launchd agents):
#   quantcore-monitor      always-on alert poller
#   quantcore-app          Streamlit UI on :8502
#   quantcore-morningbrief daily 08:00 (timer)
#   quantcore-revalidate   weekly Sun 04:00 (timer)
#
# Prereqs: repo cloned, and a .env file present in the repo root (secrets).
# Run from the repo root:   bash deploy/setup_vps.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(whoami)"
PY=python3
cd "$REPO"

echo "==> Repo: $REPO   User: $USER_NAME"

# 1) System packages
echo "==> Installing system packages (sudo) ..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-dev build-essential git curl

# 2) venv + deps
if [ ! -d venv ]; then
  echo "==> Creating venv ..."
  $PY -m venv venv
fi
echo "==> Installing Python deps (this can take a few minutes) ..."
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

# 3) .env check
if [ ! -f .env ]; then
  echo "!! No .env found in $REPO."
  echo "!! Create it with your keys before the services will work:"
  echo "     ANTHROPIC_API_KEY=..., FRED_API_KEY=..., TELEGRAM_BOT_TOKEN=..., TELEGRAM_CHAT_ID=..."
  echo "   (Then re-run this script, or just: sudo systemctl restart quantcore-monitor)"
fi

mkdir -p data

# 4) systemd units
write_unit () { echo "$2" | sudo tee "/etc/systemd/system/$1" >/dev/null; echo "   wrote $1"; }

echo "==> Writing systemd units ..."
write_unit quantcore-monitor.service "[Unit]
Description=QuantCore alert monitor
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$REPO
ExecStart=$REPO/venv/bin/python monitor.py --interval 120 --heartbeat-telegram-hours 12
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target"

write_unit quantcore-app.service "[Unit]
Description=QuantCore Streamlit app
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$REPO
ExecStart=$REPO/venv/bin/streamlit run app.py --server.port 8502 --server.address 0.0.0.0 --server.headless true
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target"

write_unit quantcore-morningbrief.service "[Unit]
Description=QuantCore morning brief
[Service]
Type=oneshot
User=$USER_NAME
WorkingDirectory=$REPO
ExecStart=$REPO/venv/bin/python morning_brief.py"

write_unit quantcore-morningbrief.timer "[Unit]
Description=QuantCore morning brief daily 08:00
[Timer]
OnCalendar=*-*-* 08:00:00
Persistent=true
[Install]
WantedBy=timers.target"

write_unit quantcore-revalidate.service "[Unit]
Description=QuantCore weekly edge revalidation
[Service]
Type=oneshot
User=$USER_NAME
WorkingDirectory=$REPO
ExecStart=$REPO/venv/bin/python revalidate.py"

write_unit quantcore-revalidate.timer "[Unit]
Description=QuantCore revalidation weekly Sun 04:00
[Timer]
OnCalendar=Sun *-*-* 04:00:00
Persistent=true
[Install]
WantedBy=timers.target"

# 5) enable + start
echo "==> Enabling services ..."
sudo systemctl daemon-reload
sudo systemctl enable --now quantcore-monitor.service quantcore-app.service
sudo systemctl enable --now quantcore-morningbrief.timer quantcore-revalidate.timer

echo
echo "==> Status:"
systemctl --no-pager --lines=0 status quantcore-monitor quantcore-app 2>/dev/null | grep -E "quantcore|Active:" || true
echo
echo "Done. App on this box: http://127.0.0.1:8502 (reach it from your phone via Tailscale)."
echo "Logs:  journalctl -u quantcore-monitor -f   /   journalctl -u quantcore-app -f"
