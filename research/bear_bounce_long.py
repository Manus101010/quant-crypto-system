"""
Research (Oct 18 2026): quick oversold-bounce LONGS in a falling market.

The scanner tags dozens of coins "Counter-Trend Bounce" (RSI-2 < 5 or z <= -2.7
below the 200d) but none was ever tested. Entry at the close, 0.36% cost,
2020-2026 daily history (survivors only). Exits: stop k x ATR below, exit on a
close above the 5-day SMA (Connors) or a fixed target, max hold. Bonferroni over
~12 variants: need t >= ~2.9.

Run:  ./venv/bin/python research/bear_bounce_long.py ~/quantcore_cache/long_history.pkl
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skills import new_setups as NS  # noqa: E402

COST = 0.0036


def _rsi(c, n):
    d = c.diff()
    g = d.clip(lower=0).ewm(com=n - 1, min_periods=n).mean()
    ls = (-d).clip(lower=0).ewm(com=n - 1, min_periods=n).mean()
    return 100 - 100 / (1 + g / ls)


def sim_long(c, h, l, sma5, i, stop_k, atr, exit_mode, hold, tgt_r=None):
    e = c.iat[i]; risk = stop_k * atr
    if not np.isfinite(risk) or risk <= 0:
        return None
    st = e - risk
    for k in range(1, hold + 1):
        j = i + k
        if j >= len(c):
            return None
        if l.iat[j] <= st:
            x = st; break
        if tgt_r and h.iat[j] >= e + tgt_r * risk:
            x = e + tgt_r * risk; break
        if exit_mode == "sma5" and c.iat[j] > sma5.iat[j]:
            x = c.iat[j]; break
    else:
        x = c.iat[min(i + hold, len(c) - 1)]
    return (x - e) / risk - COST * e / risk


def main(pkl):
    d = pickle.load(open(pkl, "rb"))
    btc = d["btc"]["close"].copy(); btc.index = btc.index.normalize()
    bt = NS.btc_trend(btc)
    res: dict[str, list] = {}
    for sym, df in d["coins"].items():
        if df is None or len(df) < 230:
            continue
        df = df.copy(); df.index = df.index.normalize()
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        s200, s5 = c.rolling(200).mean(), c.rolling(5).mean()
        m20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
        z = (c - m20) / sd20
        r2 = _rsi(c, 2)
        liq = (c * v).rolling(20).mean() >= 0.5e6
        b = bt.reindex(df.index, method="ffill")
        below = c < s200
        base = {"RSI2<5": r2 < 5, "z<=-2.7": z <= -2.7, "RSI2<5 & z<=-2": (r2 < 5) & (z <= -2)}
        for bn, cond in base.items():
            for regime, rmask in {"any BTC": b != "NA", "BTC DOWN": b == "DOWN"}.items():
                sig = (cond & below & liq & rmask).fillna(False).values
                for ex, (sk, mode, hold, tr_) in {"2ATR stop, exit>SMA5, 7d": (2, "sma5", 7, None),
                                                   "1.5ATR stop, 1.5R target, 5d": (1.5, None, 5, 1.5)}.items():
                    name = f"{bn} | {regime} | {ex}"
                    last = -99
                    for i in np.flatnonzero(sig):
                        if i < 205 or i - last < 3:
                            continue
                        last = i
                        r = sim_long(c, h, l, s5, i, sk, atr.iat[i], mode, hold, tr_)
                        if r is not None and np.isfinite(r):
                            res.setdefault(name, []).append((r, df.index[i]))
    pf = lambda a: a[a > 0].sum() / -a[a < 0].sum() if (a < 0).any() else 99
    for name, rows in res.items():
        rs = np.array([r for r, _ in rows]); ts = np.array([t for _, t in rows])
        mid = np.sort(ts)[len(ts) // 2]
        t = rs.mean() / (rs.std(ddof=1) / np.sqrt(len(rs)))
        yrs = pd.Series(rs, index=pd.DatetimeIndex(ts)).groupby(lambda x: x.year).sum()
        print(f"{name:<52} n={len(rs):>5} PF {pf(rs):.2f} win {np.mean(rs>0)*100:.0f}% avg {rs.mean():+.3f} "
              f"t={t:5.2f} halves {pf(rs[ts<mid]):.2f}/{pf(rs[ts>=mid]):.2f} | "
              + " ".join(f"{y}:{s:+.0f}" for y, s in yrs.items()))


if __name__ == "__main__":
    main(sys.argv[1])
