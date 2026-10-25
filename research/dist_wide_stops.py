"""
Research (Oct 25 2026): Distribution Short by stop distance.

Live scans drop any setup whose stop is > 25% away (AUTO_SCAN_PARAMS
max_stop_pct). Distribution Short's 3.5xATR stop is wider than that on most
small caps, so ~16 of ~19 signals in Oct 11-24 were dropped. Does the edge hold
on wide-stop signals? (Sizing still caps the loss: a wide stop just means a
smaller position, leverage < 1.) Same simulation as research/bear_shorts.py.

Run:  ./venv/bin/python research/dist_wide_stops.py ~/quantcore_cache/long_history.pkl
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.bear_shorts import ind, families, sim_short  # noqa: E402


def main(pkl):
    d = pickle.load(open(pkl, "rb"))
    btc = d["btc"]["close"].copy(); btc.index = btc.index.normalize()
    rows = []
    for sym, df in d["coins"].items():
        if df is None or len(df) < 230:
            continue
        df = df.copy(); df.index = df.index.normalize()
        x = ind(df, btc)
        sig, p = families(df, x)["DIST (live)"]
        c, h, l = df["close"], df["high"], df["low"]
        last = -99
        for i in np.flatnonzero(sig.fillna(False).values):
            if i < 205 or i - last < 5:
                continue
            last = i
            stop = float(p["stop"].iat[i])
            r = sim_short(c, h, l, i, stop, None, 3.5, float(x["atr"].iat[i]), 60)
            if r is not None and np.isfinite(r):
                rows.append((r, df.index[i], (stop / c.iat[i] - 1) * 100))
    T = pd.DataFrame(rows, columns=["r", "d", "stop_pct"])
    pf = lambda a: a[a > 0].sum() / -a[a < 0].sum() if (a < 0).any() else 99
    for lo, hi in [(0, 15), (15, 25), (25, 35), (35, 50), (50, 999), (0, 25), (25, 999), (0, 40), (0, 999)]:
        a = T[(T.stop_pct > lo) & (T.stop_pct <= hi)]
        if len(a) < 5:
            continue
        r = a.r.values; mid = a.d.sort_values().iloc[len(a) // 2]
        t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
        yrs = a.groupby(a.d.dt.year).r.sum()
        print(f"stop {lo:>3}-{hi:<3}%  n={len(a):>4} PF {pf(r):.2f} win {np.mean(r>0)*100:.0f}% avg {r.mean():+.3f} t={t:4.2f} "
              f"halves {pf(a[a.d<mid].r.values):.2f}/{pf(a[a.d>=mid].r.values):.2f} | "
              + " ".join(f"{y}:{v:+.0f}" for y, v in yrs.items()))


if __name__ == "__main__":
    main(sys.argv[1])
