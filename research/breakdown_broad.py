"""
Research: the live scanner hid most Breakdown Shorts.

classify_setup() returns "Falling Knife — Avoid" for any oversold coin below its
200d BEFORE it checks for a 55-day breakdown, and a fresh 55-day low is nearly
always oversold. So live (and in the validation backtest) Breakdown Short only
covered the rare NOT-oversold breakdowns. This tests the full rule.

Signal: close below the prior 55-day low, close < SMA200, SMA50 < SMA200,
20d avg turnover >= $0.5M, 5-day cooldown per coin. Entry at the close.
Exit: Bybit trail 3.5xATR off the best price, immediate, 60 days max, 0.36% cost.

Run:  ./venv/bin/python research/breakdown_broad.py ~/quantcore_cache/long_history.pkl
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.bybit_trailing import sim  # noqa: E402
from backtesting.crypto_optimize import management_for  # noqa: E402

LABEL = "Breakdown Short (55d low)"


def _rsi(c, n):
    d = c.diff()
    g = d.clip(lower=0).ewm(com=n - 1, min_periods=n).mean()
    ls = (-d).clip(lower=0).ewm(com=n - 1, min_periods=n).mean()
    return 100 - 100 / (1 + g / ls)


def signals(df, btc):
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    lo55 = l.rolling(55).min().shift(1)
    qv = (c * v).rolling(20).mean()
    rsi14, rsi2 = _rsi(c, 14), _rsi(c, 2)
    m20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    bbp = (c - (m20 - 2 * sd20)) / (4 * sd20)
    z = (c - m20) / sd20
    oversold = (rsi2 < 15) | (rsi14 < 30) | (bbp <= 0.05) | (z <= -2.0)
    b = btc.reindex(c.index, method="ffill")
    btc_dn = b < b.rolling(50).mean()
    btc_1w = b / b.shift(7) - 1
    sig = (c < lo55) & (c < s200) & (s50 < s200) & (qv >= 0.5e6)
    out, last = [], -99
    for i in np.flatnonzero(sig.fillna(False).values):
        if i - last < 5 or i < 205:
            continue
        last = i
        out.append((i, {"price": c.iat[i], "atr": atr.iat[i], "_label": LABEL},
                    {"oversold": bool(oversold.iat[i]), "btc_dn": bool(btc_dn.iat[i]),
                     "btc_1w": float(btc_1w.iat[i]) if pd.notna(btc_1w.iat[i]) else 0.0,
                     "ext": float((lo55.iat[i] - c.iat[i]) / atr.iat[i])}))
    return out


def report(name, rows):
    if not rows:
        print(f"{name:<44} n=0"); return
    rs = np.array([r for r, _ in rows]); ts = np.array([t for _, t in rows])
    pf = lambda x: x[x > 0].sum() / -x[x < 0].sum() if (x < 0).any() else 99
    mid = np.sort(ts)[len(ts) // 2]
    t = rs.mean() / (rs.std(ddof=1) / np.sqrt(len(rs))) if len(rs) > 2 else 0
    yrs = pd.Series(rs, index=pd.DatetimeIndex(ts)).groupby(lambda d: d.year).agg(["sum", "count"])
    print(f"{name:<44} n={len(rs):>5} PF {pf(rs):5.2f} win {np.mean(rs > 0)*100:3.0f}% "
          f"avg {rs.mean():+.3f}R tot {rs.sum():+7.0f}R t={t:4.2f} | halves "
          f"{pf(rs[ts < mid]):.2f}/{pf(rs[ts >= mid]):.2f} | "
          + " ".join(f"{y}:{s:+.0f}({n})" for y, (s, n) in yrs.iterrows()))


def main(pkl):
    d = pickle.load(open(pkl, "rb"))
    btc = d["btc"]["close"]; btc.index = btc.index.normalize()
    mg = management_for(LABEL)
    res = []
    for sym, df in d["coins"].items():
        if df is None or len(df) < 230:
            continue
        df = df.copy(); df.index = df.index.normalize()
        for i, ind, tags in signals(df, btc):
            r = sim(df["close"], df["high"], df["low"], i, ind, mg, "high", 3.5, 0)
            if r is not None and np.isfinite(r):
                res.append((r, df.index[i], tags))
    def sub(f): return [(r, t) for r, t, g in res if f(g)]
    report("ALL breakdowns (proposed)", sub(lambda g: True))
    report("not oversold (what live used)", sub(lambda g: not g["oversold"]))
    report("oversold (hidden by Falling Knife)", sub(lambda g: g["oversold"]))
    report("ALL + BTC below its 50d", sub(lambda g: g["btc_dn"]))
    report("ALL + BTC above its 50d", sub(lambda g: not g["btc_dn"]))
    report("ALL + BTC down on the week", sub(lambda g: g["btc_1w"] < 0))
    report("ALL + close <=1 ATR past the low", sub(lambda g: g["ext"] <= 1.0))
    report("ALL + close >1 ATR past the low", sub(lambda g: g["ext"] > 1.0))


if __name__ == "__main__":
    main(sys.argv[1])
