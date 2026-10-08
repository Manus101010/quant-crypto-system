"""
Data for the intraday overextension-short research (Bybit USDT perps).

1. 1h candles for every Bybit crypto USDT perp since START (4h is resampled).
2. Pump "episodes" found on 1h with a deliberately loose filter (variants are
   stricter): close >= 2.5 x ATR(14) above the 1h EMA20, or +25% in 24h.
3. Around each episode (-24h .. +96h): 15m candles, open-interest history (1h)
   and the coin's funding history. Plus BTC 15m for the whole period.

Run:  ./venv/bin/python research/overext/fetch_data.py out.pkl [start=2025-01-01]
Resumable: re-running continues from what's already saved.
"""
from __future__ import annotations
import pickle
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from utils.exchange import list_perp_symbols  # noqa: E402

H, M15 = 3_600_000, 900_000
_local = {}


def ex() -> ccxt.bybit:
    import threading
    k = threading.get_ident()
    if k not in _local:
        _local[k] = ccxt.bybit({"enableRateLimit": True, "timeout": 20000})
        _local[k].load_markets()
    return _local[k]


def retry(fn, *a, **k):
    for i in range(5):
        try:
            return fn(*a, **k)
        except Exception:                          # noqa: BLE001
            time.sleep(1.5 * (i + 1))
    return None


def candles(sym: str, tf: str, since: int, until: int) -> pd.DataFrame | None:
    step = {"1h": H, "15m": M15}[tf]
    rows, cur = [], since
    while cur < until:
        b = retry(ex().fetch_ohlcv, sym, tf, since=cur, limit=1000)
        if not b:
            break
        rows += [r for r in b if r[0] < until]
        nxt = b[-1][0] + step
        if nxt <= cur or len(b) < 2:
            break
        cur = nxt
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).drop_duplicates("ts")
    df.index = pd.to_datetime(df.pop("ts"), unit="ms")
    return df.sort_index().astype(float)


def episodes(h: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    c = h["close"]
    ema = c.ewm(span=20, adjust=False).mean()
    tr = pd.concat([h["high"] - h["low"], (h["high"] - c.shift()).abs(), (h["low"] - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    hot = ((c - ema) >= 2.5 * atr) | (c / c.shift(24) - 1 >= 0.25)
    out, cur = [], None
    for t in h.index[hot.fillna(False).values]:
        if cur and t - cur[1] <= pd.Timedelta(hours=48):
            cur[1] = t
        else:
            if cur:
                out.append(tuple(cur))
            cur = [t, t]
    if cur:
        out.append(tuple(cur))
    return [(a - pd.Timedelta(hours=24), b + pd.Timedelta(hours=96)) for a, b in out]


def per_coin(t: str, start: int, now: int):
    sym = f"{t.replace('-USD', '')}/USDT:USDT"
    h = candles(sym, "1h", start, now)
    if h is None or len(h) < 200:
        return t, None
    eps = episodes(h)
    m15, oi = [], []
    for a, b in eps:
        a_ms, b_ms = int(a.value // 1e6), min(int(b.value // 1e6), now)
        d = candles(sym, "15m", a_ms, b_ms)
        if d is not None:
            m15.append(d)
        o = retry(ex().fetch_open_interest_history, sym, "1h", since=a_ms, limit=200)
        if o:
            oi += [(x["timestamp"], x.get("openInterestAmount") or x.get("openInterestValue")) for x in o]
    fund = []
    if eps:
        cur = start
        while cur < now:
            f = retry(ex().fetch_funding_rate_history, sym, since=cur, limit=200)
            if not f:
                break
            fund += [(x["timestamp"], x["fundingRate"]) for x in f]
            nxt = f[-1]["timestamp"] + 1
            if nxt <= cur or len(f) < 2:
                break
            cur = nxt
    rec = {"h1": h, "episodes": eps,
           "m15": pd.concat(m15).sort_index().loc[lambda d: ~d.index.duplicated()] if m15 else None,
           "oi": pd.Series(dict(oi)).sort_index() if oi else None,
           "funding": pd.Series(dict(fund)).sort_index() if fund else None}
    for k in ("oi", "funding"):
        if rec[k] is not None:
            rec[k].index = pd.to_datetime(rec[k].index, unit="ms")
    return t, rec


def main(out: str, start_s: str = "2025-01-01"):
    out = Path(out)
    data = pickle.loads(out.read_bytes()) if out.exists() else {"coins": {}, "btc15": None}
    start = int(pd.Timestamp(start_s).value // 1e6)
    now = int(time.time() * 1000) // H * H
    if data["btc15"] is None:
        data["btc15"] = candles("BTC/USDT:USDT", "15m", start, now)
        print("BTC 15m bars:", len(data["btc15"]), flush=True)
    todo = [t for t in list_perp_symbols("bybit") if t not in data["coins"]]
    print(f"{len(todo)} coins to fetch", flush=True)
    with ThreadPoolExecutor(14) as pool:
        for k, (t, rec) in enumerate(pool.map(lambda t: per_coin(t, start, now), todo), 1):
            data["coins"][t] = rec
            if k % 25 == 0 or k == len(todo):
                out.write_bytes(pickle.dumps(data))
                n_ep = sum(len(r["episodes"]) for r in data["coins"].values() if r)
                print(f"  {k}/{len(todo)} · episodes so far {n_ep}", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
