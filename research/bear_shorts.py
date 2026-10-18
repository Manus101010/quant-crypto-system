"""
Research (Oct 18 2026): short setups that can fire in a falling market.

Live scans armed nothing for 6 days: longs were (correctly) gated off, and the
only validated shorts are rare. Candidates tested on the 2020-2026 daily history
(~500 Bybit/MEXC coins, survivors only, 0.36% round-trip cost, entry at close):

  DIST       Distribution Short as live (skills/new_setups.py)
  DIST_any   ... also when BTC is DOWN
  FADE       Downtrend Bounce Fade as live (BTC MIXED, >= $2M/day)
  FADE_any   ... any BTC state, >= $0.5M/day
  FADE_dn    ... BTC DOWN only
  EMA_REJ    rally to the falling 20 EMA in a downtrend, closes back below it
  RWS        Relative Weakness Short (scanner rule)
  LH_FAIL    lower-high failure: 10d high below the 55d high, red day below 10d low

Exits: trailing ones use Bybit trail off best price; fixed ones use stop/target.
Reports PF, t-stat, halves, per-year. Bonferroni: 8 families x ~3 exits => need
t >= ~3.0 to call it real.

Run:  ./venv/bin/python research/bear_shorts.py ~/quantcore_cache/long_history.pkl
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skills import new_setups as NS  # noqa: E402

COST = 0.0036


def sim_short(c, h, l, i, stop, target, trail_atr, atr, max_hold):
    """Short from close[i]. Stop checked first each bar (conservative)."""
    entry = c.iat[i]
    risk = stop - entry
    if not np.isfinite(risk) or risk <= 0:
        return None
    best, st = entry, stop
    n = len(c)
    exit_p = None
    for k in range(1, max_hold + 1):
        j = i + k
        if j >= n:
            return None                       # still open at end of data: skip
        if h.iat[j] >= st:
            exit_p = st; break
        if target is not None and l.iat[j] <= target:
            exit_p = target; break
        if trail_atr:
            best = min(best, l.iat[j])
            st = min(st, best + trail_atr * atr)
    if exit_p is None:
        exit_p = c.iat[min(i + max_hold, n - 1)]
    return (entry - exit_p) / risk - COST * entry / risk


def ind(df, btc):
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    x = NS._ind(df)
    x["btc"] = NS.btc_trend(btc).reindex(df.index, method="ffill").fillna("NA")
    x["btc_r30"] = (btc / btc.shift(30) - 1).reindex(df.index, method="ffill")
    x["r30"] = c / c.shift(30) - 1
    x["hi10"], x["lo10p"] = h.rolling(10).max(), l.rolling(10).min().shift(1)
    x["hi55"] = h.rolling(55).max()
    d = c.diff()
    g = d.clip(lower=0).ewm(com=13, min_periods=14).mean()
    ls = (-d).clip(lower=0).ewm(com=13, min_periods=14).mean()
    x["rsi"] = 100 - 100 / (1 + g / ls)
    return x


def families(df, x):
    c, h, l = x["c"], x["h"], x["l"]
    down = (c < x["sma200"]) & (x["sma50"] < x["sma200"])
    liq = x["qvol20"] >= 0.5e6
    post_up = (x["ret120"] >= 0.50) | (x["sma50"] > x["sma200"])
    coiled = (x["bbw_pct"] <= 0.10) & post_up
    first = coiled & ~coiled.shift(fill_value=False)
    lower_half = c < (x["hh20p"] + x["ll20p"]) / 2
    dist_core = first & lower_half & (x["btc"] != "NA") & liq
    rip = x["z5"].rolling(7).max() >= 2.0
    peak = ((h - x["ema20"]) / x["atr"]).rolling(7).max() >= 2.5
    calm = x["tr3"] <= x["atr"]
    room = (c - x["ema20"]) >= 0.25 * x["atr"]
    fade_core = rip & peak & calm & room & (c < x["sma200"])
    hi7 = h.rolling(7).max()
    ema_rej = (down & liq & (h >= x["ema20"]) & (c < x["ema20"]) & (c < c.shift())
               & (x["ema20"] < x["ema20"].shift(5)) & (x["rsi"] < 55))
    rws = ((c < x["sma200"]) & liq & ((x["r30"] - x["btc_r30"]) * 100 <= -15) & (x["rsi"] >= 30))
    lh = (down & liq & (x["hi10"] < x["hi55"] * 0.9) & (c < x["lo10p"]) & (c < c.shift()))
    trail = lambda: dict(stop=c + 3.5 * x["atr"], target=None, trail=3.5, hold=60)
    fade = lambda: dict(stop=hi7 + 0.25 * x["atr"], target=x["ema20"], trail=None, hold=10)
    return {
        "DIST (live)":        (dist_core & (x["btc"] != "DOWN"), trail()),
        "DIST_any (+BTC DOWN)": (dist_core, trail()),
        "DIST_btcDOWN only":  (dist_core & (x["btc"] == "DOWN"), trail()),
        "FADE (live)":        (fade_core & (x["btc"] == "MIXED") & (x["qvol20"] >= 2e6), fade()),
        "FADE_any":           (fade_core & liq, fade()),
        "FADE_dn (BTC DOWN)": (fade_core & liq & (x["btc"] == "DOWN"), fade()),
        "FADE_any $2M":       (fade_core & (x["qvol20"] >= 2e6), fade()),
        "EMA_REJ trail":      (ema_rej, trail()),
        "EMA_REJ 2ATR/3R":    (ema_rej, dict(stop=c + 2 * x["atr"], target=c - 6 * x["atr"], trail=None, hold=15)),
        "EMA_REJ hi/1.5R":    (ema_rej, dict(stop=h + 0.25 * x["atr"], target=None, trail=None, hold=10, rr=1.5)),
        "RWS trail":          (rws, trail()),
        "RWS 2ATR/3R":        (rws, dict(stop=c + 2 * x["atr"], target=c - 6 * x["atr"], trail=None, hold=15)),
        "LH_FAIL trail":      (lh, trail()),
        "LH_FAIL 2ATR/3R":    (lh, dict(stop=c + 2 * x["atr"], target=c - 6 * x["atr"], trail=None, hold=15)),
    }


def stats(rows):
    rs = np.array([r for r, _ in rows]); ts = np.array([t for _, t in rows])
    if len(rs) < 3:
        return None
    pf = lambda a: a[a > 0].sum() / -a[a < 0].sum() if (a < 0).any() else 99
    mid = np.sort(ts)[len(ts) // 2]
    t = rs.mean() / (rs.std(ddof=1) / np.sqrt(len(rs)))
    yrs = pd.Series(rs, index=pd.DatetimeIndex(ts)).groupby(lambda d: d.year).sum()
    return dict(n=len(rs), pf=pf(rs), win=np.mean(rs > 0), avg=rs.mean(), tot=rs.sum(), t=t,
                h1=pf(rs[ts < mid]), h2=pf(rs[ts >= mid]), yrs=yrs, last90=rs[ts >= ts.max() - np.timedelta64(90, "D")])


def main(pkl):
    d = pickle.load(open(pkl, "rb"))
    btc = d["btc"]["close"].copy(); btc.index = btc.index.normalize()
    out: dict[str, list] = {}
    for sym, df in d["coins"].items():
        if df is None or len(df) < 230:
            continue
        df = df.copy(); df.index = df.index.normalize()
        x = ind(df, btc)
        c, h, l = df["close"], df["high"], df["low"]
        for name, (sig, p) in families(df, x).items():
            last = -99
            for i in np.flatnonzero(sig.fillna(False).values):
                if i < 205 or i - last < 5:
                    continue
                last = i
                stop = float(p["stop"].iat[i]); atr = float(x["atr"].iat[i])
                tgt = p["target"].iat[i] if p["target"] is not None else None
                if p.get("rr"):
                    tgt = c.iat[i] - p["rr"] * (stop - c.iat[i])
                if tgt is not None and (not np.isfinite(tgt) or tgt >= c.iat[i]):
                    continue
                r = sim_short(c, h, l, i, stop, tgt, p["trail"], atr, p["hold"])
                if r is not None and np.isfinite(r) and abs(r) < 50:
                    out.setdefault(name, []).append((r, df.index[i]))
    print(f"{'family':<24}{'n':>6}{'PF':>6}{'win':>5}{'avgR':>8}{'totR':>7}{'t':>6}  halves     last90d(n,R)  per-year R")
    for name, rows in out.items():
        s = stats(rows)
        if not s:
            continue
        l9 = s["last90"]
        print(f"{name:<24}{s['n']:>6}{s['pf']:>6.2f}{s['win']*100:>4.0f}%{s['avg']:>+8.3f}{s['tot']:>+7.0f}{s['t']:>6.2f}"
              f"  {s['h1']:.2f}/{s['h2']:.2f}  ({len(l9)},{l9.sum():+.0f})  "
              + " ".join(f"{y}:{v:+.0f}" for y, v in s["yrs"].items()))


if __name__ == "__main__":
    main(sys.argv[1])
