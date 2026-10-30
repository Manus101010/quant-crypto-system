"""
Daily movers, tested the way he trades them (30 Oct 2026).

He sorts the day's biggest gainers and losers, opens five of each and looks for:
  G_FADE   gainer that is compressing on the 1h (bars shrinking while it rises) and rolling
           over (Parabolic SAR flips above price). Short, target the 1h Bollinger midline
           (20 SMA). Stop above the high since the peak.
  G_RUN    gainer still ripping: above the 1h midline, SAR still under price, has not come
           back to the midline since the run started. Long, stop under the SAR, trail.
  L_BOUNCE loser compressing and turning up (SAR flips under price). Long to the midline.
  L_CONT   loser still dumping (SAR above price, below the midline). Short, trail.
Each also with his higher-timeframe caution: skip fades that fight a fresh 90 day breakout
(or breakdown), skip runs that are against the 4h trend.

A mover is a coin whose rolling 24h change is >= +GAIN (gainers) or <= -LOSS (losers) at
the 1h close. One trade per coin at a time. Entry at the trigger bar close.

Baseline: the same mover lists, the same stop and target geometry, but entering at a
random bar of the mover window instead of on the trigger. If the trigger does not beat
that, the timing is not the edge, the list is.

Reuses research/my_edge data (Binance USDT-M 1h, delisted included) and its sim().
Run: python research/movers/run.py
"""
from __future__ import annotations

import sys
from multiprocessing import Pool
from pathlib import Path

import numba
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "my_edge"))
import core as C   # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
NAN = float("nan")
RNG_SEED = 7


@numba.njit(cache=True)
def psar(h, l, af0=0.02, step=0.02, amax=0.2):
    n = len(h)
    sar = np.full(n, np.nan)
    up = np.zeros(n, dtype=np.int8)
    if n < 3:
        return sar, up
    bull = True
    s = l[0]
    ep = h[0]
    af = af0
    for i in range(1, n):
        if not (np.isfinite(h[i]) and np.isfinite(l[i])):
            sar[i] = s
            up[i] = 1 if bull else -1
            continue
        s = s + af * (ep - s)
        if bull:
            s = min(s, l[i - 1], l[max(i - 2, 0)])
            if l[i] < s:
                bull = False
                s = ep
                ep = l[i]
                af = af0
            elif h[i] > ep:
                ep = h[i]
                af = min(af + step, amax)
        else:
            s = max(s, h[i - 1], h[max(i - 2, 0)])
            if h[i] > s:
                bull = True
                s = ep
                ep = h[i]
                af = af0
            elif l[i] < ep:
                ep = l[i]
                af = min(af + step, amax)
        sar[i] = s
        up[i] = 1 if bull else -1
    return sar, up


