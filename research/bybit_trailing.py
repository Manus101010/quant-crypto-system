"""
Research: how should the trailing setups be set up on Bybit?

Bybit's native trailing stop follows the BEST price reached (intraday high for a
long), optionally only after an ACTIVATION price. Our backtest trailed off daily
CLOSES. This re-simulates every trailing setup (daily bars, full 2020-2026
history, 0.36% cost) Bybit-style:
  close-trail (current backtest)  vs  Bybit high-trail at k x ATR(entry)
  activation: immediate, or only after +1R in profit (initial stop until then)
Relative Strength Leader keeps its "half off at +2R, rest to breakeven".
Conservative fills: stop checked before new highs on the same bar.

Run:  ./venv/bin/python research/bybit_trailing.py long_history.pkl
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting.crypto_optimize import _signals, management_for, SHORT_SETUPS  # noqa: E402
from backtesting.setup_validation import _MIN_HISTORY  # noqa: E402

COST = 0.0036


def sim(c, h, l, i, ind, mgmt, mode, k_atr, act_r):
    atr, entry = ind.get("atr"), ind["price"]
    if not atr or atr <= 0:
        return None
    short = ind["_label"] in SHORT_SETUPS
    sg = -1 if short else 1
    risk = mgmt["stop_mult"] * atr
    stop0 = entry - sg * risk
    dist = (mgmt["stop_mult"] if mode == "close" else k_atr) * atr
    part = mgmt.get("partial") or {}
    took, booked = 0.0, 0.0
    stop, best, active = stop0, entry, act_r == 0
    n = len(c)
    exit_p, k = None, 0
    for k in range(1, mgmt["max_hold"] + 1):
        j = i + k
        if j >= n:
            k -= 1
            break
        hi, lo, cl = h.iat[j], l.iat[j], c.iat[j]
        if (not short and lo <= stop) or (short and hi >= stop):
            exit_p = stop
            break
        if part.get("at_r") and not took:
            lvl = entry + sg * part["at_r"] * risk
            if (not short and hi >= lvl) or (short and lo <= lvl):
                took, booked = part["frac"], part["frac"] * part["at_r"] * risk
                stop = max(stop, entry) if not short else min(stop, entry)
        fav = hi if not short else lo
        if not active and sg * (fav - entry) >= act_r * risk:
            active = True
        if active:
            if mode == "close":
                new = cl - sg * dist
            else:                                    # Bybit: trail off best price
                best = max(best, hi) if not short else min(best, lo)
                new = best - sg * dist
            stop = max(stop, new) if not short else min(stop, new)
    if exit_p is None:
        exit_p = c.iat[min(i + max(k, 1), n - 1)]
    move = booked + (1 - took) * sg * (exit_p - entry)
    return move / risk - COST * entry / risk


def main(pkl):
    d = pickle.load(open(pkl, "rb"))
    btc = d["btc"]["close"]
    btc.index = btc.index.normalize()
    cache = Path(pkl).with_name("trail_signals.pkl")
    if cache.exists():
        sigs = pickle.load(open(cache, "rb"))
    else:
        sigs = []
        for sym, df in d["coins"].items():
            if df is None or len(df) < _MIN_HISTORY + 20:
                continue
            df = df.copy(); df.index = df.index.normalize()
            v = df["volume"] if "volume" in df.columns else None
            for i, ind in _signals(df["close"], df["high"], df["low"], v, btc):
                if management_for(ind["_label"]).get("trailing"):
                    sigs.append((sym, i, ind))
        pickle.dump(sigs, open(cache, "wb"))
    labels = sorted({s[2]["_label"] for s in sigs})
    variants = [("close-trail (backtest today)", "close", None, 0)] + \
               [(f"Bybit trail {k}xATR, {'activate +1R' if a else 'immediate'}", "high", k, a)
                for k in (2.5, 3.5, 4.5, 6.0) for a in (0, 1)]
    for lab in labels:
        mg = management_for(lab)
        ss = [s for s in sigs if s[2]["_label"] == lab]
        print(f"\n=== {lab}  (n={len(ss)}, initial stop {mg['stop_mult']}xATR, max {mg['max_hold']}d)")
        print(f"{'variant':<34}{'PF':>6}{'win%':>6}{'avgR':>8}{'totR':>8}   {'PF 1st½':>8}{'PF 2nd½':>8}")
        mid = sorted(d["coins"][s[0]].index[s[1]] for s in ss)[len(ss) // 2]
        for name, mode, kk, act in variants:
            rs, half = [], []
            for sym, i, ind in ss:
                df = d["coins"][sym]
                r = sim(df["close"], df["high"], df["low"], i, ind, mg, mode, kk, act)
                if r is not None:
                    rs.append(r); half.append(df.index[i] >= mid)
            rs, half = np.array(rs), np.array(half)
            pf = lambda x: x[x > 0].sum() / -x[x < 0].sum() if (x < 0).any() else 99
            print(f"{name:<34}{pf(rs):>6.2f}{(rs > 0).mean() * 100:>5.0f}%{rs.mean():>+8.3f}{rs.sum():>8.0f}   "
                  f"{pf(rs[~half]):>8.2f}{pf(rs[half]):>8.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
