"""Activation problem: for each pick's trades (default exit), the best favourable move
reached BEFORE the initial stop was hit (7 day cap), and what a 5% trail locks in.
With a stop of s% and a 5% trail from the best price, the trail only sits above the
initial stop once the best move exceeds about (5 - s)%, and only locks profit after
about +5.3%. Run after analyze.py: python research/my_edge/mfe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze as AN      # noqa: E402
import core as C          # noqa: E402


def mfe_before_stop(o, h, l, c, i, side, stop, mb=168):
    best = 0.0
    e = c[i]
    for j in range(i + 1, min(len(c), i + mb + 1)):
        if not np.isfinite(c[j]):
            break
        if (side == 1 and l[j] <= stop) or (side == -1 and h[j] >= stop):
            break
        best = max(best, ((h[j] if side == 1 else l[j]) - e) * side / e)
    return best


def main():
    t, E, X = AN.load_trades()
    pk = pd.read_csv(AN.RES / "picks.csv")
    rows = []
    cache = {}
    for (fam, en), _ in pk.groupby(["fam", "entry"]):
        d = t[(t.e == E.index(en)) & (t.x == X.index(AN.DEFAULT_X)) & (t.win.isin(["is", "oos"]))]
        m = []
        for sym, g in d.groupby("sym", observed=True):
            if sym not in cache:
                cache[sym] = C.load(sym)
            k = cache[sym]
            o, h, l, c = (k[x].to_numpy() for x in ("open", "high", "low", "close"))
            pos = k.index.get_indexer(g["t"] - pd.Timedelta(hours=1))
            for i, side, sp in zip(pos, g["side"], g["sp"]):
                st = c[i] * (1 - side * sp)
                m.append(mfe_before_stop(o, h, l, c, i, side, st))
        m = np.array(m) * 100
        rows.append({"fam": fam, "entry": en, "n": len(m), "stop_med": d.sp.median() * 100,
                     **{f"reach_{x}pct": (m >= x).mean() for x in (1, 2, 3, 4, 5.3, 8, 10, 15)},
                     "mfe_med": np.median(m)})
        print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(AN.RES / "mfe.csv", index=False)


if __name__ == "__main__":
    main()
