"""Run every entry variant x every exit on the whole universe; save all trades.
Cost is applied later (it does not change the path): R = (net0 - cost) / stop_pct.
Run: python research/my_edge/run.py [max_coins]  -> research/my_edge/results/trades.parquet
"""
from __future__ import annotations

import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core as C          # noqa: E402
import setups as S        # noqa: E402

import os
OUT = Path(__file__).resolve().parent / os.environ.get("MY_EDGE_OUT", "results")
NAN = float("nan")
EXITS = {}
for a in (0.0, 0.01, 0.02, 0.03, 0.04):
    for tr in (0.03, 0.05, 0.07):
        EXITS[f"act{int(a*100)}_tr{int(tr*100)}"] = (a, tr, NAN, 168)
EXITS["T2R_48h"] = (0.0, NAN, 2.0, 48)       # what the earlier studies used
EXITS["T1R_24h"] = (0.0, NAN, 1.0, 24)
ENTRIES = S.entry_names()


def run_coin(sym: str) -> pd.DataFrame | None:
    k = C.load(sym)
    if k is None:
        return None
    k = k[k.index >= C.PRE_START - pd.Timedelta(days=40)]
    if len(k) < 24 * 40:
        return None
    sig, _ = S.signals(k)
    o, h, l, c, f = (k[x].to_numpy() for x in ("open", "high", "low", "close", "fund"))
    dead = bool(k["dead"].iloc[0])
    t_close = (k.index + pd.Timedelta(hours=1)).to_numpy()
    rows = []
    for ei, en in enumerate(ENTRIES):
        ii, side, stops = sig[en]
        if len(ii) == 0:
            continue
        keep = t_close[ii] >= np.datetime64(C.PRE_START)
        ii, stops = ii[keep], stops[keep]
        for xi, (xn, (act, tr, tg, mb)) in enumerate(EXITS.items()):
            busy = -1
            for i, st in zip(ii, stops):
                if i <= busy:
                    continue
                risk = (c[i] - st) * side / c[i]
                if not np.isfinite(risk) or risk < C.MIN_STOP or risk > C.MAX_STOP:
                    continue
                j, net, sp, code, gross = C.sim(o, h, l, c, f, int(i), side, float(st), act, tr, tg, mb, 0.0, dead)
                busy = j
                if code == 5:
                    continue
                rows.append((ei, xi, i, side, net, sp, code, j - i))
    if not rows:
        return None
    a = np.array(rows, dtype=float)
    df = pd.DataFrame({"e": a[:, 0].astype(np.int16), "x": a[:, 1].astype(np.int8),
                       "t": t_close[a[:, 2].astype(int)], "side": a[:, 3].astype(np.int8),
                       "net0": a[:, 4].astype(np.float32), "sp": a[:, 5].astype(np.float32),
                       "code": a[:, 6].astype(np.int8), "hold": a[:, 7].astype(np.int16)})
    df["sym"] = sym
    return df


def main(maxc=None):
    OUT.mkdir(exist_ok=True)
    syms = C.universe_symbols()
    if maxc:
        syms = syms[:maxc]
    print(len(syms), "symbols", len(ENTRIES), "entries", len(EXITS), "exits", flush=True)
    t0 = time.time()
    parts = []
    with Pool(2) as p:
        for n, df in enumerate(p.imap_unordered(run_coin, syms, chunksize=4), 1):
            if df is not None:
                parts.append(df)
            if n % 50 == 0:
                print(n, f"{time.time()-t0:.0f}s", sum(len(x) for x in parts), flush=True)
    tr = pd.concat(parts, ignore_index=True)
    tr["sym"] = tr["sym"].astype("category")
    tr.to_parquet(OUT / "trades.parquet")
    pd.Series(ENTRIES).to_csv(OUT / "entries.csv")
    pd.Series(list(EXITS)).to_csv(OUT / "exits.csv")
    print("saved", len(tr), f"{time.time()-t0:.0f}s")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
