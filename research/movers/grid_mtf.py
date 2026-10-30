"""
His movers playbook, tested as the trades he actually places (30 Oct 2026).

The PARTI trade (30 Oct): +105% pump on the 1h, bars shrank under the peak, he opened a
Pionex SHORT futures grid 0.048..0.063 (peak 0.06415), 181 grids, 5x, $147 and closed it
manually 3h24m later at the 1h Bollinger midline (0.05165): +13.85% (grid 3.1%, trend 10.7%).

So the test here is that trade, not a tight-stop directional short:
  ENTRY  states read on 15m, 1h or 4h bars (resampled from Binance 15m):
         FADE   gainer (24h >= +25%), stretched >= 3 ATR above the midline, last 3 bars'
                range <= 0.7x the 3 before (compression), SAR flipped down in the last 3 bars
         FADE0  same but no SAR flip needed, just stretched + compressing (his earlier entry)
         DUMP   loser (24h <= -20%), SAR above price, below the midline, no touch for 12 bars
         RUN    gainer, SAR under price, above the midline, no touch for 12 bars
  TRADE  short grid (long grid for RUN): upper = 12-bar high (+0.5 ATR), lower = midline
         - 1.5 ATR (DUMP: upper = midline + 0.5 ATR, lower = close - 3 ATR), 100 grids,
         5x, stop 1 ATR beyond the far edge, max 72h. Exits: (a) his: close when price
         touches the trigger timeframe's midline (FADE) / 2 ATR past entry (DUMP, RUN);
         (b) hold to range edge / stop / 72h.
         Also the same entries as a plain directional position (no grid), same exits.
  PnL    Pionex grid fills on the 15m path (O->H->L->C or O->L->H->C by bar colour),
         fee 0.05% per fill, as % of margin (what the Pionex card shows).
  BASE   random entries in the same mover windows, same grid rules, same count.
"""
from __future__ import annotations

import sys
from multiprocessing import Pool
from pathlib import Path

import numba
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import psar  # noqa: E402

K15 = Path("/tmp/claude-0/-home-claude/f9afb357-b96a-5c99-93e3-0ac2bb39e920/scratchpad/k15")
K1H = Path("/tmp/claude-0/-home-claude/f9afb357-b96a-5c99-93e3-0ac2bb39e920/scratchpad/bum/k1h")
OUT = Path(__file__).resolve().parent / "results"
FEE = 0.0005
LEV = 5.0
NG = 100
MAXH = 72
IS_END = pd.Timestamp("2025-07-01")
TFS = {"15m": 1, "1h": 4, "4h": 16}


@numba.njit(cache=True)
def grid_sim(o, h, l, c, i0, side, lo, hi, stop, tgt, max_bars, use_tgt, ng, fee):
    """Pionex style futures grid from c[i0]. side -1 short grid, +1 long grid.
    Short grid: unit k (band [L_k, L_k+1]) is short while price is above L_k; sold at
    L_k+1 (or at entry, for bands below the start price), bought back at L_k.
    Returns (pnl as fraction of notional cap, exit bar, code, grid part, fills).
    code 0 stop, 1 target, 2 time, 3 data end."""
    L = np.linspace(lo, hi, ng + 1)
    p0 = c[i0]
    q = 1.0 / ng                      # each unit is 1/ng of the full notional (at ~price 1)
    open_ = np.zeros(ng, dtype=np.bool_)
    ent = np.zeros(ng)
    realised = 0.0
    gridp = 0.0
    fills = 0
    # initial position, bought at market
    for k in range(ng):
        if side == -1 and L[k] < p0:     # band below price -> short now, cover at L_k
            open_[k] = True
            ent[k] = p0
            fills += 1
            realised -= fee * q
        if side == 1 and L[k + 1] > p0:  # band above price -> long now, sell at L_k+1
            open_[k] = True
            ent[k] = p0
            fills += 1
            realised -= fee * q
    n = len(c)
    last = min(n - 1, i0 + max_bars)
    code = 2
    px = c[last]
    j = i0
    for j in range(i0 + 1, last + 1):
        if not np.isfinite(c[j]):
            code = 3
            px = c[j - 1]
            break
        path = (o[j], h[j], l[j], c[j]) if c[j] < o[j] else (o[j], l[j], h[j], c[j])
        done = False
        prev = path[0]
        for s in range(1, 4):
            a, b = prev, path[s]
            prev = b
            # stop beyond the far edge
            if side == -1 and b >= stop:
                px, code, done = stop, 0, True
                break
            if side == 1 and b <= stop:
                px, code, done = stop, 0, True
                break
            # grid fills between a and b
            for k in range(ng):
                if side == -1:
                    if open_[k] and b <= L[k] < a:                 # falling through L_k: cover
                        r = (ent[k] - L[k]) / ent[k] * q
                        realised += r - fee * q
                        gridp += r
                        open_[k] = False
                        fills += 1
                    elif (not open_[k]) and a < L[k + 1] <= b:     # rising to L_k+1: re-short
                        open_[k] = True
                        ent[k] = L[k + 1]
                        realised -= fee * q
                        fills += 1
                else:
                    if open_[k] and a < L[k + 1] <= b:
                        r = (L[k + 1] - ent[k]) / ent[k] * q
                        realised += r - fee * q
                        gridp += r
                        open_[k] = False
                        fills += 1
                    elif (not open_[k]) and b <= L[k] < a:
                        open_[k] = True
                        ent[k] = L[k]
                        realised -= fee * q
                        fills += 1
            if use_tgt and ((side == -1 and b <= tgt) or (side == 1 and b >= tgt)):
                px, code, done = tgt, 1, True
                break
        if done:
            break
    # close what is open at px
    for k in range(ng):
        if open_[k]:
            r = (ent[k] - px) / ent[k] * q if side == -1 else (px - ent[k]) / ent[k] * q
            realised += r - fee * q
    return realised, j, code, gridp, fills


