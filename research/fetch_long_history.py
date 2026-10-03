"""
Download long daily history (back to 2020) for the backtest universe.

ccxt returns ~1000 candles per call, so we page forward from 2020-01-01 until
today. Tries Binance → Bybit → OKX → MEXC per coin (Binance has the deepest
history). Saves {symbol: DataFrame} + BTC to a pickle; resumable.

Survivorship bias: only coins that still trade today can be fetched — coins that
died (LUNA, FTT, …) are missing, which flatters long setups in 2022. Keep that in
mind when reading any result built on this data.

Run:  ./venv/bin/python research/fetch_long_history.py  [out.pkl]
"""
from __future__ import annotations
import pickle
import sys
import time
from pathlib import Path

import ccxt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting.crypto_optimize import _universe

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/long_history.pkl")
START = "2020-01-01T00:00:00Z"
VENUES = ["binance", "bybit", "okx", "mexc"]
_ex = {n: getattr(ccxt, n)({"enableRateLimit": True}) for n in VENUES}


def fetch(base: str) -> pd.DataFrame | None:
    for name in VENUES:
        ex = _ex[name]
        sym = f"{base}/USDT"
        try:
            since, rows = ex.parse8601(START), []
            while True:
                b = ex.fetch_ohlcv(sym, "1d", since=since, limit=1000)
                if not b:
                    break
                rows += b
                nxt = b[-1][0] + 86_400_000
                if nxt <= since or b[-1][0] > time.time() * 1000 - 2 * 86_400_000:
                    break
                since = nxt
            if len(rows) < 250:
                continue
            df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
            df = df.drop_duplicates("ts")
            df.index = pd.to_datetime(df.pop("ts"), unit="ms")
            return df
        except Exception:                          # noqa: BLE001 — try next venue
            continue
    return None


def main():
    done = pickle.loads(OUT.read_bytes()) if OUT.exists() else {"coins": {}, "btc": None}
    tickers, _ = _universe("mexc", 400, 500)
    todo = [t for t in tickers if t not in done["coins"]]
    print(f"{len(tickers)} coins, {len(todo)} to fetch → {OUT}", flush=True)
    if done["btc"] is None:
        done["btc"] = fetch("BTC")
    for k, t in enumerate(todo, 1):
        df = fetch(t.replace("-USD", ""))
        done["coins"][t] = df
        if k % 20 == 0 or k == len(todo):
            OUT.write_bytes(pickle.dumps(done))
            got = sum(d is not None for d in done["coins"].values())
            print(f"  {k}/{len(todo)} done · {got} with ≥250 days", flush=True)
    span = [d.index.min() for d in done["coins"].values() if d is not None]
    print("BTC from", done["btc"].index.min().date(), "| coins from 2021 or earlier:",
          sum(s.year <= 2021 for s in span), "of", len(span))


if __name__ == "__main__":
    main()
