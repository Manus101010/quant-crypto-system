"""Entry detectors for versions A, B, C (see core.py docstring). All features use closed bars."""
from __future__ import annotations

import numpy as np
import pandas as pd

import core as C

RUN_DEFS = {          # name: (kind, threshold, days)
    "p20_3d": ("pct", 0.20, 3), "p30_3d": ("pct", 0.30, 3), "p30_7d": ("pct", 0.30, 7),
    "p50_7d": ("pct", 0.50, 7), "atr5": ("atr", 5.0, 0), "atr8": ("atr", 8.0, 0),
}
DUMP_DEFS = {
    "p20_3d": ("pct", 0.20, 3), "p30_3d": ("pct", 0.30, 3), "p30_7d": ("pct", 0.30, 7),
    "p45_7d": ("pct", 0.45, 7), "atr5": ("atr", 5.0, 0), "atr8": ("atr", 8.0, 0),
}
TRIGS = ("SW", "EMA", "LH")
TFS = ("1h", "4h")
C_DEFS = {   # name: (side, ret7d threshold, pullback reference)
    "L_y10_e1": (1, 0.10, "e20_1"), "L_y25_e1": (1, 0.25, "e20_1"),
    "L_y10_e4": (1, 0.10, "e20_4"), "L_y25_e4": (1, 0.25, "e20_4"),
    "S_y10_e1": (-1, 0.10, "e20_1"), "S_y20_e1": (-1, 0.20, "e20_1"),
    "S_y10_e4": (-1, 0.10, "e20_4"), "S_y20_e4": (-1, 0.20, "e20_4"),
}
P = 72   # the peak / trough must sit inside the last 72h ("rolling over" now)


def entry_names() -> list[str]:
    out = []
    for v, defs in (("A", RUN_DEFS), ("B", DUMP_DEFS)):
        for d in defs:
            for t in TRIGS:
                for tf in TFS:
                    out.append(f"{v}|{d}|{t}|{tf}")
    out += [f"C|{d}" for d in C_DEFS]
    return out


def _tf_triggers(o, h, l, c, side, pbars):
    """Trigger booleans on one timeframe's bars. side -1 breakdown, +1 reclaim."""
    cs = pd.Series(c)
    e20 = C.ema(cs, 20).to_numpy()
    if side == -1:
        m5 = pd.Series(l).shift(1).rolling(5, min_periods=5).min().to_numpy()
        sw = (c < m5) & (np.roll(c, 1) >= np.roll(m5, 1))
        em = (c < e20) & (np.roll(c, 1) >= np.roll(e20, 1))
        loc = pd.Series(h).rolling(3, min_periods=1).max().to_numpy()
    else:
        m5 = pd.Series(h).shift(1).rolling(5, min_periods=5).max().to_numpy()
        sw = (c > m5) & (np.roll(c, 1) <= np.roll(m5, 1))
        em = (c > e20) & (np.roll(c, 1) <= np.roll(e20, 1))
        loc = pd.Series(l).rolling(3, min_periods=1).min().to_numpy()
    sw[:30] = False
    em[:30] = False
    lh = C.lower_high_break(h, l, c, pbars, side)
    lh[:30] = False
    return {"SW": sw, "EMA": em, "LH": lh}, loc


