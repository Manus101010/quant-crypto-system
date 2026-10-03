"""
Research: altcoin-breadth filter + per-setup robustness over the full cycle.

Breadth = share of the universe (coins with history that day) closing above
their own 50-day / 200-day SMA. Longs are taken only when breadth > threshold,
optionally combined with BTC above its 200d AND 50d. Trades are cached to a
pickle so filters can be iterated cheaply.

Run:  ./venv/bin/python research/breadth_long.py long_history.pkl
"""
import pickle, sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.garch_storm import curve_stats
from backtesting.crypto_optimize import _signals, _simulate, management_for
from backtesting.crypto_validation import _apply_costs
from backtesting.setup_validation import _MIN_HISTORY

src = Path(sys.argv[1]); cache = src.with_name("long_trades.pkl")
d = pickle.load(open(src, "rb"))
btc = d["btc"]["close"]; btc.index = btc.index.normalize()
coins = {}
for s, df in d["coins"].items():
    if df is not None and len(df) >= _MIN_HISTORY + 20:
        df = df.copy(); df.index = df.index.normalize(); coins[s] = df

if cache.exists():
    trades = pickle.load(open(cache, "rb"))
else:
    trades = []
    for sym, df in coins.items():
        v = df["volume"] if "volume" in df.columns else None
        for i, ind in _signals(df["close"], df["high"], df["low"], v, btc):
            lab = ind["_label"]
            t = _simulate(df["close"], df["high"], df["low"], i, ind, management_for(lab))
            if t:
                t["entry"] = df.index[i]; t["exit"] = df.index[min(i + max(t["bars_held"], 1), len(df) - 1)]
                trades.append(t)
    trades = _apply_costs(trades, 0.36)
    pickle.dump(trades, open(cache, "wb"))

closes = pd.DataFrame({s: df["close"] for s, df in coins.items()})
breadth = {n: ((closes > closes.rolling(n).mean()).sum(axis=1)
               / closes.rolling(n).mean().notna().sum(axis=1)).where(lambda x: x.notna())
           for n in (50, 200)}
ma = {n: btc.rolling(n).mean() for n in (50, 200)}
def btc_up(day): return all(pd.notna(ma[n].get(day)) and btc.get(day, 0) > ma[n][day] for n in (50, 200))
def br(n, day): return breadth[n].get(day, np.nan)

LONGS = ["Relative Strength Leader", "Momentum Runner", "Donchian Breakout (55d)"]
longs = [t for t in trades if t["setup"] in LONGS]
years = sorted({t["entry"].year for t in longs})
RULES = {
    "BTC 200d&50d (best so far)": lambda t: btc_up(t["entry"]),
    "breadth50 > 50%":            lambda t: br(50, t["entry"]) > 0.5,
    "breadth50 > 60%":            lambda t: br(50, t["entry"]) > 0.6,
    "breadth200 > 50%":           lambda t: br(200, t["entry"]) > 0.5,
    "BTC&50 + breadth50>50%":     lambda t: btc_up(t["entry"]) and br(50, t["entry"]) > 0.5,
    "BTC&50 + breadth200>50%":    lambda t: btc_up(t["entry"]) and br(200, t["entry"]) > 0.5,
    "BTC&50 + breadth50>60%":     lambda t: btc_up(t["entry"]) and br(50, t["entry"]) > 0.6,
}
print(f"{len(longs)} long trades {years[0]}–{years[-1]}\n")
print(f"{'rule':<28}{'trades':>7}{'totR':>8}{'maxDD':>8}{'worstM':>8}{'ret/dd':>7}  " + "".join(f"{y:>7}" for y in years))
for name, f in RULES.items():
    rows = [{"R": t["r_mult"], "exit": t["exit"], "y": t["entry"].year} for t in longs if f(t)]
    a = curve_stats(rows); by = {y: sum(r["R"] for r in rows if r["y"] == y) for y in years}
    print(f"{name:<28}{a['n']:>7}{a['totR']:>8.0f}{a['maxDD']:>8.0f}{a['worstM']:>8.0f}{a['ret/dd']:>7.2f}  " + "".join(f"{by[y]:>7.0f}" for y in years))

print("\nPer setup, full cycle, NO filter → with best filter (BTC 200d&50d):")
print(f"{'setup':<30}{'n':>6}{'PF':>6}{'expR':>8}   {'n':>6}{'PF':>6}{'expR':>8}   PF by year (filtered)")
def pf(p):
    gw = sum(t["ret_pct"] for t in p if t["ret_pct"] > 0); gl = abs(sum(t["ret_pct"] for t in p if t["ret_pct"] <= 0))
    return gw / gl if gl else 0
for lab in sorted({t["setup"] for t in trades}):
    a = [t for t in trades if t["setup"] == lab]
    b = [t for t in a if (btc_up(t["entry"]) if lab in LONGS else True)]
    yr = " ".join(f"{y%100}:{pf([t for t in b if t['entry'].year==y]):.2f}" for y in years if any(t['entry'].year==y for t in b))
    print(f"{lab:<30}{len(a):>6}{pf(a):>6.2f}{np.mean([t['r_mult'] for t in a]):>+8.3f}   {len(b):>6}{pf(b):>6.2f}{np.mean([t['r_mult'] for t in b]) if b else 0:>+8.3f}   {yr}")
