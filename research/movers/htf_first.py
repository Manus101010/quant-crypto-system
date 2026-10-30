"""The trade as he takes it (30 Oct): the 4h rolls over FIRST on a coin that pumped, then a
15m bounce fails and he shorts it ("a 15m bounce rarely breaks the 4h turn").

Window: coin pumped (3 day high >= 30% above the 6 day low) and the 4h SAR is above price,
having flipped down within the last N 4h bars (N = 6, i.e. a fresh turn, or 18).
Entry: the 15m SAR flips back down (the 15m bounce has failed). Optional: the bounce got
back to the 15m midline first (BNC).
Stop: 15m 12 bar high + 0.3 ATR(15m) ("tight"), or the 4h SAR level ("4h").
Exits: 2R, 3R, or ride until the 4h SAR flips back up (max 72h).
R per trade, 0.1% round trip. Random 15m entries in the same window, same stop rule.
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


def sim(o, h, l, c, up4, i, stop, mode):
    pe = c[i]
    risk = (stop - pe) / pe
    if risk <= 0.004 or risk > 0.5:
        return None
    tgt = pe * (1 - risk * {"2R": 2, "3R": 3}.get(mode, 0)) if mode in ("2R", "3R") else -1
    px, last = np.nan, min(len(c) - 1, i + 288)
    for j in range(i + 1, last + 1):
        if not np.isfinite(c[j]):
            px = c[j - 1]
            break
        if h[j] >= stop:
            px = max(stop, o[j])
            break
        if tgt > 0 and l[j] <= tgt:
            px = tgt
            break
        if mode == "ride4h" and up4[j] == 1:
            px = c[j]
            break
    if not np.isfinite(px):
        px = c[last]
    return ((pe - px) / pe - FEE) / risk


def run_coin(path):
    k = pd.read_parquet(path)
    k = k[~k.index.duplicated()].sort_index()
    if len(k) < 3000:
        return None
    k = k.reindex(pd.date_range(k.index[0], k.index[-1], freq="15min"))
    o, h, l, c = (k[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    dv = (k["quote_volume"].rolling(96 * 7, min_periods=96 * 3).mean() * 96).to_numpy()
    pumped = ((k["high"].rolling(288).max() / k["low"].rolling(576).min() - 1) >= 0.30).to_numpy() & (np.nan_to_num(dv) >= 5e6)
    s4 = states(tf_frame(k, 16))
    flip = ((s4["up"] == -1) & (s4["up"].shift() == 1)).astype(float)
    s4["bars_since_flip"] = flip[::-1].groupby(flip[::-1].cumsum()).cumcount()[::-1] * 0  # placeholder
    # bars since the last 4h down flip
    cnt, out = 10**6, []
    for v in flip.to_numpy():
        cnt = 0 if v else cnt + 1
        out.append(cnt)
    s4["since_flip"] = out
    s4["sar"] = np.nan
    from run import psar
    d4 = tf_frame(k, 16)
    s4["sar"], _ = psar(d4["high"].to_numpy(float), d4["low"].to_numpy(float))
    f4 = known_at_15m(s4, 16, k.index)
    up4, since4, sar4 = f4["up"].to_numpy(), f4["since_flip"].to_numpy(), f4["sar"].to_numpy()
    f = states(tf_frame(k, 1))
    up15 = f["up"].to_numpy()
    flip15 = np.r_[False, (up15[1:] == -1) & (up15[:-1] == 1)]
    mid, atr, hh = f["mid"].to_numpy(), f["atr"].to_numpy(), f["hh"].to_numpy()
    touched_mid = pd.Series((k["high"] >= f["mid"]).to_numpy()).rolling(8).max().to_numpy() > 0
    rng = np.random.default_rng(abs(hash(path.stem)) % (2**32))
    rows = []
    for N in (6, 18):
        win = pumped & (up4 == -1) & (since4 <= N) & np.isfinite(atr) & (atr > 0) & (c < sar4)
        for ename, ent in (("FAIL", win & flip15), ("FAIL_BNC", win & flip15 & touched_mid)):
            ii = np.flatnonzero(ent)
            pool = np.flatnonzero(win)
            rnd = np.sort(rng.choice(pool, min(len(ii), len(pool)), replace=False)) if len(ii) and len(pool) else []
            for kind, idx in (("sig", ii), ("rand", rnd)):
                for sname in ("tight", "4h"):
                    for mode in ("2R", "3R", "ride4h"):
                        busy = -1
                        for i in idx:
                            if i <= busy:
                                continue
                            stop = hh[i] + 0.3 * atr[i] if sname == "tight" else sar4[i]
                            r = sim(o, h, l, c, up4, i, stop, mode)
                            if r is None:
                                continue
                            busy = i + 16           # one entry per coin per 4h
                            rows.append((path.stem, N, ename, kind, sname, mode, k.index[i], r))
    return pd.DataFrame(rows, columns=["sym", "N", "entry", "kind", "stop", "exit", "t", "R"]) if rows else None


if __name__ == "__main__":
    with Pool() as p:
        df = pd.concat([x for x in p.map(run_coin, sorted(K15.glob("*.parquet")), chunksize=2) if x is not None])
    res = Path(__file__).resolve().parent / "results"
    df.to_parquet(res / "htf_first.parquet")
    rows = []
    for key, g in df.groupby(["N", "entry", "stop", "exit", "kind"]):
        for per, m in (("IS", g.t < IS_END), ("OOS", g.t >= IS_END)):
            r = g.R[m]
            if len(r) < 15:
                continue
            w, lo = r[r > 0].sum(), -r[r < 0].sum()
            rows.append((*key, per, len(r), round(w / lo, 2), round(r.mean(), 3), round((r > 0).mean(), 2),
                         round(r.mean() / r.std() * np.sqrt(len(r)), 2)))
    t = pd.DataFrame(rows, columns=["N", "entry", "stop", "exit", "kind", "per", "n", "pf", "avgR", "win", "t"])
    t.to_csv(res / "htf_first_summary.csv", index=False)
    pd.set_option("display.width", 250, "display.max_rows", 300)
    print(t.pivot_table(index=["N", "entry", "stop", "exit"], columns=["kind", "per"], values=["n", "pf", "t"], aggfunc="first").to_string())
