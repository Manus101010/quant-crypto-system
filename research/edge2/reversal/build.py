"""Stage 1: per coin, per day (entry 00:00 UTC) features + outcomes for all exit specs.
Ranking uses bars closed by 00:00 (bar i = 23:00 bar, its close = entry price ~ 00:00 open)."""
import sys, json
from multiprocessing import Pool
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/quant-crypto-system/research/my_edge")
import core as C
OUT = Path(__file__).resolve().parent
NAN = float("nan")
PIONEX = {s.replace("-USD", "") for s in json.loads((C.ROOT / "data/pionex_perps.json").read_text())["symbols"]}

def base(sym):
    b = sym[:-4]
    for p in ("1000000", "1000", "1M"):
        if b.startswith(p) and b[len(p):]:
            return b[len(p):]
    return b

def run(sym):
    try:
        k = C.load(sym)
    except Exception:
        return None
    if k is None:
        return None
    k = k[k.index >= pd.Timestamp("2022-06-01")]
    if len(k) < 24 * 40:
        return None
    o, h, l, c, fu = (k[x].to_numpy() for x in ("open", "high", "low", "close", "fund"))
    dv = k["dvol30"].to_numpy(); age = k["age_h"].to_numpy()
    dead = bool(k["dead"].iloc[0])
    idx = np.flatnonzero(k.index.hour == 23)
    rows = []
    for i in idx:
        if i < 24 or age[i] < 720 or not np.isfinite(c[i]) or not np.isfinite(c[i - 24]) or not np.isfinite(dv[i]) or dv[i] < 5e6:
            continue
        r24 = c[i] / c[i - 24] - 1
        hi24 = np.nanmax(h[i - 23:i + 1]); lo24 = np.nanmin(l[i - 23:i + 1])
        f24 = np.nansum(fu[i - 23:i + 1])
        ci = c[i]
        out = [sym, k.index[i] + pd.Timedelta(hours=1), r24, f24, dv[i], ci]
        # A short 24h stop 8%
        j, net, sp, code, g = C.sim(o, h, l, c, fu, int(i), -1, ci * 1.08, 0.0, NAN, NAN, 24, 0.0, dead)
        out += [net if code != 5 else NAN, sp, j]
        # B short 72h stop hi24*1.01 clipped [3%,20%]
        s = min(max(hi24 * 1.01 / ci - 1, 0.03), 0.20)
        j, net, sp, code, g = C.sim(o, h, l, c, fu, int(i), -1, ci * (1 + s), 0.0, NAN, NAN, 72, 0.0, dead)
        out += [net if code != 5 else NAN, sp, j]
        # Cl long 24h stop 8%
        j, net, sp, code, g = C.sim(o, h, l, c, fu, int(i), 1, ci * 0.92, 0.0, NAN, NAN, 24, 0.0, dead)
        out += [net if code != 5 else NAN, sp, j]
        # raw 24h: price return and funding (long perspective), no stop
        e = i + 24
        if e < len(c) and np.isfinite(c[e]):
            out += [c[e] / ci - 1, np.nansum(fu[i + 1:e + 1])]
        elif e >= len(c) and dead:
            last = len(c) - 1
            out += [c[last] / ci - 1, np.nansum(fu[i + 1:])]
        else:
            out += [NAN, NAN]
        rows.append(out)
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["sym", "t", "r24", "f24", "dvol", "px", "A_net", "A_sp", "A_j",
                                     "B_net", "B_sp", "B_j", "L_net", "L_sp", "L_j", "raw", "rawf"])
    df["pionex"] = base(sym) in PIONEX
    df["dead"] = dead
    df["A_j"] = k.index[df["A_j"].astype(int)] + pd.Timedelta(hours=1)
    df["B_j"] = k.index[df["B_j"].astype(int)] + pd.Timedelta(hours=1)
    df["L_j"] = k.index[df["L_j"].astype(int)] + pd.Timedelta(hours=1)
    return df

if __name__ == "__main__":
    syms = sorted(p.stem for p in (C.BUM / "k1h").glob("*USDT.parquet") if p.stem[:-4] not in C.STOCKS)
    uni = set(C.universe_symbols())
    with Pool(2) as p:
        parts = [x for x in p.map(run, syms, chunksize=8) if x is not None]
    df = pd.concat(parts, ignore_index=True)
    df["in_uni"] = df.sym.isin(uni)
    df.to_parquet(OUT / "panel.parquet")
    print(df.shape, df.pionex.mean(), df.groupby("pionex").sym.nunique())
