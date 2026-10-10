"""Save the live list of Bybit crypto USDT perps to data/bybit_perps.json.

Bybit blocks US IPs, so GitHub Actions / Streamlit Cloud can't list its markets;
they read this committed file instead. Run from a machine Bybit allows:
    ./venv/bin/python scripts/refresh_universe.py && git add data/bybit_perps.json && git commit -m "Refresh Bybit universe" && git push
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.exchange import _geo_blocked, list_perp_symbols  # noqa: E402

syms = list_perp_symbols("bybit")
if "bybit" in _geo_blocked or len(syms) < 100:
    sys.exit("Bybit not reachable from here (or too few symbols) — file left unchanged.")
out = Path(__file__).resolve().parents[1] / "data" / "bybit_perps.json"
out.write_text(json.dumps({"updated": dt.date.today().isoformat(), "symbols": syms}, indent=0))
print(f"saved {len(syms)} Bybit perps → {out}")
