"""
Six new candidate edges for a bear / chop regime, crypto perps, 1h and 4h.

  C1 FUNDNEG_LONG   crowded shorts: funding settles at or below -0.05% / -0.10% per 8h,
                    long on the first 1h close above the prior bar's high within 12h.
  C2 PREM_SHORT     crowded longs inside a downtrend: perp premium over index (8h mean)
                    >= +0.05% / +0.10%, coin below its daily SMA50, short on the first
                    1h close below the prior bar's low within 12h.
  C3 LIQ_LONG       liquidation cascade reversal: a 1h bar falling >= k sigma (k 4 / 6,
                    sigma = 7d stdev of 1h returns) on >= 5x volume with taker sells
                    dominating (taker buy share <= 45%). Long at the cascade close, or
                    on the first green 1h close within 6h. Optional OI flush (OI -2% in
                    the bar) on the OI subset.
  C4 COVER_SHORT    short covering rally in a downtrend: price +6% / +10% over 24h while
                    open interest (coin units) FELL 3% / 6% (rally without new longs),
                    coin below daily SMA50 and 4h EMA20 < EMA50; short on the first 1h
                    close below the prior bar's low within 12h. OI subset only.
  C5 SOUP_4H        failed breakdown / breakout on 4h (Raschke "turtle soup"): the 4h
                    bar trades through the prior 20 / 55 bar low and closes back above
                    it (long), or the mirror at the high (short).
  C7 NEWLIST_SHORT  (round 2) short a newly listed perp: first 4h close below the low of
                    its first 24h / 72h of trading (or simply at the 3 day mark), stop above
                    the 72h high, multi day exits (2R or 14 days, trail, 7 day hold).
  C6 ABSORB         taker flow absorption: over 4h, taker selling dominates (buy share
                    <= 46% / 45%, about the 5th / 2.5th IS percentile; mirror 53% / 54%) on >= 2x volume but price did not fall: long. Mirror:
                    taker buying dominates and price did not rise: short.

Stops are structural (24h swing or the signal bar extreme, plus 0.25 ATR); exits
are the three shared exits in harness.EXITS. Parameters are chosen on data before
2025-07-01 only; research/edge_hunt/run.py then tests the chosen variant untouched
on 2025-07-01 .. 2026-10.

Run: python research/edge_hunt/run.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from harness import EXITS, atr, ema, resample, to_h1

H = pd.Timedelta(hours=1)


def features(df: pd.DataFrame, oi: pd.DataFrame | None) -> pd.DataFrame:
    f = df
    c = f["close"]
    f["atr1h"] = atr(f, 14)
    r1 = c / c.shift() - 1
    f["ret1h"] = r1
    f["sig7d"] = r1.rolling(168, min_periods=120).std().shift(1)
    f["vavg7d"] = f["qv"].rolling(168, min_periods=120).mean().shift(1)
    f["tbs"] = f["tbq"] / f["qv"]
    f["hh24"] = f["high"].rolling(24, min_periods=20).max()
    f["ll24"] = f["low"].rolling(24, min_periods=20).min()
    f["prem8"] = f["prem"].rolling(8, min_periods=6).mean()
    qv4 = f["qv"].rolling(4).sum()
    f["tbs4"] = f["tbq"].rolling(4).sum() / qv4
    f["qv4x"] = qv4 / (f["vavg7d"] * 4)
    f["chg4"] = c / c.shift(4) - 1
    f["chg24"] = c / c.shift(24) - 1
    f["low4"] = f["low"].rolling(4).min()
    f["high4"] = f["high"].rolling(4).max()
    d1 = resample(f[["open", "high", "low", "close", "volume", "qv", "tbq"]], "1D")
    f["sma50d"] = to_h1(d1["close"].rolling(50, min_periods=50).mean(), pd.Timedelta(days=1), f.index)
    h4 = resample(f[["open", "high", "low", "close", "volume", "qv", "tbq"]], "4h")
    f["ema20_4"] = to_h1(ema(h4["close"], 20), pd.Timedelta(hours=4), f.index)
    f["ema50_4"] = to_h1(ema(h4["close"], 50), pd.Timedelta(hours=4), f.index)
    if oi is not None:
        o = oi["oi"]
        f["oi_chg1"] = o / o.shift(1) - 1
        f["oi_chg24"] = o / o.shift(24) - 1
    else:
        f["oi_chg1"] = np.nan
        f["oi_chg24"] = np.nan
    return f


def _first_confirm(trig: np.ndarray, conf: np.ndarray, window: int) -> np.ndarray:
    """For each trigger bar, the first bar in [t, t+window] where conf is true."""
    out = []
    n = len(conf)
    last = -1
    for t in np.flatnonzero(trig):
        if t <= last:
            continue
        for j in range(t, min(n, t + window + 1)):
            if conf[j]:
                out.append(j)
                last = j + window   # one entry per trigger cluster
                break
    return np.unique(np.array(out, dtype=int))


# Each variant: function(f, uni) -> (idx, side, stop) ; uni = universe mask
def c1(theta, confirm):
    def fn(f, uni):
        fu = f["fund8"].to_numpy()
        trig = np.isfinite(fu) & (fu <= theta) & uni
        if confirm:
            conf = (f["close"] > f["high"].shift()).to_numpy()
            idx = _first_confirm(trig, conf, 12)
        else:
            idx = np.flatnonzero(trig)
        stop = (f["ll24"] - 0.25 * f["atr1h"]).to_numpy()[idx]
        return idx, 1, stop
    return fn


def c2(theta):
    def fn(f, uni):
        trig = ((f["prem8"] >= theta) & (f["close"] < f["sma50d"])).to_numpy() & uni
        conf = (f["close"] < f["low"].shift()).to_numpy()
        idx = _first_confirm(trig, conf, 12)
        stop = (f["hh24"] + 0.25 * f["atr1h"]).to_numpy()[idx]
        return idx, -1, stop
    return fn


def c3(k, wait_green, need_oi=False):
    def fn(f, uni):
        trig = ((f["ret1h"] <= -k * f["sig7d"]) & (f["qv"] >= 5 * f["vavg7d"]) & (f["tbs"] <= 0.45)).to_numpy() & uni
        if need_oi:
            trig &= (f["oi_chg1"] <= -0.02).to_numpy()
        if wait_green:
            conf = (f["close"] > f["open"]).to_numpy()
            idx = _first_confirm(np.r_[False, trig[:-1]], conf, 6)   # strictly after the cascade bar
        else:
            idx = np.flatnonzero(trig)
        lo = f["low"].rolling(8, min_periods=1).min()
        stop = (lo - 0.25 * f["atr1h"]).to_numpy()[idx]
        return idx, 1, stop
    return fn


def c4(rally, oi_drop):
    def fn(f, uni):
        trig = ((f["chg24"] >= rally) & (f["oi_chg24"] <= -oi_drop) & (f["close"] < f["sma50d"])
                & (f["ema20_4"] < f["ema50_4"])).to_numpy() & uni
        conf = (f["close"] < f["low"].shift()).to_numpy()
        idx = _first_confirm(trig, conf, 12)
        stop = (f["hh24"] + 0.25 * f["atr1h"]).to_numpy()[idx]
        return idx, -1, stop
    return fn


def c5(n, side):
    def fn(f, uni):
        h4 = resample(f[["open", "high", "low", "close", "volume", "qv", "tbq"]], "4h")
        a4 = atr(h4, 14)
        if side == 1:
            pl = h4["low"].shift(1).rolling(n, min_periods=n).min()
            sig = (h4["low"] < pl) & (h4["close"] > pl)
            stop4 = h4["low"] - 0.25 * a4
        else:
            ph = h4["high"].shift(1).rolling(n, min_periods=n).max()
            sig = (h4["high"] > ph) & (h4["close"] < ph)
            stop4 = h4["high"] + 0.25 * a4
        t = h4.index[sig.fillna(False).to_numpy()] + pd.Timedelta(hours=3)   # last 1h bar of the 4h bar
        pos = f.index.get_indexer(t)
        keep = pos >= 0
        pos, st = pos[keep], stop4[sig.fillna(False)].to_numpy()[keep]
        ok = uni[pos]
        return pos[ok], side, st[ok]
    return fn


def c6(lo, hi, side):
    def fn(f, uni):
        if side == 1:
            trig = ((f["tbs4"] <= lo) & (f["qv4x"] >= 2) & (f["chg4"] >= 0)).to_numpy() & uni
            stop = (f["low4"] - 0.5 * f["atr1h"]).to_numpy()
        else:
            trig = ((f["tbs4"] >= hi) & (f["qv4x"] >= 2) & (f["chg4"] <= 0)).to_numpy() & uni
            stop = (f["high4"] + 0.5 * f["atr1h"]).to_numpy()
        idx = np.flatnonzero(trig)
        return idx, side, stop[idx]
    return fn


def c7(entry):
    """New listing short. Listing = first Binance perp bar, only listings after 2023-01-15
    (earlier first bars are just the start of the data). Own liquidity filter: average daily
    quote volume since listing >= $10M (the 30d filter cannot apply to a new coin)."""
    def fn(f, uni):
        t0 = f.index[0]
        empty = (np.array([], int), -1, np.array([]))
        if t0 < pd.Timestamp("2023-01-15"):
            return empty
        n = len(f)
        hrs = np.arange(n)
        dv = f["qv"].expanding(min_periods=24).mean().to_numpy() * 24
        ok = (dv >= 10e6) & (hrs >= 24) & (hrs <= 24 * 30) & (f.index >= pd.Timestamp("2023-02-01"))
        if entry == "time3d":
            i = 24 * 3 - 1
            idx = np.array([i]) if i < n and ok[i] else np.array([], int)
        else:
            orh = 24 if entry == "orb24" else 72
            if n <= orh + 4:
                return empty
            orl = np.nanmin(f["low"].to_numpy()[:orh])
            c = f["close"].to_numpy()
            # 4h closes only (1h bar index 3, 7, 11 ... after listing), after the opening range
            is4 = ((hrs + 1) % 4 == 0) & (hrs >= orh)
            cand = np.flatnonzero(is4 & ok & (c < orl))
            idx = cand[:1]
        if len(idx) == 0:
            return empty
        hh72 = f["high"].rolling(72, min_periods=1).max()
        stop = (hh72 + 0.25 * f["atr1h"]).to_numpy()[idx]
        return idx, -1, stop
    return fn


def variants():
    v = {}
    for th in (-0.0005, -0.0010):
        for cf in (False, True):
            v[f"C1 fund<={th*100:.2f}% {'confirm' if cf else 'at print'}"] = ("C1", c1(th, cf), False)
    for th in (0.0005, 0.0010):
        v[f"C2 prem8>={th*100:.2f}%"] = ("C2", c2(th), False)
    for k in (4, 6):
        for wg in (False, True):
            v[f"C3 {k}sigma {'green' if wg else 'at close'}"] = ("C3", c3(k, wg), False)
    for wg in (False, True):
        v[f"C3 4sigma +OI flush {'green' if wg else 'at close'}"] = ("C3", c3(4, wg, True), True)
    for ra in (0.06, 0.10):
        for od in (0.03, 0.06):
            v[f"C4 rally>={ra:.0%} OI<=-{od:.0%}"] = ("C4", c4(ra, od), True)
    for n in (20, 55):
        for s in (1, -1):
            v[f"C5 soup{n} {'long' if s == 1 else 'short'}"] = ("C5", c5(n, s), False)
    # thresholds ~ 5th / 2.5th percentile of the 4h taker buy share on >= 2x volume (IS, Binance
    # taker share is skewed: median ~0.49)
    for lo, hi in ((0.46, 0.53), (0.45, 0.54)):
        for s in (1, -1):
            v[f"C6 absorb {lo:.2f}/{hi:.2f} {'long' if s == 1 else 'short'}"] = ("C6", c6(lo, hi, s), False)
    out = {}
    for name, (cand, fn, need_oi) in v.items():
        for ex in ("T2R_48h", "T1R_24h", "trail_96h"):
            out[f"{name} | {ex}"] = (cand, fn, need_oi, ex)
    # round 2 (added after round 1 failed): new listing short, with multi day exits
    for e in ("orb24", "orb72", "time3d"):
        fn = c7(e)
        for ex in ("T2R_14d", "trail_14d", "hold_7d"):
            out[f"C7 newlist {e} | {ex}"] = ("C7", fn, False, ex)
    return out