def features(k: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = k["open"], k["high"], k["low"], k["close"]
    f = pd.DataFrame(index=k.index)
    f["chg24"] = c / c.shift(24) - 1
    f["mid"] = c.rolling(20).mean()
    sd = c.rolling(20).std()
    f["bbu"], f["bbl"] = f["mid"] + 2 * sd, f["mid"] - 2 * sd
    f["atr"] = C.atr(h, l, c, 14)
    sar, up = psar(h.to_numpy(), l.to_numpy())
    f["sar"], f["up"] = sar, up
    f["flip_dn"] = (f["up"] == -1) & (f["up"].shift() == 1)
    f["flip_up"] = (f["up"] == 1) & (f["up"].shift() == -1)
    rng = (h - l)
    # compression: the last 3 bars' average range is well below the 3 before, which were
    # the expansion bars of the move
    f["comp"] = rng.rolling(3).mean() / rng.shift(3).rolling(3).mean()
    f["hh12"], f["ll12"] = h.rolling(12).max(), l.rolling(12).min()
    # stretch at the move's extreme: how far the 12h high sat above the midline, in ATR
    f["stretch_up"] = (f["hh12"] - f["mid"]) / f["atr"]
    f["stretch_dn"] = (f["mid"] - f["ll12"]) / f["atr"]
    # bars since price last touched the midline
    touch = ((l <= f["mid"]) & (h >= f["mid"])).astype(float)
    grp = touch.cumsum()
    f["since_mid"] = touch.groupby(grp).cumcount()
    # higher timeframe: fresh 90 day breakout / breakdown, 4h trend
    f["hi90"] = h.shift(1).rolling(24 * 90, min_periods=24 * 60).max()
    f["lo90"] = l.shift(1).rolling(24 * 90, min_periods=24 * 60).min()
    f["brk_up"] = h.rolling(24).max() >= f["hi90"]
    f["brk_dn"] = l.rolling(24).min() <= f["lo90"]
    e20, e50 = C.ema(c, 80), C.ema(c, 200)          # ~ 4h EMA20 / EMA50 on 1h bars
    f["tr4_up"] = (c > e20) & (e20 > e50)
    f["tr4_dn"] = (c < e20) & (e20 < e50)
    return f


GAIN, LOSS = 0.25, 0.20
SETUPS = ("G_FADE", "G_FADE_htf", "G_RUN", "G_RUN_htf", "L_BOUNCE", "L_BOUNCE_htf", "L_CONT", "L_CONT_htf")


def triggers(f: pd.DataFrame, c: np.ndarray, h: np.ndarray, l: np.ndarray) -> dict:
    gain = (f["chg24"] >= GAIN).to_numpy()
    lose = (f["chg24"] <= -LOSS).to_numpy()
    mid, atr, sar = f["mid"].to_numpy(), f["atr"].to_numpy(), f["sar"].to_numpy()
    comp = f["comp"].to_numpy()
    out = {}
    # G_FADE: gainer, stretched, compressing, SAR flips down, still above the mid (room)
    g = gain & (f["stretch_up"] >= 3).to_numpy() & (comp <= 0.7) & f["flip_dn"].to_numpy() & (c > mid + 0.5 * atr)
    stop = f["hh12"].to_numpy() + 0.1 * atr
    out["G_FADE"] = (g, -1, stop, mid)
    out["G_FADE_htf"] = (g & ~f["brk_up"].to_numpy(), -1, stop, mid)
    # G_RUN: gainer, SAR up, above mid, has not touched mid for >= 12 bars, not stretched > 6 ATR
    r = gain & (f["up"] == 1).to_numpy() & (c > mid) & (f["since_mid"] >= 12).to_numpy() & (f["stretch_up"] < 6).to_numpy()
    r = r & ~np.roll(r, 1)                                 # first bar of the condition
    rstop = np.minimum(sar, mid) - 0.1 * atr
    out["G_RUN"] = (r, 1, rstop, np.full_like(c, NAN))
    out["G_RUN_htf"] = (r & f["tr4_up"].to_numpy(), 1, rstop, np.full_like(c, NAN))
    # L_BOUNCE: mirror of G_FADE
    b = lose & (f["stretch_dn"] >= 3).to_numpy() & (comp <= 0.7) & f["flip_up"].to_numpy() & (c < mid - 0.5 * atr)
    bstop = f["ll12"].to_numpy() - 0.1 * atr
    out["L_BOUNCE"] = (b, 1, bstop, mid)
    out["L_BOUNCE_htf"] = (b & ~f["brk_dn"].to_numpy(), 1, bstop, mid)
    # L_CONT: mirror of G_RUN
    d = lose & (f["up"] == -1).to_numpy() & (c < mid) & (f["since_mid"] >= 12).to_numpy() & (f["stretch_dn"] < 6).to_numpy()
    d = d & ~np.roll(d, 1)
    dstop = np.maximum(sar, mid) + 0.1 * atr
    out["L_CONT"] = (d, -1, dstop, np.full_like(c, NAN))
    out["L_CONT_htf"] = (d & f["tr4_dn"].to_numpy(), -1, dstop, np.full_like(c, NAN))
    out["_window_g"], out["_window_l"] = gain, lose
    return out


# exits: fixed target at the midline (mean reversion) or an ATR-ish % trail (runs)
EXITS = {"mid_48h": "mid", "mid_then_2R": "mid2", "tr5": "trail", "T2R_48h": "2r"}


def run_coin(sym: str):
    k = C.load(sym)
    if k is None:
        return None
    k = k[k.index >= C.PRE_START - pd.Timedelta(days=100)]
    if len(k) < 24 * 100:
        return None
    f = features(k)
    o, h, l, c, fu = (k[x].to_numpy() for x in ("open", "high", "low", "close", "fund"))
    dv = k["dvol30"].to_numpy()
    dead = bool(k["dead"].iloc[0])
    tc = (k.index + pd.Timedelta(hours=1))
    tr = triggers(f, c, h, l)
    rng = np.random.default_rng(abs(hash(sym)) % (2**32) + RNG_SEED)
    rows = []
    liquid = np.nan_to_num(dv) >= C.MIN_DVOL
    for name in SETUPS:
        sig, side, stop, tgt = tr[name]
        sig = sig & liquid & (tc >= C.PRE_START)
        ii = np.flatnonzero(sig)
        # random baseline: same count, random bars from the same mover window (same side)
        win = (tr["_window_g"] if name.startswith("G") else tr["_window_l"]) & liquid & (tc >= C.PRE_START)
        pool = np.flatnonzero(win)
        rand = np.sort(rng.choice(pool, size=min(len(ii), len(pool)), replace=False)) if len(ii) and len(pool) else np.array([], int)
        for kind, idx in (("sig", ii), ("rand", rand)):
            for xn, xm in EXITS.items():
                if xm in ("mid", "mid2") and not name.startswith(("G_FADE", "L_BOUNCE")):
                    continue
                busy = -1
                for i in idx:
                    if i <= busy:
                        continue
                    # random entries use the same stop and target formulas at their own bar
                    st = stop[i]
                    tg = tgt[i] if kind == "sig" or not np.isnan(tgt[i]) else NAN
                    if kind == "rand" and xm in ("mid", "mid2"):
                        tg = f["mid"].iat[i]
                    risk = (c[i] - st) * side / c[i]
                    if not np.isfinite(risk) or risk < C.MIN_STOP or risk > C.MAX_STOP:
                        continue
                    if xm in ("mid", "mid2"):
                        if not np.isfinite(tg) or (tg - c[i]) * side <= 0:
                            continue
                        tgt_r = (tg - c[i]) * side / (c[i] - st) / side
                        tgt_r = abs((tg - c[i]) / (c[i] - st))
                        if xm == "mid2":
                            tgt_r = max(tgt_r, 2.0)
                        j, net, sp, code, gross = C.sim(o, h, l, c, fu, int(i), side, float(st), 0.0, NAN, float(tgt_r), 48, 0.0, dead)
                    elif xm == "trail":
                        j, net, sp, code, gross = C.sim(o, h, l, c, fu, int(i), side, float(st), 0.0, 0.05, NAN, 168, 0.0, dead)
                    else:
                        j, net, sp, code, gross = C.sim(o, h, l, c, fu, int(i), side, float(st), 0.0, NAN, 2.0, 48, 0.0, dead)
                    busy = j
                    if code == 5:
                        continue
                    rows.append((sym, name, kind, xn, tc[i], side, net, sp, code))
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["sym", "setup", "kind", "exit", "t", "side", "net0", "stop_pct", "code"])


