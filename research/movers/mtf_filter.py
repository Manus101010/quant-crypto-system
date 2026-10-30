"""His tell (30 Oct): "if the 4h is rolling over and you get a 15m entry, a 15m bounce rarely
breaks that 4h turn". So filter lower timeframe entries by the 4h state.

Entries on 15m and 1h (same definitions as grid_mtf.py): FADE, FADE0 (shorts), RUN (long),
DUMP (short). 4h state, known only after the 4h bar closes:
  4h_roll   : 4h SAR flipped down within the last 3 4h bars, or 4h close below the prior
              4h bar's low while the 4h top is >= 2 ATR(4h) above the 4h midline
  4h_down   : 4h SAR above price
  4h_up     : 4h SAR under price and 4h close above the 4h midline
Trade: plain position. Shorts: stop = 12 bar high + 1 ATR, exit at the midline (FADE*) or
2 ATR (DUMP); long RUN: stop = min(midline, close) - 0.5 ATR, exit +2 ATR. Max 24 bars.
R per trade, 0.1% round trip. Random entries in the same mover window AND the same 4h state
show whether the 4h filter alone is the edge.
"""
from __future__ import annotations

import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grid_mtf import K15, known_at_15m, states, tf_frame  # noqa: E402

FEE = 0.001
IS_END = pd.Timestamp("2025-07-01")


def trade(o, h, l, c, i, side, stop, tgt, bars):
    pe = c[i]
    risk = (stop - pe) / pe * -side
    if risk <= 0.003 or risk > 0.6:
        return None
    px, last = np.nan, min(len(c) - 1, i + bars)
    for j in range(i + 1, last + 1):
        if not np.isfinite(c[j]):
            px = c[j - 1]
            break
        if side == -1 and h[j] >= stop:
            px = max(stop, o[j])
            break
        if side == 1 and l[j] <= stop:
            px = min(stop, o[j])
            break
        if (side == -1 and l[j] <= tgt) or (side == 1 and h[j] >= tgt):
            px = tgt
            break
    if not np.isfinite(px):
        px = c[last]
    return ((px - pe) / pe * side - FEE) / risk


def run_coin(path):
    k = pd.read_parquet(path)
    k = k[~k.index.duplicated()].sort_index()
    if len(k) < 2000:
        return None
    k = k.reindex(pd.date_range(k.index[0], k.index[-1], freq="15min"))
    o, h, l, c = (k[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    chg = (k["close"] / k["close"].shift(96) - 1).to_numpy()
    dv = (k["quote_volume"].rolling(96 * 7, min_periods=96 * 3).mean() * 96).to_numpy()
    liq = np.nan_to_num(dv) >= 5e6
    gain, lose = (chg >= 0.25) & liq, (chg <= -0.20) & liq
    d4 = tf_frame(k, 16)
    s4 = states(d4)
    s4["lowerclose"] = d4["close"] < d4["low"].shift(1)
    f4 = known_at_15m(s4, 16, k.index)
    up4 = f4["up"].to_numpy()
    roll4 = (f4["flipdn3"].fillna(False).to_numpy().astype(bool)
             | (f4["lowerclose"].fillna(False).to_numpy().astype(bool) & (f4["str_up"] >= 2).to_numpy()))
    above4 = (f4["c"] > f4["mid"]).to_numpy()
    st4 = {"any": np.ones(len(k), bool), "4h_roll": roll4, "4h_down": up4 == -1,
           "4h_up": (up4 == 1) & above4, "4h_not_roll": ~roll4 & (up4 == 1)}
    rng = np.random.default_rng(abs(hash(path.stem)) % (2**32))
    rows = []
    for tf, mult in (("15m", 1), ("1h", 4)):
        f = known_at_15m(states(tf_frame(k, mult)), mult, k.index)
        mid, atr, hh = f["mid"].to_numpy(), f["atr"].to_numpy(), f["hh"].to_numpy()
        nb = ((np.arange(len(k)) + 1) % mult == 0) & np.isfinite(atr) & np.isfinite(mid) & (atr > 0)
        comp, sup, up, since = (f["comp"].to_numpy(), f["str_up"].to_numpy(), f["up"].to_numpy(),
                                f["since"].to_numpy())
        flip = f["flipdn3"].fillna(False).to_numpy().astype(bool)
        sig = {
            "FADE": gain & (sup >= 3) & (comp <= 0.7) & flip & (c > mid + 0.5 * atr),
            "FADE0": gain & (sup >= 3) & (comp <= 0.7) & (c > mid + 0.5 * atr) & (up == 1),
            "RUN": gain & (up == 1) & (c > mid) & (since >= 12) & (sup < 6),
            "DUMP": lose & (up == -1) & (c < mid) & (since >= 12) & (f["str_dn"].to_numpy() < 6),
        }
        for name, s in sig.items():
            side = 1 if name == "RUN" else -1
            window = (lose if name == "DUMP" else gain) & nb
            for fname, fm in st4.items():
                ii = np.flatnonzero(s & nb & fm)
                pool = np.flatnonzero(window & fm)
                rnd = np.sort(rng.choice(pool, min(len(ii), len(pool)), replace=False)) if len(ii) and len(pool) else []
                for kind, idx in (("sig", ii), ("rand", rnd)):
                    busy = -1
                    for i in idx:
                        if i <= busy:
                            continue
                        a = atr[i]
                        if name.startswith("FADE"):
                            stop, tgt = hh[i] + a, mid[i]
                            if tgt >= c[i]:
                                continue
                        elif name == "DUMP":
                            stop, tgt = max(mid[i], c[i]) + 0.5 * a, c[i] - 2 * a
                        else:
                            stop, tgt = min(mid[i], c[i]) - 0.5 * a, c[i] + 2 * a
                        r = trade(o, h, l, c, i, side, stop, tgt, 24 * mult)
                        if r is None:
                            continue
                        busy = i + 4 * mult            # no stacking within the hour (15m) / 4h (1h)
                        rows.append((path.stem, tf, name, fname, kind, k.index[i], r))
    return pd.DataFrame(rows, columns=["sym", "tf", "setup", "f4", "kind", "t", "R"]) if rows else None


def stats(r):
    if len(r) < 15:
        return None
    w, lo = r[r > 0].sum(), -r[r < 0].sum()
    return len(r), round(w / lo, 2), round(r.mean(), 3), round((r > 0).mean(), 2), round(r.mean() / r.std() * np.sqrt(len(r)), 2)


if __name__ == "__main__":
    with Pool() as p:
        df = pd.concat([x for x in p.map(run_coin, sorted(K15.glob("*.parquet")), chunksize=2) if x is not None])
    out = Path(__file__).resolve().parent / "results"
    df.to_parquet(out / "mtf_filter.parquet")
    rows = []
    for key, g in df.groupby(["setup", "tf", "f4", "kind"]):
        for per, m in (("IS", g.t < IS_END), ("OOS", g.t >= IS_END), ("ALL", g.t.notna())):
            s = stats(g.R[m])
            if s:
                rows.append((*key, per, *s))
    t = pd.DataFrame(rows, columns=["setup", "tf", "f4", "kind", "per", "n", "pf", "avgR", "win", "t"])
    t.to_csv(out / "mtf_filter_summary.csv", index=False)
    pd.set_option("display.width", 250, "display.max_rows", 400)
    print(t.pivot_table(index=["setup", "tf", "f4"], columns=["kind", "per"], values=["n", "pf", "t"], aggfunc="first").to_string())
