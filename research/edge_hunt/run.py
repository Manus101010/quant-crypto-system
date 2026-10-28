"""
Run all candidate variants, select on in sample (2023-02 .. 2025-06), test the
selection untouched out of sample (2025-07 .. 2026-10).

Selection rule, fixed before looking at OOS: per candidate family, among its
variants with in sample n >= 50 and both in sample halves profitable, take the
highest day clustered t-stat. Families with no such variant fail in sample (their
best IS variant is still shown OOS for honesty, flagged).

Outputs research/edge_hunt/results/{trades.parquet, is_table.csv, oos.csv}
Run: python research/edge_hunt/run.py [max_coins]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as H                                       # noqa: E402
from candidates import features, variants                 # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "results"
STOCKS_HINT = {"PAXG", "XAUT", "BTCDOM", "DEFI", "FOOTBALL", "BLUEBIRD", "AMD", "APLD", "TSLA", "NVDA", "AAPL", "MSTR", "COIN", "HOOD", "META", "GOOGL", "AMZN",
               "MSFT", "PLTR", "CRCL", "SPY", "QQQ", "XAU", "XAG", "INTC", "ORCL", "NFLX", "BABA"}


def crypto_universe(syms: list[str]) -> list[str]:
    bybit = {s.replace("-USD", "") for s in json.loads((ROOT / "data/bybit_perps.json").read_text())["symbols"]}
    # crypto only: listed on Bybit today, OR delisted from Binance before Sep 2026 (dead crypto
    # perps kept to reduce survivorship; Binance's TradFi perps (oil, stocks, ETFs) are all
    # 2026 listings that still trade and are not on Bybit's crypto list, so they drop out)
    out = []
    for s in syms:
        b = s[:-4]
        if b in STOCKS_HINT:
            continue
        if b in bybit or b.replace("1000", "") in bybit or b in ("MATIC", "RNDR"):
            out.append(s)
            continue
        idx = pd.read_parquet(H.H1 / f"{s}.parquet", columns=["close"]).index
        if len(idx) and idx[-1] < pd.Timestamp("2026-09-01"):
            out.append(s)
    return out, bybit


def btc_bear() -> pd.Series:
    b = H.load("BTCUSDT")
    d = b["close"].resample("1D").last()
    bear = (d < d.rolling(50).mean()).shift(1)      # known at the start of each day
    return bear


def main(max_coins: int | None = None):
    OUT.mkdir(exist_ok=True)
    syms, bybit = crypto_universe(H.symbols())
    if max_coins:
        syms = syms[:max_coins]
    V = variants()
    print(f"{len(syms)} symbols, {len(V)} variants", flush=True)
    rows = []
    t0 = time.time()
    for k, sym in enumerate(syms, 1):
        df = H.load(sym)
        if df is None:
            continue
        df = df[df.index >= H.START - pd.Timedelta(days=60)]
        if len(df) < 24 * 5:
            continue
        oi = H.load_oi(sym, df.index)
        f = features(df, oi)
        uni = H.universe_ok(f) & (f.index >= H.START)
        A = H.arrays(f)
        cache = {}
        for name, (cand, fn, need_oi, ex) in V.items():
            if need_oi and oi is None:
                continue
            key = id(fn)
            if key not in cache:
                try:
                    cache[key] = fn(f, uni)
                except Exception as e:                    # noqa: BLE001
                    print("ERR", sym, name, e, flush=True)
                    cache[key] = (np.array([], int), 1, np.array([]))
            idx, side, stop = cache[key]
            if len(idx) == 0:
                continue
            # new listings have 30 to 50% structural stops; allow up to 50% (sized below 1x),
            # the same rule live Distribution Short uses since commit 57f1676
            H.MAX_STOP = 0.50 if cand == "C7" else 0.25
            for t in H.run_signals(A, idx, side, stop, H.EXITS[ex], sym):
                t["variant"] = name
                t["cand"] = cand
                t["on_bybit"] = sym[:-4] in bybit
                rows.append(t)
        if k % 25 == 0:
            print(f"{k}/{len(syms)} {sym} trades {len(rows)} {time.time()-t0:.0f}s", flush=True)
    tr = pd.DataFrame(rows)
    bear = btc_bear()
    tr["btc_bear"] = bear.reindex(tr["entry_t"].dt.floor("D")).to_numpy()
    tr["oos"] = tr["entry_t"] >= H.IS_END
    tr.to_parquet(OUT / "trades.parquet")
    print("saved", len(tr), "trades", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
