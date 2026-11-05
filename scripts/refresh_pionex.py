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

# Safety (6 Nov 2026 audit): the scanner prices each Pionex coin from MEXC's perp of
# the "same" coin (alias and 1000x unit mapping in utils.exchange). Drop any coin
# whose MEXC price, scaled, is more than 20% off Pionex: that would be another asset.
try:
    from utils.exchange import _MEXC_ALIAS, _PREFIXES, _split_prefix
    pt = requests.get("https://api.pionex.com/api/v1/market/tickers?type=PERP", timeout=20).json()
    px = {t["symbol"][:-len("_USDT_PERP")]: float(t["close"]) for t in pt["data"]["tickers"]
          if t["symbol"].endswith("_USDT_PERP")}
    mt = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=20).json()
    mx = {t["symbol"][:-len("_USDT")].upper(): float(t["lastPrice"]) for t in mt["data"]
          if t["symbol"].endswith("_USDT")}
    bad = []
    for b in bases:
        name = _MEXC_ALIAS.get(b, b)
        core, mult = _split_prefix(name)
        for cand, factor in [(name, 1.0)] + [((f"{p}{core}" if p > 1 else core), mult / p)
                                             for p in (*_PREFIXES, 1) if p != mult]:
            if cand in mx and b in px and px[b] > 0:
                if abs(mx[cand] * factor / px[b] - 1) > 0.20:
                    bad.append(f"{b}->{cand}")
                break
    if bad:
        print("dropped (MEXC price does not match Pionex):", " ".join(bad))
        bases = [b for b in bases if not any(x.startswith(b + "->") for x in bad)]
except Exception as exc:  # noqa: BLE001
    print(f"price check skipped ({exc}); list saved without it")
if len(bases) < 100:
    sys.exit(f"Only {len(bases)} symbols came back: file left unchanged.")
out = Path(__file__).resolve().parents[1] / "data" / "pionex_perps.json"
out.write_text(json.dumps({"updated": dt.date.today().isoformat(),
                           "symbols": [f"{b}-USD" for b in bases]}, indent=0))
print(f"saved {len(bases)} Pionex crypto perps -> {out}")
