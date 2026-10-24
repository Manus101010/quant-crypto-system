"""
Fetch 5-minute candles for the grid research (dense grids live on intraday chop;
hourly bars undercount their fills).

Run:  ./venv/bin/python research/families/fetch_intraday.py hourly.pkl out_5m.pkl [n_coins] [days]
      (coins = the n most liquid in the hourly file)
"""
from __future__ import annotations
import pickle
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.families.fetch_history import _client, _retry  # noqa: E402

M5 = 300_000


def page(sym: str, start_ms: int) -> list:
    ex = _client("mexc")                       # one client per thread
    rows, win = [], 300
    end = int(time.time() * 1000) // M5 * M5
    while end > start_ms:
        since = max(start_ms, end - win * M5)
        b = _retry(ex.fetch_ohlcv, sym, "5m", since=since, limit=win)
        b = [r for r in (b or []) if since <= r[0] < end + M5]
        if not b:
            break
        rows = b + rows
        end = since - M5
    return rows


def one(sym: str, start_ms: int):
    try:
        rows = page(f"{sym.replace('-USD', '')}/USDT", start_ms)
    except Exception:                                   # noqa: BLE001
        return sym, None
    if not rows:
        return sym, None
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts")
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("ts"), unit="ms"))
    return sym, df


def main(hourly, out, n=25, days=180):
    h = pickle.loads(Path(hourly).read_bytes())
    vol = {s: float((df["close"] * df["volume"]).tail(24 * 60).mean()) for s, df in h.items()}
    syms = sorted(vol, key=lambda s: -vol[s])[:n]
    start = int(time.time() * 1000) - days * 86_400_000
    done = {}
    with ThreadPoolExecutor(4) as pool:
        for k, (s, df) in enumerate(pool.map(lambda s: one(s, start), syms), 1):
            done[s] = df
            print(f"  {k}/{len(syms)} {s} {0 if df is None else len(df)}", flush=True)
    Path(out).write_bytes(pickle.dumps(done))


if __name__ == "__main__":
    a = sys.argv
    main(a[1], a[2], int(a[3]) if len(a) > 3 else 25, int(a[4]) if len(a) > 4 else 180)
