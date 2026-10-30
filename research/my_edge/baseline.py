"""Random entry baseline for each pick: same coin, side, stop %, exit, cost, but entry at
random universe valid hours of the same window (3 draws per real trade).
Also: how often a trade reaches +2/3/4% before its stop (the activation problem).
Run after analyze.py: python research/my_edge/baseline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze as AN      # noqa: E402
import core as C          # noqa: E402
from run import EXITS     # noqa: E402

RNG = np.random.default_rng(5)


def main():
    t, E, X = AN.load_trades()
    pk = pd.read_csv(AN.RES / "picks.csv")
    combos = pk[pk.role.isin(["default", "tuned"])][["fam", "entry", "exit"]].drop_duplicates()
    cache = {}
    out = []
    for _, row in combos.iterrows():
        ei, xi = E.index(row.entry), X.index(row.exit)
        act, tr, tg, mb = EXITS[row.exit]
        for w in ("is", "oos"):
            d = t[(t.e == ei) & (t.x == xi) & (t.win == w)]
            a, b = AN.WIN[w]
            rs = []
            for sym, g in d.groupby("sym", observed=True):
                if sym not in cache:
                    k = C.load(sym)
                    ok = ((k["dvol30"] >= C.MIN_DVOL) & (k["age_h"] >= 720)).to_numpy() & np.isfinite(k["close"].to_numpy())
                    cache[sym] = (k, ok)
                k, ok = cache[sym]
                tc = k.index + pd.Timedelta(hours=1)
                pool = np.flatnonzero(ok & (tc >= a) & (tc < b))
                if len(pool) == 0:
                    continue
                o, h, l, c, f = (k[x].to_numpy() for x in ("open", "high", "low", "close", "fund"))
                for _, tr_ in g.iterrows():
                    for i in RNG.choice(pool, 3):
                        st = c[i] * (1 - tr_.side * tr_.sp)
                        j, net, sp, code, _ = C.sim(o, h, l, c, f, int(i), int(tr_.side), float(st), act, tr, tg, mb, 0.0, bool(k["dead"].iloc[0]))
                        if code != 5:
                            rs.append((net - C.COSTS["taker"]) / sp)
            rs = np.array(rs)
            real = d["r_taker"].to_numpy()
            pf = lambda x: x[x > 0].sum() / -x[x < 0].sum() if (x < 0).any() else np.inf
            out.append({"fam": row.fam, "entry": row.entry, "exit": row.exit, "win": w, "real_n": len(real),
                        "real_pf": pf(real), "real_exp": real.mean() if len(real) else np.nan,
                        "rand_n": len(rs), "rand_pf": pf(rs) if len(rs) else np.nan,
                        "rand_exp": rs.mean() if len(rs) else np.nan})
            print(out[-1], flush=True)
    pd.DataFrame(out).to_csv(AN.RES / "baseline.csv", index=False)


if __name__ == "__main__":
    main()
