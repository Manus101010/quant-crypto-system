"""Save Bybit's crypto USDT perps to data/bybit_perps.json via CoinGecko.

Bybit's own API blocks US hosts (GitHub runners, Claude sessions). CoinGecko lists
Bybit's derivatives and tags each with a coin id; stocks and other real world
assets carry no coin id or an rwa id, so they drop out. Stablecoin perps dropped too.
    python scripts/refresh_bybit_cg.py && git add -f data/bybit_perps.json && git commit -m "Refresh Bybit universe" && git push
"""
import datetime as dt
import json
import sys
from pathlib import Path

import requests

URL = "https://api.coingecko.com/api/v3/derivatives/exchanges/bybit?include_tickers=unexpired"
STABLE = {"USDC", "USDE", "USD1", "RLUSD", "FDUSD", "USDT", "DAI", "TUSD", "PYUSD", "USDD"}
r = requests.get(URL, timeout=60)
r.raise_for_status()
t = r.json().get("tickers", [])
bases = sorted({x["base"].upper() for x in t
                if x.get("contract_type") == "perpetual" and str(x.get("target", "")).upper() == "USDT"
                and x.get("coin_id") and not x.get("rwa_id")} - STABLE)
if len(bases) < 300:
    sys.exit(f"Only {len(bases)} came back: file left unchanged.")
out = Path(__file__).resolve().parents[1] / "data" / "bybit_perps.json"
out.write_text(json.dumps({"updated": dt.date.today().isoformat(), "source": "coingecko",
                           "symbols": [f"{b}-USD" for b in bases]}, indent=0))
print(f"saved {len(bases)} Bybit crypto perps -> {out}")
