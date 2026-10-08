"""
Fetch full-cycle DAILY history for the research families.

Universe = MEXC USDT perpetuals (what you actually trade), ranked by 24h quote
volume, minus stablecoins / wrapped tokens / tokenised stocks. Candles come from
MEXC spot first (your venue), falling back to OKX when MEXC's history is shorter.

Output format matches research/fetch_long_history.py so the existing research
scripts can read it too:  {"coins": {"SOL-USD": DataFrame, ...}, "btc": DataFrame}

Survivorship bias: only coins listed TODAY are fetched. Dead coins (LUNA, FTT...)
are missing, which flatters LONG results in 2022 and understates short results.

Run:  ./venv/bin/python research/families/fetch_history.py [out.pkl] [top_n]
"""
from __future__ import annotations
import pickle
import sys
import time
from pathlib import Path

import ccxt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from utils.crypto_universe import _BLOCKLIST  # noqa: E402

START = "2020-01-01T00:00:00Z"
DAY = 86_400_000


def _client(name: str):
    ex = getattr(ccxt, name)({"enableRateLimit": True, "timeout": 30000})
    ex.session.trust_env = True        # honour HTTPS_PROXY / CA bundle env if set
    return ex


def _retry(fn, *a, tries: int = 4, **kw):
    for k in range(tries):
        try:
            return fn(*a, **kw)
        except (ccxt.NetworkError, ccxt.RequestTimeout):
            if k == tries - 1:
                raise
            time.sleep(3 * (k + 1))


MEXC, OKX = _client("mexc"), _client("okx")


def universe(top_n: int) -> list[str]:
    mk = _retry(MEXC.load_markets)
    swaps = [m for m in mk.values()
             if m.get("swap") and m.get("active") and m.get("quote") == "USDT"]
    spot_bases = {m["base"] for m in mk.values()
                  if m.get("spot") and m.get("active") and m.get("quote") == "USDT"}
    tick = _retry(MEXC.fetch_tickers, [m["symbol"] for m in swaps])
    rows = []
    for m in swaps:
        base = str(m["base"]).upper()
        if base in _BLOCKLIST or base not in spot_bases:
            continue                    # no spot pair = tokenised stock / index perp
        if any(base.endswith(s) for s in ("3L", "3S", "5L", "5S", "UP", "DOWN")):
            continue
        qv = (tick.get(m["symbol"]) or {}).get("quoteVolume") or 0
        rows.append((qv, base))
    rows.sort(reverse=True)
    seen, out = set(), []
    for _, b in rows:
        if b not in seen:
            seen.add(b); out.append(b)
    return out[:top_n]


def _page(ex, sym: str, limit: int) -> list:
    """Page BACKWARDS from today in fixed windows. Paging forward from 2020 fails
    for coins listed later (the venue returns an empty first page)."""
    start, rows = ex.parse8601(START), []
    win = 250                                     # days per window (< every venue cap)
    end = int(time.time() * 1000) // DAY * DAY
    while end > start:
        since = max(start, end - win * DAY)
        b = _retry(ex.fetch_ohlcv, sym, "1d", since=since, limit=limit)
        b = [r for r in (b or []) if since <= r[0] < end + DAY]
        if not b:
            break                                 # nothing older: listing date reached
        rows = b + rows
        end = since - DAY
    return rows


def fetch(base: str) -> pd.DataFrame | None:
    best = None
    for ex, lim in ((MEXC, 300), (OKX, 300)):
        try:
            rows = _page(ex, f"{base}/USDT", lim)
        except Exception:                               # noqa: BLE001
            continue
        if len(rows) < 250:
            continue
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df = df.drop_duplicates("ts").sort_values("ts")
        df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("ts"), unit="ms")).normalize()
        df = df[~df.index.duplicated()]
        if best is None or df.index.min() < best.index.min() - pd.Timedelta(days=60):
            best = df
        if best.index.min() <= pd.Timestamp("2020-02-01"):
            break                                      # already full depth
    return best


def main():
    OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/families_history.pkl")
    TOP_N = int(sys.argv[2]) if len(sys.argv) > 2 else 250
    done = pickle.loads(OUT.read_bytes()) if OUT.exists() else {"coins": {}, "btc": None}
    bases = universe(TOP_N)
    todo = [b for b in bases if f"{b}-USD" not in done["coins"]]
    print(f"{len(bases)} coins, {len(todo)} to fetch -> {OUT}", flush=True)
    if done["btc"] is None:
        done["btc"] = fetch("BTC")
    for k, b in enumerate(todo, 1):
        done["coins"][f"{b}-USD"] = fetch(b)
        if k % 25 == 0 or k == len(todo):
            OUT.write_bytes(pickle.dumps(done))
            got = sum(d is not None for d in done["coins"].values())
            print(f"  {k}/{len(todo)} · {got} with >=250 days", flush=True)
    span = [d.index.min() for d in done["coins"].values() if d is not None]
    print("BTC from", done["btc"].index.min().date(), "| coins with data:", len(span),
          "| from 2021 or earlier:", sum(s.year <= 2021 for s in span))


if __name__ == "__main__":
    main()
