"""
Research: is the long gate too slow / too narrow? Test extra market-state signals
ON TOP of the live gate (BTC > 200d & 50d, alt breadth50 > 60%), 2020-2026.

Signals, all known at the daily close a trade would enter on:
  lower-timeframe BTC   close vs 4h EMA20, 4h EMA20 rising/falling, close vs 1h EMA50
  overheated            BTC daily RSI14 > 75; alt breadth50 > 85%; median alt +25% in 7d
  weekly                bearish engulfing on the last COMPLETED BTC weekly candle
Each is applied as an extra "don't take new longs when…" rule; a few fast-only
gates are also tried as replacements.

Run:  ./venv/bin/python research/regime_signals.py ~/quantcore_cache
      (needs long_history.pkl, long_trades.pkl [from breadth_long.py], btc_1h.pkl)
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.garch_storm import curve_stats  # noqa: E402
from backtesting.setup_validation import _MIN_HISTORY  # noqa: E402

D = Path(sys.argv[1]).expanduser()
hist = pickle.load(open(D / "long_history.pkl", "rb"))
trades = pickle.load(open(D / "long_trades.pkl", "rb"))
b1 = pickle.load(open(D / "btc_1h.pkl", "rb"))
LONGS = ["Relative Strength Leader", "Momentum Runner", "Donchian Breakout (55d)",
         "Volume Breakout", "Squeeze Breakout"]
longs = [t for t in trades if t["setup"] in LONGS]

btc = hist["btc"]["close"]; btc.index = btc.index.normalize()
bd = hist["btc"].copy(); bd.index = bd.index.normalize()
ma = {n: btc.rolling(n).mean() for n in (50, 200)}
coins = {s: df for s, df in hist["coins"].items() if df is not None and len(df) >= _MIN_HISTORY + 20}
closes = pd.DataFrame({s: df["close"].set_axis(df.index.normalize()) for s, df in coins.items()})
valid = closes.rolling(50).mean().notna().sum(axis=1)
breadth = (closes > closes.rolling(50).mean()).sum(axis=1) / valid
alt7 = (closes / closes.shift(7) - 1).median(axis=1)


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


rsi_d = rsi(btc)
# lower timeframes: state at the END of each UTC day (last closed 1h / 4h bar)
c1 = b1["close"]
e50_1h = c1.ewm(span=50, adjust=False).mean()
h4 = b1.resample("4h", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
e20_4h = h4["close"].ewm(span=20, adjust=False).mean()
ltf = pd.DataFrame({"c": c1, "e50_1h": e50_1h})
ltf["e20_4h"] = e20_4h.set_axis(e20_4h.index + pd.Timedelta(hours=4)).reindex(ltf.index + pd.Timedelta(hours=1), method="ffill").to_numpy()
ltf["e20_4h_prev"] = e20_4h.shift(6).set_axis(e20_4h.index + pd.Timedelta(hours=4)).reindex(ltf.index + pd.Timedelta(hours=1), method="ffill").to_numpy()
eod = ltf.groupby(ltf.index.normalize()).last()            # indexed by the day (bar-open date)
# weekly bearish engulfing on the last completed week (weeks end Sunday)
wk = bd.resample("W-SUN").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
eng = (wk["close"] < wk["open"]) & (wk["close"].shift() > wk["open"].shift()) & \
      (wk["open"] >= wk["close"].shift()) & (wk["close"] <= wk["open"].shift())
eng_d = eng.reindex(pd.date_range(wk.index[0], btc.index[-1]), method="ffill")   # known from that Sunday's close


def g(series, day, default=np.nan):
    v = series.get(day, default)
    return v if not isinstance(v, pd.Series) else default


def base(d):
    return (pd.notna(g(ma[200], d)) and btc.get(d, 0) > ma[200][d] and btc[d] > ma[50][d]
            and g(breadth, d, 0) > 0.60)


def up4(d): return d in eod.index and eod.at[d, "c"] > eod.at[d, "e20_4h"]
def rising4(d): return d in eod.index and eod.at[d, "e20_4h"] > eod.at[d, "e20_4h_prev"]
def up1(d): return d in eod.index and eod.at[d, "c"] > eod.at[d, "e50_1h"]
def ltf_bear(d): return d in eod.index and not up4(d) and not up1(d)


RULES = {
    "LIVE gate (BTC 200d&50d + breadth>60%)":       base,
    "+ skip if BTC below 4h EMA20 AND 1h EMA50":    lambda d: base(d) and not ltf_bear(d),
    "+ need BTC above 4h EMA20":                    lambda d: base(d) and up4(d),
    "+ need 4h EMA20 rising":                       lambda d: base(d) and rising4(d),
    "+ need BTC above 1h EMA50":                    lambda d: base(d) and up1(d),
    "+ skip if BTC daily RSI > 75 (overheated)":    lambda d: base(d) and not g(rsi_d, d, 50) > 75,
    "+ skip if breadth > 85% (overheated)":         lambda d: base(d) and not g(breadth, d, 0) > 0.85,
    "+ skip if median alt +25% in 7d":              lambda d: base(d) and not g(alt7, d, 0) > 0.25,
    "+ skip after weekly bearish engulfing":        lambda d: base(d) and not bool(g(eng_d, d, False)),
    "+ 4h up AND no weekly engulfing":              lambda d: base(d) and up4(d) and not bool(g(eng_d, d, False)),
    "FAST ONLY: 4h up & 1h up & breadth>50%":       lambda d: up4(d) and up1(d) and g(breadth, d, 0) > 0.5,
    "FAST ONLY: 4h up & rising & breadth>60%":      lambda d: up4(d) and rising4(d) and g(breadth, d, 0) > 0.6,
}

years = sorted({t["entry"].year for t in longs})
mid = sorted(t["entry"] for t in longs)[len(longs) // 2]
print(f"{len(longs)} long trades {years[0]}–{years[-1]} (lower-TF data from {eod.index[0].date()})\n")
print(f"{'rule':<44}{'trades':>7}{'totR':>7}{'maxDD':>7}{'worstM':>7}{'ret/dd':>7}{'avgR':>8}  "
      + "".join(f"{y:>6}" for y in years) + f"{'r/dd 1H':>9}{'r/dd 2H':>8}")
for name, f in RULES.items():
    rows = [{"R": t["r_mult"], "exit": t["exit"], "y": t["entry"].year, "h": t["entry"] >= mid}
            for t in longs if f(t["entry"])]
    a = curve_stats(rows)
    if not a:
        print(f"{name:<44} no trades"); continue
    by = {y: sum(r["R"] for r in rows if r["y"] == y) for y in years}
    h0 = curve_stats([r for r in rows if not r["h"]]); h1 = curve_stats([r for r in rows if r["h"]])
    print(f"{name:<44}{a['n']:>7}{a['totR']:>7.0f}{a['maxDD']:>7.0f}{a['worstM']:>7.0f}{a['ret/dd']:>7.2f}"
          f"{a['totR'] / a['n']:>+8.3f}  " + "".join(f"{by[y]:>6.0f}" for y in years)
          + f"{h0.get('ret/dd', 0):>9.2f}{h1.get('ret/dd', 0):>8.2f}")
