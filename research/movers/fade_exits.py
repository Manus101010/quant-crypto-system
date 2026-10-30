"""FADE exits: the fade hits the midline ~7 in 10, so test where the loss leaks.
Plain short positions, R per trade, fee 0.1% round trip. Chosen in sample (to Jul 2025),
then read out of sample. Run: python research/movers/fade_exits.py"""
from __future__ import annotations

import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grid_mtf import K15, TFS, known_at_15m, states, tf_frame  # noqa: E402
from run import psar  # noqa: E402

FEE = 0.001
IS_END = pd.Timestamp("2025-07-01")
# stop: peak = 12 bar high + buf ATR ; exits: mid / mid_half (half at mid, rest to lower band)
# flip = also exit when the TF SAR flips back up ; time 24 TF bars
VARIANTS = [(sb, ex, fl) for sb in (0.1, 0.5, 1.0, 2.0) for ex in ("mid", "half") for fl in (False, True)]


def run_coin(path):
    k = pd.read_parquet(path)
    k = k[~k.index.duplicated()].sort_index()
    if len(k) < 2000:
        return None
    k = k.reindex(pd.date_range(k.index[0], k.index[-1], freq="15min"))
    o, h, l, c = (k[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    chg = (k["close"] / k["close"].shift(96) - 1).to_numpy()
    dv = (k["quote_volume"].rolling(96 * 7, min_periods=96 * 3).mean() * 96).to_numpy()
    gain = (chg >= 0.25) & (np.nan_to_num(dv) >= 5e6)
    rows = []
    for tf, mult in (("15m", 1), ("1h", 4)):
        d = tf_frame(k, mult)
        f = known_at_15m(states(d), mult, k.index)
        mid, atr, hh = f["mid"].to_numpy(), f["atr"].to_numpy(), f["hh"].to_numpy()
        up = f["up"].to_numpy()
        sd = d["close"].rolling(20).std()
        lowb = known_at_15m((d["close"].rolling(20).mean() - 2 * sd).to_frame("lb"), mult, k.index)["lb"].to_numpy()
        new_bar = (np.arange(len(k)) + 1) % mult == 0
        sig = (gain & (f["str_up"] >= 3).to_numpy() & (f["comp"] <= 0.7).to_numpy()
               & f["flipdn3"].fillna(False).to_numpy().astype(bool) & (c > mid + 0.5 * atr)
               & np.isfinite(atr) & new_bar)
        for i in np.flatnonzero(sig):
            pe, a = c[i], atr[i]
            for sb, ex, fl in VARIANTS:
                stop = hh[i] + sb * a
                risk = (stop - pe) / pe
                if risk <= 0.003:
                    continue
                tgt1, tgt2 = mid[i], lowb[i]
                half = False
                got = 0.0
                px, last = np.nan, min(len(c) - 1, i + 24 * mult)
                for j in range(i + 1, last + 1):
                    if not np.isfinite(c[j]):
                        px = c[j - 1]
                        break
                    if h[j] >= stop:
                        px = stop if o[j] < stop else o[j]
                        break
                    if ex == "mid" and l[j] <= tgt1:
                        px = tgt1
                        break
                    if ex == "half":
                        if not half and l[j] <= tgt1:
                            half, got = True, (pe - tgt1) / pe * 0.5
                            stop = min(stop, pe)          # rest to breakeven
                        if half and np.isfinite(tgt2) and l[j] <= tgt2:
                            px = tgt2
                            break
                    if fl and (j + 1) % mult == 0 and up[j] == 1:
                        px = c[j]
                        break
                if not np.isfinite(px):
                    px = c[last]
                rest = 0.5 if half else 1.0
                r = (got + rest * (pe - px) / pe - FEE) / risk
                rows.append((path.stem, tf, f"stop{sb}_{ex}{'_flip' if fl else ''}", k.index[i], r, risk))
    return pd.DataFrame(rows, columns=["sym", "tf", "v", "t", "R", "risk"]) if rows else None


if __name__ == "__main__":
    with Pool() as p:
        df = pd.concat([x for x in p.map(run_coin, sorted(K15.glob("*.parquet")), chunksize=2) if x is not None])
    df.to_parquet(Path(__file__).resolve().parent / "results" / "fade_exits.parquet")
    out = []
    for (tf, v), g in df.groupby(["tf", "v"]):
        for per, m in (("IS", g.t < IS_END), ("OOS", g.t >= IS_END)):
            r = g.R[m]
            w, lo = r[r > 0].sum(), -r[r < 0].sum()
            out.append((tf, v, per, len(r), round(w / lo, 2), round(r.mean(), 3), round((r > 0).mean(), 2),
                        round(r.mean() / r.std() * np.sqrt(len(r)), 2), round(g.risk[m].median() * 100, 1)))
    t = pd.DataFrame(out, columns=["tf", "v", "per", "n", "pf", "avgR", "win", "t", "stop%"])
    pd.set_option("display.width", 200, "display.max_rows", 200)
    print(t.pivot_table(index=["tf", "v"], columns="per", values=["n", "pf", "avgR", "win", "t", "stop%"]).round(2).to_string())
