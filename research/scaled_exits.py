"""
Research: does taking PARTIAL profit early improve the validated setups?

Variants (per setup, same signals, same data, same 0.36% round-trip cost as the
production validation):
  base          — the production management (trail or fixed target)
  PxxRyy[BE]    — close xx% of the position when price reaches +yy R, then
                  (BE) move the stop on the remainder to breakeven; the
                  remainder continues under the production management.

Robustness: every variant is also scored separately on the first and second
half of the history — a change is only worth adopting if it helps in BOTH.

Run:  ./venv/bin/python research/scaled_exits.py
Not wired into anything live.
"""
from __future__ import annotations
import os
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.crypto_optimize import (_signals, _btc_close, _universe, management_for,
                                         SHORT_SETUPS)
from backtesting.setup_validation import _MIN_HISTORY
from utils.exchange import get_ohlcv_batch

SETUPS = ["Relative Strength Leader", "Momentum Runner", "Donchian Breakout (55d)",
          "Breakdown Short (55d low)"]
VARIANTS = [("base", None, None, False),
            ("P33R1", 0.33, 1.0, False), ("P50R1", 0.50, 1.0, False),
            ("P50R1BE", 0.50, 1.0, True), ("P33R1.5BE", 0.33, 1.5, True),
            ("P50R2BE", 0.50, 2.0, True)]
COST_PCT = 0.36
CACHE = Path(os.environ.get("SCALED_CACHE", "/tmp/scaled_exits_data.pkl"))


def simulate(close, high, low, i, ind, cfg, frac, at_r, be) -> dict | None:
    """Production _simulate logic + an optional partial exit at +at_r R."""
    atr, entry = ind.get("atr"), ind["price"]
    if not atr or atr <= 0:
        return None
    short = ind.get("_label") in SHORT_SETUPS
    sgn = -1 if short else 1
    n = len(close)
    stop = entry - sgn * cfg["stop_mult"] * atr
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    target = entry + sgn * cfg["target_r"] * risk
    trail = stop
    partial_px = entry + sgn * at_r * risk if frac else None
    took = 0.0            # fraction already closed
    realized = 0.0        # sum of (fraction × signed return) booked so far
    exit_p, k = None, 0
    for k in range(1, cfg["max_hold"] + 1):
        j = i + k
        if j >= n:
            k -= 1
            break
        hi, lo, cl = float(high.iloc[j]), float(low.iloc[j]), float(close.iloc[j])
        cur = trail if cfg["trailing"] else stop
        if (lo <= cur) if not short else (hi >= cur):          # stop first (conservative)
            exit_p = cur
            break
        if frac and not took and ((hi >= partial_px) if not short else (lo <= partial_px)):
            took = frac
            realized += frac * sgn * (partial_px - entry)
            if be:
                stop = entry if not cfg["trailing"] else stop
                trail = max(trail, entry) if not short else min(trail, entry)
        if (hi >= target) if not short else (lo <= target):
            exit_p = target
            break
        if cfg["trailing"]:
            new = cl - sgn * cfg["stop_mult"] * atr
            trail = max(trail, new) if not short else min(trail, new)
        if be and took and not cfg["trailing"]:
            stop = entry
    if exit_p is None:
        exit_p = float(close.iloc[min(i + max(k, 1), n - 1)])
    realized += (1 - took) * sgn * (exit_p - entry)
    ret_pct = realized / entry * 100 - COST_PCT
    return {"ret_pct": ret_pct, "r": realized / risk - COST_PCT / 100 * entry / risk,
            "i": i, "n": n}


def stats(tr):
    if not tr:
        return None
    gw = sum(t["ret_pct"] for t in tr if t["ret_pct"] > 0)
    gl = abs(sum(t["ret_pct"] for t in tr if t["ret_pct"] <= 0))
    return {"n": len(tr), "pf": gw / gl if gl else 99.0,
            "win": sum(t["ret_pct"] > 0 for t in tr) / len(tr),
            "exp_r": sum(t["r"] for t in tr) / len(tr)}


def main():
    if CACHE.exists():
        data, btc = pickle.loads(CACHE.read_bytes())
    else:
        tickers, exch = _universe("mexc", 400, 500)
        data = get_ohlcv_batch(tickers, timeframe="1d", limit=600, exchange=exch)
        btc = _btc_close(600, exch)
        CACHE.write_bytes(pickle.dumps((data, btc)))
    print(f"coins with data: {len(data)}")
    res = {s: {v[0]: [] for v in VARIANTS} for s in SETUPS}
    for sym, df in data.items():
        if len(df) < _MIN_HISTORY + 20:
            continue
        c, h, l = df["close"], df["high"], df["low"]
        vol = df["volume"] if "volume" in df.columns else None
        for i, ind in _signals(c, h, l, vol, btc):
            lab = ind["_label"]
            if lab not in res:
                continue
            cfg = management_for(lab)
            for name, frac, at_r, be in VARIANTS:
                t = simulate(c, h, l, i, ind, cfg, frac, at_r, be)
                if t:
                    t["ts"] = df.index[i]
                    res[lab][name].append(t)
    all_ts = sorted(t["ts"] for lab in SETUPS for t in res[lab]["base"])
    mid = all_ts[len(all_ts) // 2] if all_ts else None
    print(f"period split at {mid}")
    for lab in SETUPS:
        for name in res[lab]:
            for t in res[lab][name]:
                t["half"] = 0 if t["ts"] < mid else 1
        print(f"\n=== {lab}  ({management_for(lab)['name']})")
        print(f"{'variant':<11}{'n':>6}{'PF':>7}{'win%':>7}{'expR':>8}   {'PF 1st½':>8}{'PF 2nd½':>8}")
        for name, *_ in VARIANTS:
            tr = res[lab][name]
            a = stats(tr)
            if not a:
                continue
            h0 = stats([t for t in tr if t["half"] == 0])
            h1 = stats([t for t in tr if t["half"] == 1])
            print(f"{name:<11}{a['n']:>6}{a['pf']:>7.3f}{a['win']*100:>6.1f}%{a['exp_r']:>+8.3f}   "
                  f"{(h0 or {}).get('pf', 0):>8.3f}{(h1 or {}).get('pf', 0):>8.3f}")


if __name__ == "__main__":
    main()
