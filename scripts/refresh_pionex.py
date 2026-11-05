"""Save Pionex's live crypto USDT perp list to data/pionex_perps.json.

Pionex answers most hosts but returns 403 to GitHub Actions runners, so the
scheduled scanner reads this committed file when the live call fails. Run from
any machine Pionex allows (your laptop, or a Claude session):
    python scripts/refresh_pionex.py && git add data/pionex_perps.json && git commit -m "Refresh Pionex universe" && git push
"""
import datetime as dt
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.exchange import _PIONEX_SYMBOLS_URL, pionex_crypto_bases  # noqa: E402

r = requests.get(_PIONEX_SYMBOLS_URL, timeout=20)
r.raise_for_status()
bases = pionex_crypto_bases(r.json()["data"]["symbols"])
if len(bases) < 100:
    sys.exit(f"Only {len(bases)} symbols came back: file left unchanged.")
out = Path(__file__).resolve().parents[1] / "data" / "pionex_perps.json"
out.write_text(json.dumps({"updated": dt.date.today().isoformat(),
                           "symbols": [f"{b}-USD" for b in bases]}, indent=0))
print(f"saved {len(bases)} Pionex crypto perps -> {out}")