def tf_frame(k15: pd.DataFrame, mult: int) -> pd.DataFrame:
    if mult == 1:
        return k15[["open", "high", "low", "close"]].copy()
    r = f"{15 * mult}min"
    g = k15.resample(r, label="left", closed="left")
    d = g.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    cnt = k15["close"].resample(r, label="left", closed="left").count()
    return d[cnt == mult].dropna()


def states(d: pd.DataFrame) -> pd.DataFrame:
    h, l, c = d["high"], d["low"], d["close"]
    f = pd.DataFrame(index=d.index)
    f["c"] = c
    f["mid"] = c.rolling(20).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    f["atr"] = tr.rolling(14).mean()
    sar, up = psar(h.to_numpy(float), l.to_numpy(float))
    up = pd.Series(up, index=d.index)
    flip_dn = (up == -1) & (up.shift() == 1)
    f["flipdn3"] = flip_dn | flip_dn.shift(1, fill_value=False) | flip_dn.shift(2, fill_value=False)
    f["up"] = up
    rng = h - l
    f["comp"] = rng.rolling(3).mean() / rng.shift(3).rolling(3).mean()
    f["hh"], f["ll"] = h.rolling(12).max(), l.rolling(12).min()
    f["str_up"] = (f["hh"] - f["mid"]) / f["atr"]
    f["str_dn"] = (f["mid"] - f["ll"]) / f["atr"]
    touch = ((l <= f["mid"]) & (h >= f["mid"])).astype(int)
    f["since"] = touch.groupby(touch.cumsum()).cumcount()
    return f


def known_at_15m(f: pd.DataFrame, mult: int, idx15: pd.DatetimeIndex) -> pd.DataFrame:
    """Each TF bar's values become known at its close; map onto 15m bar closes."""
    g = f.copy()
    g.index = g.index + pd.Timedelta(minutes=15 * mult)       # close time
    at = idx15 + pd.Timedelta(minutes=15)                     # 15m close times
    out = g.reindex(g.index.union(at)).ffill().reindex(at)
    out.index = idx15
    return out


SETUPS = ("FADE", "FADE0", "DUMP", "RUN")


