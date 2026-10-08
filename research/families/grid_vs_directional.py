"""
Round 2 (#1b): for the setups that PASSED in round 1, is a short GRID a better way
to execute than a plain short with a stop? Same signal days, 25 most liquid coins,
the 5-minute window only (so samples are small; read as directional evidence).

Directional = the round-1 plan (daily simulation, 0.36% cost), as % of notional.
Grid        = short grid, +/-2.5 ATR, 30 grids, hold at the edges, 7 days,
              0.02% per fill, as % of notional (1x).

Run:  ./venv/bin/python research/families/grid_vs_directional.py history.pkl m5.pkl [report.md]
"""
from __future__ import annotations
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.families import exhaustion as E  # noqa: E402
from research.families.breakout import events, plan_for  # noqa: E402
from research.families.common import MIN_VOL_USD, prepare, simulate  # noqa: E402
from research.families.grids_5m import sim  # noqa: E402


def signals(x):
    fade = E.signal("short", 2.0, 2.5, 1.0, "none")(x) & (x["btc_regime"] == "MIXED") & (x["c"] < x["sma200"])
    out = [(i, "bounce fade", E.plan("short", "ema20")(x, i)) for i in np.flatnonzero(fade.fillna(False).values)]
    for i, level, edge in events(x, "short", 0.10, 1.5, "post-trend", "prepos"):
        if x["btc_regime"].iat[i] != "DOWN":
            out.append((i, "distribution short", plan_for(x, i, "short", "trail", level, edge)))
    return out


def main(hist, m5_path, out=None):
    ind, _ = prepare(hist)
    m5 = pickle.loads(Path(m5_path).read_bytes())
    rows = []
    for sym, df in m5.items():
        if df is None or sym not in ind:
            continue
        x = ind[sym]
        ts = df.index.values
        o, h, l, c = (df[k].values.astype(np.float64) for k in ("open", "high", "low", "close"))
        for i, name, plan in signals(x):
            d = x.index[i]
            if d < df.index[0].normalize() or x["qvol20"].iat[i] < MIN_VOL_USD or plan is None:
                continue
            t = simulate(x, i, plan)
            if t is None:
                continue
            s = d + pd.Timedelta(days=1)
            i0, i1 = np.searchsorted(ts, np.datetime64(s)), np.searchsorted(ts, np.datetime64(s + pd.Timedelta(days=7)))
            if i1 - i0 < 288:
                continue
            atr, center = float(x["atr"].iat[i]), float(c[i0 - 1])
            pnl, worst, killed, fills = sim(o[i0:i1], h[i0:i1], l[i0:i1], c[i0:i1], center,
                                            center - 2.5 * atr, 5 * atr / 30, 30, 2, False)
            rows.append({"setup": name, "sym": sym, "date": d.date(),
                         "directional": t["ret_pct"] - 0.36, "grid": 100 * pnl})
    df = pd.DataFrame(rows)
    lines = ["# Passing setups: plain short vs short grid (5-minute window)\n",
             "| setup | signals | directional mean % | directional win | grid mean % | grid win | grid better in |",
             "|---|---|---|---|---|---|---|"]
    for name, g in df.groupby("setup") if len(df) else []:
        lines.append(f"| {name} | {len(g)} | {g['directional'].mean():+.2f}% | {100*(g['directional']>0).mean():.0f}% | "
                     f"{g['grid'].mean():+.2f}% | {100*(g['grid']>0).mean():.0f}% | "
                     f"{100*(g['grid']>g['directional']).mean():.0f}% of signals |")
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text)
    print(text)


if __name__ == "__main__":
    a = sys.argv
    main(a[1], a[2], a[3] if len(a) > 3 else None)
