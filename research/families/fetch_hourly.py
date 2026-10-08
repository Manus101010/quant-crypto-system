"""
Fetch HOURLY candles for the grid research. Daily bars badly undercount grid fills
(a grid lives on intraday chop), so grids are simulated on 1h paths.

Takes the most liquid coins from the daily history file (by recent quote volume).

Run:  ./venv/bin/python research/families/fetch_hourly.py daily.pkl out_1h.pkl [n_coins] [start]
"""
from __future__ import annotations
import pickle
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.families.fetch_history import MEXC, OKX, _retry  # noqa: E402

HOUR = 3_600_000


def page_hourly(ex, sym: str, start_ms: int) -> list:
    rows, win = [], 300
    end = int(time.time() * 1000) // HOUR * HOUR
    while end > start_ms:
        since = max(start_ms, end - win * HOUR)
        b = _retry(ex.fetch_ohlcv, sym, "1h", since=since, limit=win)
        b = [r for r in (b or []) if since <= r[0] < end + HOUR]
        if not b:
            break
        rows = b + rows
        end = since - HOUR
    return rows


def main(daily, out, n=60, start="2024-06-01"):
    d = pickle.loads(Path(daily).read_bytes())
    vol = {s: float((df["close"] * df["volume"]).tail(60).mean())
           for s, df in d["coins"].items() if df is not None and len(df) >= 400}
    syms = sorted(vol, key=lambda s: -vol[s])[:n]
    done = pickle.loads(Path(out).read_bytes()) if Path(out).exists() else {}
    st = MEXC.parse8601(f"{start}T00:00:00Z")
    for k, s in enumerate(syms, 1):
        if s in done:
            continue
        base = s.replace("-USD", "")
        rows = []
        for ex in (MEXC, OKX):
            try:
                rows = page_hourly(ex, f"{base}/USDT", st)
            except Exception:                           # noqa: BLE001
                rows = []
            if len(rows) > 2000:
                break
        if rows:
            df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
            df = df.drop_duplicates("ts").sort_values("ts")
            df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("ts"), unit="ms"))
            done[s] = df
        if k % 10 == 0 or k == len(syms):
            Path(out).write_bytes(pickle.dumps(done))
            print(f"  {k}/{len(syms)}", flush=True)
    Path(out).write_bytes(pickle.dumps(done))


if __name__ == "__main__":
    a = sys.argv
    main(a[1], a[2], int(a[3]) if len(a) > 3 else 60, a[4] if len(a) > 4 else "2024-06-01")
