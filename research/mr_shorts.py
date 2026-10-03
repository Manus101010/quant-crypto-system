"""
Research: a testable mean-reversion SHORT.

The production "MR Short" / "Williams %R Overbought Short" required a coin below
its 200-SMA *and* at its 20-day high with RSI14>=75, z>=2, 1.5x volume, RSI2>=95
— a combination that produced ZERO trades in 600 days (a rally that strong has
almost always crossed the 200-SMA). So they could never be validated.

Here: Connors-style inverse RSI-2 variants, all below the 200-SMA, simulated with
the production short machinery (tight 2xATR stop / 3R / 15 bars, 0.36% cost),
optionally with BTC itself below its 200d. Adoption bar: PF > 1.0, n >= 25,
PF > 1 in BOTH halves.

Run:  ./venv/bin/python research/mr_shorts.py
"""
from __future__ import annotations
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting.crypto_optimize import _simulate, management_for
from backtesting.crypto_validation import _apply_costs

SCR = Path(os.environ.get("RESEARCH_DIR", "/tmp"))
LABEL = "MR Short (overbought in downtrend)"      # → SHORT_SETUPS, tight management


def rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


VARIANTS = {
    "RSI2>=95":             lambda x: x.r2 >= 95,
    "RSI2>=90":             lambda x: x.r2 >= 90,
    "RSI2>=95 & z>=1":      lambda x: (x.r2 >= 95) & (x.z >= 1),
    "RSI2>=90 & 50<200":    lambda x: (x.r2 >= 90) & (x.s50 < x.s200),
    "RSI2>=95 & 50<200":    lambda x: (x.r2 >= 95) & (x.s50 < x.s200),
    "2 days RSI2>=90":      lambda x: (x.r2 >= 90) & (x.r2.shift() >= 90),
}


def main():
    data, _ = pickle.load(open(SCR / "scaled_data.pkl", "rb"))
    btc = pickle.load(open(SCR / "btc_long.pkl", "rb"))["close"]
    btc.index = btc.index.normalize()
    btc_down = btc < btc.rolling(200).mean()
    cfg = management_for(LABEL)
    res = {k: [] for k in VARIANTS}
    for sym, df in data.items():
        if len(df) < 230:
            continue
        c, h, l = df["close"], df["high"], df["low"]
        x = pd.DataFrame({"c": c, "r2": rsi(c, 2), "s50": c.rolling(50).mean(),
                          "s200": c.rolling(200).mean(), "atr": atr(h, l, c),
                          "z": (c - c.rolling(20).mean()) / c.rolling(20).std()})
        below = x.c < x.s200
        for name, cond in VARIANTS.items():
            sig = (below & cond(x)).fillna(False)
            last = -99
            for i in np.flatnonzero(sig.values):
                if i < 210 or i - last < 3:          # no stacking on consecutive bars
                    continue
                last = i
                ind = {"price": float(c.iloc[i]), "atr": float(x.atr.iloc[i]), "_label": LABEL}
                t = _simulate(c, h, l, i, ind, cfg)
                if t:
                    d = df.index[i].normalize()
                    t["entry"] = d
                    t["btc_down"] = bool(btc_down.get(d, False))
                    res[name].append(t)
    allts = sorted(t["entry"] for v in res.values() for t in v)
    mid = allts[len(allts) // 2]
    print(f"half split {mid.date()}\n")
    print(f"{'variant':<22}{'filter':<11}{'n':>6}{'PF':>7}{'win%':>7}{'expR':>8}{'PF 1st½':>9}{'PF 2nd½':>9}  verdict")
    for name, tr in res.items():
        tr = _apply_costs(tr, 0.36)
        for flt, pool in (("any BTC", tr), ("BTC<200d", [t for t in tr if t["btc_down"]])):
            def pf(p):
                gw = sum(t["ret_pct"] for t in p if t["ret_pct"] > 0)
                gl = abs(sum(t["ret_pct"] for t in p if t["ret_pct"] <= 0))
                return gw / gl if gl else (99.0 if gw else 0.0)
            if not pool:
                print(f"{name:<22}{flt:<11}{0:>6}"); continue
            h0 = [t for t in pool if t["entry"] < mid]; h1 = [t for t in pool if t["entry"] >= mid]
            a, b, c2 = pf(pool), pf(h0), pf(h1)
            ok = a > 1 and len(pool) >= 25 and b > 1 and c2 > 1
            print(f"{name:<22}{flt:<11}{len(pool):>6}{a:>7.2f}{sum(t['ret_pct']>0 for t in pool)/len(pool)*100:>6.0f}%"
                  f"{np.mean([t['r_mult'] for t in pool]):>+8.3f}{b:>9.2f}{c2:>9.2f}  {'PASS' if ok else 'fail'}")


if __name__ == "__main__":
    main()