def signals(k: pd.DataFrame) -> tuple[dict, dict]:
    """Returns {entry_name: (idx, side, stop)} on the 1h index of k, plus feature dict."""
    idx = k.index
    o, h, l, c = (k[x].to_numpy() for x in ("open", "high", "low", "close"))
    a1 = C.atr(k["high"], k["low"], k["close"]).to_numpy()
    h4 = C.h4_frame(k)
    a4 = C.atr(h4["high"], h4["low"], h4["close"])
    e50_4 = C.ema(h4["close"], 50)
    e20_4 = C.ema(h4["close"], 20)
    a4_1 = C.to_h1(a4, pd.Timedelta(hours=4), idx)
    e50_4_1 = C.to_h1(e50_4, pd.Timedelta(hours=4), idx)
    e20_4_1 = C.to_h1(e20_4, pd.Timedelta(hours=4), idx)
    uni = ((k["dvol30"] >= C.MIN_DVOL) & (k["age_h"] >= 24 * 30)).to_numpy() & np.isfinite(a1) & np.isfinite(a4_1)

    # run up / dump magnitudes (peak or trough inside the last 72h)
    feats = {}
    hs, ls = pd.Series(h), pd.Series(l)
    for days in (3, 7):
        bmin = ls.rolling(24 * days, min_periods=24 * days - 6).min().to_numpy()
        bmax = hs.rolling(24 * days, min_periods=24 * days - 6).max().to_numpy()
        feats[f"up{days}"], _ = C.extreme_move(h, l, P, bmin, -1)
        feats[f"dn{days}"], _ = C.extreme_move(h, l, P, bmax, 1)
    ext_up = pd.Series((h - e50_4_1) / a4_1).rolling(P, min_periods=1).max().to_numpy()
    ext_dn = pd.Series((e50_4_1 - l) / a4_1).rolling(P, min_periods=1).max().to_numpy()

    def cond(defs_name, defs, side):
        kind, th, days = defs[defs_name]
        if kind == "pct":
            v = feats[f"up{days}"] if side == -1 else feats[f"dn{days}"]
        else:
            v = ext_up if side == -1 else ext_dn
        return np.nan_to_num(v, nan=-1) >= th

    # triggers on 1h and 4h bars, mapped to 1h positions
    trig = {}
    for side in (-1, 1):
        t1, loc1 = _tf_triggers(o, h, l, c, side, P)
        trig[(side, "1h")] = (t1, loc1)
        tb, locb = _tf_triggers(*(h4[x].to_numpy() for x in ("open", "high", "low", "close")), side, P // 4)
        pos = C.h4_pos_in_h1(h4.index, idx)
        ok = pos >= 0
        t4 = {}
        for name, arr in tb.items():
            z = np.zeros(len(idx), bool)
            z[pos[ok]] = arr[ok]
            t4[name] = z
        loc4 = np.full(len(idx), np.nan)
        loc4[pos[ok]] = locb[ok]
        trig[(side, "4h")] = (t4, loc4)

    out = {}
    for v, defs, side in (("A", RUN_DEFS, -1), ("B", DUMP_DEFS, 1)):
        for dn in defs:
            cm = cond(dn, defs, side) & uni
            for tf in TFS:
                tt, loc = trig[(side, tf)]
                stop = loc - side * 0.1 * a1           # short: local high + 0.1 ATR
                for t in TRIGS:
                    m = cm & tt[t] & np.isfinite(stop)
                    ii = np.flatnonzero(m)
                    out[f"{v}|{dn}|{t}|{tf}"] = (ii, side, stop[ii])
    # C trend pullback
    up4 = ((h4["close"] > e20_4) & (e20_4 > e50_4) & (e50_4 > e50_4.shift(6))).astype(float)
    dn4 = ((h4["close"] < e20_4) & (e20_4 < e50_4) & (e50_4 < e50_4.shift(6))).astype(float)
    up4_1 = C.to_h1(up4, pd.Timedelta(hours=4), idx) == 1
    dn4_1 = C.to_h1(dn4, pd.Timedelta(hours=4), idx) == 1
    cs = pd.Series(c)
    e20_1 = C.ema(cs, 20).to_numpy()
    r7 = (cs / cs.shift(168) - 1).to_numpy()
    lo3 = ls.rolling(3, min_periods=3).min().to_numpy()
    hi3 = hs.rolling(3, min_periods=3).max().to_numpy()
    lo6 = ls.rolling(6, min_periods=6).min().to_numpy()
    hi6 = hs.rolling(6, min_periods=6).max().to_numpy()
    ph = np.roll(h, 1)
    pl = np.roll(l, 1)
    for name, (side, y, ref) in C_DEFS.items():
        rv = e20_1 if ref == "e20_1" else e20_4_1
        if side == 1:
            m = uni & up4_1 & (np.nan_to_num(r7) >= y) & (lo3 <= rv) & (c > ph) & (c > e20_1)
            stop = lo6 - 0.1 * a1
        else:
            m = uni & dn4_1 & (np.nan_to_num(r7, nan=0) <= -y) & (hi3 >= rv) & (c < pl) & (c < e20_1)
            stop = hi6 + 0.1 * a1
        m[:200] = False
        ii = np.flatnonzero(m & np.isfinite(stop))
        out[f"C|{name}"] = (ii, side, stop[ii])
    return out, {"a1": a1}
