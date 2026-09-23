# Deploy to a free always-on VPS (Oracle Cloud)

Runs the whole system off your laptop, for $0, on an Oracle Always-Free VM.
The TradingView bridge stays on your Mac (attended); everything unattended —
monitor, app, morning brief, weekly revalidation — runs on the server.

## 1. Create the server (Oracle Cloud console)
- Image: **Ubuntu 22.04**
- Shape: **VM.Standard.A1.Flex** (ARM, free — 2 OCPU / 12 GB). If "out of
  capacity", try another Availability Domain or **VM.Standard.E2.1.Micro** (AMD, 1 GB).
- Region: **EU/Asia, not US** (US IPs are Binance-geoblocked).
- Save the SSH **private key** it offers, note the **public IP**.

## 2. Install (from your Mac terminal)
```bash
chmod 600 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@<PUBLIC_IP>

# on the server:
git clone https://github.com/Manus101010/quant-crypto-system.git
cd quant-crypto-system
nano .env        # paste ANTHROPIC_API_KEY / FRED_API_KEY / TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
bash deploy/setup_vps.sh
```
That installs Python + deps and registers the systemd services (monitor + app
always-on, brief daily, revalidation weekly). You'll get a Telegram "Monitor
started" from the server within a minute.

## 3. Reach the app from your phone (Tailscale, free, private)
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up          # opens a login URL — approve it
tailscale ip -4            # note the 100.x.y.z address
```
Install Tailscale on your phone (same account), then open
`http://100.x.y.z:8502` — works anywhere, laptop off, nobody else can reach it.
Leave the Oracle firewall closed for 8502 (only SSH open); Tailscale is the door.

## Managing it
```bash
systemctl status quantcore-monitor quantcore-app
journalctl -u quantcore-monitor -f          # live alert log
git pull && sudo systemctl restart quantcore-monitor quantcore-app   # deploy an update
```

## Data migration (optional)
The server starts with a fresh DB (empty triggers/watchlist). To carry over your
current state, copy the SQLite file up once:
```bash
scp -i ~/Downloads/ssh-key-*.key data/trading.db ubuntu@<PUBLIC_IP>:~/quant-crypto-system/data/
scp -i ~/Downloads/ssh-key-*.key data/crypto_validation.json ubuntu@<PUBLIC_IP>:~/quant-crypto-system/data/
```