def pf(r):
    w, lo = r[r > 0].sum(), -r[r < 0].sum()
    return w / lo if lo > 0 else np.inf


def summarise(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (s, x, kind), g in df.groupby(["setup", "exit", "kind"]):
        for cn, cost in C.COSTS.items():
            r = (g["net0"] - cost) / g["stop_pct"]
            for per, m in (("IS", (g.t >= C.IS_START) & (g.t < C.IS_END)), ("OOS", g.t >= C.IS_END),
                           ("PRE", g.t < C.IS_START)):
                rr = r[m]
                if len(rr) < 10:
                    continue
                out.append(dict(setup=s, exit=x, kind=kind, cost=cn, period=per, n=len(rr),
                                pf=round(pf(rr), 2), avgR=round(rr.mean(), 3),
                                win=round((rr > 0).mean(), 2),
                                t=round(rr.mean() / (rr.std(ddof=1) / np.sqrt(len(rr))), 2)))
    return pd.DataFrame(out)


if __name__ == "__main__":
    syms = C.universe_symbols()
    if len(sys.argv) > 1:
        syms = syms[: int(sys.argv[1])]
    with Pool() as p:
        parts = [x for x in p.map(run_coin, syms, chunksize=4) if x is not None]
    df = pd.concat(parts, ignore_index=True)
    OUT.mkdir(exist_ok=True)
    df.to_parquet(OUT / "trades.parquet")
    s = summarise(df)
    s.to_csv(OUT / "summary.csv", index=False)
    pd.set_option("display.width", 200, "display.max_rows", 500)
    print(s[s.cost == "maker"].pivot_table(index=["setup", "exit", "kind"], columns="period",
                                            values=["n", "pf", "avgR"]).round(2))
