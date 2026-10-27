"""
The trader's own grid style, tested WITHOUT the 25%-of-margin stop rule:
range -20% / +25% around price (like DOODUSDT 0.0016-0.0025 opened near 0.0020),
200 arithmetic grids, 5x, $50, stop 0.2% beyond the edge, held up to 7 days.
Entries: short grids after a spike (close > EMA20 + 3 ATR on 1h), short / neutral
with no filter, one bot per coin at a time. Also reports how many of these
would be rejected by the 25% rule and the liquidation-distance rule.

Run:  python research/grid/trader_style.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.grid.run import STRATS, _pf, load, prepare  # noqa: E402
from research.grid.sim import (  # noqa: E402
    MAKER_FEE, MMR, MODES, OK, REJ_LIQ, REJ_LOSS, SKIP, SLIPPAGE, TAKER_FEE, REASONS, run_batch,
)

R = 12.5


def main() -> None:
    coins, uni = load()
    prep = prepare(coins)
    btc = coins["BTC"]
    lo_t = btc.index[0] + pd.Timedelta(days=10)
    mid = lo_t + (btc.index[-1] - lo_t) / 2
    rows = []
    for name, kind, mode in [("short_spike3", "spike3", "short"), ("short_always", "always", "short"),
                             ("neutral_always", "always", "neutral")]:
        for lev, n in [(5, 200), (3, 200), (5, 50), (10, 200)]:
            for rules in (False, True):
                recs = []
                for sym, p in prep.items():
                    f, idx = p["f"], p["idx"]
                    t = f.index[p["sig"][kind].to_numpy()]
                    pos = idx.searchsorted(t + pd.Timedelta(hours=1))
                    keep = pos < len(idx) - 1
                    pos, t = pos[keep].astype(np.int64), t[keep]
                    if not len(pos):
                        continue
                    o = p["arr"][0][pos]
                    lo, hi = o * 0.8, o * 1.25
                    out = run_batch(*p["arr"], pos, lo, hi, n, MODES[mode], False, 50.0, float(lev),
                                    0.002, mode != "neutral", 168 * 12,
                                    R if rules else 1e9, 2.0 if rules else 0.0,
                                    MMR, MAKER_FEE, TAKER_FEE, SLIPPAGE, True)
                    tk = out[:, 0] != SKIP
                    d = pd.DataFrame(out[tk][:, [0, 1, 3, 4, 8]], columns=["st", "reason", "pnl", "grid", "wc"])
                    d["t"] = t[tk]
                    d["tier"] = uni.get(sym, {}).get("tier")
                    recs.append(d)
                d = pd.concat(recs)
                ok = d[d.st == OK]
                a, b = ok[ok.t < mid], ok[ok.t >= mid]
                rows.append({"entry": name, "lev": lev, "grids": n, "rules": rules,
                             "signals": len(d), "rej_loss": int((d.st == REJ_LOSS).sum()),
                             "rej_liq": int((d.st == REJ_LIQ).sum()), "n": len(ok),
                             "pf": _pf(ok.pnl), "win": (ok.pnl > 0).mean(),
                             "exp_usd": ok.pnl.mean(), "tot_usd": ok.pnl.sum(),
                             "worst_usd": ok.pnl.min(), "median_wc_usd": d.wc.median(),
                             "pf1": _pf(a.pnl), "pf2": _pf(b.pnl),
                             "stopped": (ok.reason.isin([1, 2])).mean(),
                             "liq": (ok.reason == 3).mean()})
    r = pd.DataFrame(rows)
    out = Path(__file__).resolve().parent / "results" / "trader_style.csv"
    r.round(4).to_csv(out, index=False)
    pd.set_option("display.width", 250)
    print(r.round(3).to_string())


if __name__ == "__main__":
    main()