def run_coin(path: Path):
    s = path.stem
    k = pd.read_parquet(path)
    k = k[~k.index.duplicated()].sort_index()
    if len(k) < 2000:
        return None
    full = pd.date_range(k.index[0], k.index[-1], freq="15min")
    k = k.reindex(full)
    o, h, l, c = (k[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    chg = k["close"] / k["close"].shift(96) - 1
    dv = (k["quote_volume"].rolling(96 * 7, min_periods=96 * 3).mean() * 96).to_numpy()
    liquid = np.nan_to_num(dv) >= 5e6
    gain = (chg >= 0.25).to_numpy() & liquid
    lose = (chg <= -0.20).to_numpy() & liquid
    rng = np.random.default_rng(abs(hash(s)) % (2**32))
    rows = []
    for tf, mult in TFS.items():
        f = known_at_15m(states(tf_frame(k, mult)), mult, k.index)
        mid, atr, cc = f["mid"].to_numpy(), f["atr"].to_numpy(), c
        hh, ll = f["hh"].to_numpy(), f["ll"].to_numpy()
        new_bar = np.zeros(len(k), dtype=bool)
        new_bar[(np.arange(len(k)) + 1) % mult == 0] = True    # a TF bar just closed
        ok = np.isfinite(mid) & np.isfinite(atr) & (atr > 0)
        sig = {
            "FADE": gain & (f["str_up"] >= 3).to_numpy() & (f["comp"] <= 0.7).to_numpy()
                    & f["flipdn3"].fillna(False).to_numpy().astype(bool) & (cc > mid + 0.5 * atr),
            "FADE0": gain & (f["str_up"] >= 3).to_numpy() & (f["comp"] <= 0.7).to_numpy()
                     & (cc > mid + 0.5 * atr) & (f["up"] == 1).to_numpy(),
            "DUMP": lose & (f["up"] == -1).to_numpy() & (cc < mid) & (f["since"] >= 12).to_numpy()
                    & (f["str_dn"] < 6).to_numpy(),
            "RUN": gain & (f["up"] == 1).to_numpy() & (cc > mid) & (f["since"] >= 12).to_numpy()
                   & (f["str_up"] < 6).to_numpy(),
        }
        for name in SETUPS:
            m = sig[name] & ok & new_bar
            ii = np.flatnonzero(m)
            pool = np.flatnonzero((gain if name != "DUMP" else lose) & ok & new_bar)
            rnd = np.sort(rng.choice(pool, size=min(len(ii), len(pool)), replace=False)) if len(ii) and len(pool) else np.array([], int)
            side = 1 if name == "RUN" else -1
            for kind, idx in (("sig", ii), ("rand", rnd)):
                busy = -1
                for i in idx:
                    if i <= busy or i + 4 >= len(c):
                        continue
                    a = atr[i]
                    if side == -1 and name.startswith("FADE"):
                        hi = max(hh[i], cc[i]) + 0.5 * a
                        lo = min(mid[i] - 1.5 * a, cc[i] - 2 * a)
                        tgt = mid[i]
                    elif side == -1:
                        hi = max(mid[i], cc[i]) + 0.5 * a
                        lo = cc[i] - 3 * a
                        tgt = cc[i] - 2 * a
                    else:
                        lo = min(mid[i], cc[i]) - 0.5 * a
                        hi = cc[i] + 3 * a
                        tgt = cc[i] + 2 * a
                    if lo <= 0 or hi <= lo:
                        continue
                    stop = hi + a if side == -1 else lo - a
                    width = (hi - lo) / cc[i]
                    if not (0.03 <= width <= 0.8):
                        continue
                    mb = MAXH * 4
                    res = {}
                    for ex, use in (("his", True), ("hold", False)):
                        pnl, j, code, gp, nf = grid_sim(o, h, l, c, int(i), side, lo, hi, stop, tgt, mb, use, NG, FEE)
                        res[ex] = (pnl, j, code, gp)
                        # directional version: full notional at entry, same stop and target
                        pe = cc[i]
                        jj, px, cd = i, np.nan, 2
                        for jj in range(i + 1, min(len(c) - 1, i + mb) + 1):
                            if not np.isfinite(c[jj]):
                                px, cd = c[jj - 1], 3
                                break
                            if (side == -1 and h[jj] >= stop) or (side == 1 and l[jj] <= stop):
                                px, cd = stop, 0
                                break
                            if use and ((side == -1 and l[jj] <= tgt) or (side == 1 and h[jj] >= tgt)):
                                px, cd = tgt, 1
                                break
                        if not np.isfinite(px):
                            px = c[jj]
                        dpnl = (px - pe) / pe * side - 2 * FEE
                        res["dir_" + ex] = (dpnl, jj, cd, 0.0)
                    busy = max(v[1] for v in res.values())
                    t = k.index[i] + pd.Timedelta(minutes=15)
                    for ex, (pnl, j, code, gp) in res.items():
                        rows.append((s, tf, name, kind, ex, t, max(pnl * LEV, -1.0), gp * LEV, code,
                                     (j - i) / 4, width, (stop - cc[i]) / cc[i] * side * -1))
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["sym", "tf", "setup", "kind", "exit", "t", "roe", "grid_roe",
                                       "code", "hours", "width", "stop_pct"])


def table(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for key, g in df.groupby(["setup", "tf", "exit", "kind"]):
        for per, m in (("IS 2022-25", g.t < IS_END), ("OOS 2025-26", g.t >= IS_END)):
            r = g.loc[m, "roe"]
            if len(r) < 15:
                continue
            w, lo = r[r > 0].sum(), -r[r < 0].sum()
            out.append(dict(setup=key[0], tf=key[1], exit=key[2], kind=key[3], period=per, n=len(r),
                            pf=round(w / lo, 2) if lo else np.inf, avg_roe=round(r.mean() * 100, 2),
                            med_roe=round(r.median() * 100, 2), win=round((r > 0).mean(), 2),
                            worst=round(r.min() * 100, 1),
                            t=round(r.mean() / (r.std(ddof=1) / np.sqrt(len(r))), 2),
                            hours=round(g.loc[m, "hours"].median(), 1)))
    return pd.DataFrame(out)


if __name__ == "__main__":
    files = sorted(K15.glob("*.parquet"))
    if len(sys.argv) > 1:
        files = files[: int(sys.argv[1])]
    with Pool() as p:
        parts = [x for x in p.map(run_coin, files, chunksize=2) if x is not None]
    df = pd.concat(parts, ignore_index=True)
    OUT.mkdir(exist_ok=True)
    df.to_parquet(OUT / "grid_mtf_trades.parquet")
    t = table(df)
    t.to_csv(OUT / "grid_mtf_summary.csv", index=False)
    pd.set_option("display.width", 250, "display.max_rows", 500)
    print(t.to_string(index=False))
