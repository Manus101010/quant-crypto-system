"""
Research: which BTC trend filter for longs, over a FULL cycle (2020 → now)?

Uses research/fetch_long_history.py data (2021 top, 2022 crash, recovery).
Each long trade (production signals + management, 0.36% cost) gets a size
multiplier from the BTC state on its entry day; equity in R booked at exit.
Survivorship bias: dead coins (LUNA, FTT…) are missing → 2022 looks kinder
than it was for longs.

Run:  ./venv/bin/python research/btc_filter_long.py  long_history.pkl
"""
import pickle, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.garch_storm import curve_stats
from backtesting.crypto_optimize import _signals, _simulate, management_for
from backtesting.crypto_validation import _apply_costs
from backtesting.setup_validation import _MIN_HISTORY

LONGS = ["Relative Strength Leader", "Momentum Runner", "Donchian Breakout (55d)"]
d = pickle.load(open(sys.argv[1], "rb"))
btc = d["btc"]["close"]; btc.index = btc.index.normalize()
ma = {n: btc.rolling(n).mean() for n in (50, 100, 200)}

def above(n, day):
    v = ma[n].get(day)
    return pd.notna(v) and btc.get(day, 0) > v

RULES = {
    "no filter":                 lambda day: 1.0,
    "BTC>200d (current)":        lambda day: 1.0 if above(200, day) else 0.0,
    "BTC>100d":                  lambda day: 1.0 if above(100, day) else 0.0,
    "BTC>50d":                   lambda day: 1.0 if above(50, day) else 0.0,
    "two-stage ½<50d, 0<200d":   lambda day: (1.0 if above(50, day) else 0.5) if above(200, day) else 0.0,
    "200d AND 50d":              lambda day: 1.0 if above(200, day) and above(50, day) else 0.0,
}

trades = []
for sym, df in d["coins"].items():
    if df is None or len(df) < _MIN_HISTORY + 20:
        continue
    df = df.copy(); df.index = df.index.normalize()
    v = df["volume"] if "volume" in df.columns else None
    for i, ind in _signals(df["close"], df["high"], df["low"], v, btc):
        if ind["_label"] not in LONGS:
            continue
        t = _simulate(df["close"], df["high"], df["low"], i, ind, management_for(ind["_label"]))
        if t:
            t["entry"] = df.index[i]
            t["exit"] = df.index[min(i + max(t["bars_held"], 1), len(df) - 1)]
            trades.append(t)
trades = _apply_costs(trades, 0.36)
print(f"{len(trades)} long trades, {min(t['entry'] for t in trades).date()} → {max(t['entry'] for t in trades).date()}\n")

years = sorted({t["entry"].year for t in trades})
hdr = f"{'rule':<26}{'trades':>7}{'totR':>8}{'maxDD':>8}{'worstM':>8}{'ret/dd':>7}  " + "".join(f"{y:>8}" for y in years)
print(hdr)
for name, rule in RULES.items():
    rows = []
    for t in trades:
        m = rule(t["entry"])
        if m > 0:
            rows.append({"R": t["r_mult"] * m, "exit": t["exit"], "y": t["entry"].year})
    a = curve_stats(rows)
    by = {y: sum(r["R"] for r in rows if r["y"] == y) for y in years}
    print(f"{name:<26}{a['n']:>7}{a['totR']:>8.0f}{a['maxDD']:>8.0f}{a['worstM']:>8.0f}{a['ret/dd']:>7.2f}  "
          + "".join(f"{by[y]:>8.0f}" for y in years))
print("\nyear columns = total R from trades entered that year")
