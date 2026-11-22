"""Distribution Short traded the way a teacher can (22 Nov 2026). PRE-REGISTERED.

Live alerts fire at the daily close (00:00 UTC = 11am Sydney, in class), carry wide
stops (e.g. MET +40%) and a 3.5 ATR trailing stop to move by hand for up to 60 days.
He found them too hard to follow. Question: does DS keep its edge when he
(a) enters later and (b) sets stop + take profit once and never touches it?

Variants (9, fixed before running):
  entry delay D: 0h (daily close, today), 6h (06:00 UTC = 5pm Sydney), 20h (20:00 UTC = 7am Sydney next day)
  exits X:
    TRAIL   live rules: DS stop, 3.5 ATR(daily) trailing stop, TP 2R, 60 days
    SET     DS stop, TP 2R, 30 days, no trail (place once, never touch)
    SET15   stop = min(DS stop, entry +15%), TP 2R, 30 days, no trail (size near $150 margin)
Entry price = close of the 1h bar at signal + D. Taker 0.36% round trip, funding
included (core.sim). R = (net - cost) / stop%. IS 2023-01..2025-07, OOS after.
Baseline: same rules on random days for the same coins (1 per signal).
"""
import json, sys
from multiprocessing import Pool
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "my_edge"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import core as C
from skills import new_setups as NS

NAN = float("nan")
COST = C.COSTS["taker"]
PIONEX = {s.replace("-USD", "") for s in json.loads(
    (Path(__file__).resolve().parents[2] / "data/pionex_perps.json").read_text())["symbols"]}
BTC_D = None


def on_pionex(sym):
    b = sym[:-4]
    for p in ("1000000", "1000", "1M"):
        if b.startswith(p) and b[len(p):] in PIONEX:
            return True
    return b in PIONEX


def init():
    global BTC_D
    BTC_D = C.load("BTCUSDT")["close"].resample("1D").last()


def per(t):
    return "IS" if C.IS_START <= t < C.IS_END else ("OOS" if t >= C.IS_END else None)


def run(sym):
    k = C.load(sym)
    if k is None or len(k) < 24 * 260:
        return []
    o, h, l, c, fu = (k[x].to_numpy() for x in ("open", "high", "low", "close", "fund"))
    dead = bool(k["dead"].iloc[0])
    d = k[["open", "high", "low", "close", "volume", "quote_volume"]].resample("1D").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "quote_volume": "sum"})
    d = d[k["close"].resample("1D").count() == 24]
    try:
        det = NS.detect(d, BTC_D)
    except Exception:
        return []
    sig = np.flatnonzero(det["label"].to_numpy() == NS.DIST)
    rng = np.random.default_rng(abs(hash(sym)) % 2**32)
    elig = np.flatnonzero(np.isfinite(det["stop"].to_numpy()) & np.isfinite(det["atr"].to_numpy()))
    rows = []
    for kind, idxs in (("sig", sig), ("rand", rng.choice(elig, size=min(len(sig), len(elig)), replace=False) if len(sig) and len(elig) else [])):
        for D in (0, 6, 20):
            for X in ("TRAIL", "SET", "SET15"):
                busy = -1
                for di in sorted(idxs):
                    t_close = d.index[di] + pd.Timedelta(days=1)          # daily close time
                    p = per(t_close)
                    if p is None:
                        continue
                    try:
                        i0 = k.index.get_loc(t_close - pd.Timedelta(hours=1)) + D
                    except KeyError:
                        continue
                    if i0 <= busy or i0 >= len(c) - 2:
                        continue
                    e = c[i0]
                    st = det["stop"].iat[di]
                    if not (np.isfinite(st) and st > e):
                        continue
                    if X == "SET15":
                        st = min(st, e * 1.15)
                    sp = (st - e) / e
                    if sp < 0.01 or sp > 0.6:
                        continue
                    trail = 3.5 * det["atr"].iat[di] / d["close"].iat[di] if X == "TRAIL" else NAN
                    mb = 60 * 24 if X == "TRAIL" else 30 * 24
                    j, net, sp2, code, gross = C.sim(o, h, l, c, fu, int(i0), -1, float(st), 0.0, trail, 2.0, mb, 0.0, dead)
                    if code == 5:
                        continue
                    busy = j
                    rows.append((sym, on_pionex(sym), kind, D, X, t_close, p, (net - COST) / sp2, sp2))
    return rows


if __name__ == "__main__":
    syms = C.universe_symbols()
    with Pool(initializer=init) as pool:
        rows = [r for part in pool.map(run, syms, chunksize=4) for r in part]
    df = pd.DataFrame(rows, columns=["sym", "pionex", "kind", "D", "X", "t", "per", "R", "stop_pct"])
    out = Path(__file__).resolve().parent
    df.to_parquet(out / "trades.parquet")
    res = []
    for (kind, D, X, p), g in df[df.pionex].groupby(["kind", "D", "X", "per"]):
        r = g.R
        w, lo = r[r > 0].sum(), -r[r < 0].sum()
        res.append(dict(kind=kind, delay_h=D, exit=X, per=p, n=len(r), pf=round(w / lo, 2), avgR=round(r.mean(), 3),
                        win=round((r > 0).mean(), 2), t=round(r.mean() / r.std() * np.sqrt(len(r)), 2),
                        med_stop=round(g.stop_pct.median() * 100, 1)))
    t = pd.DataFrame(res)
    t.to_csv(out / "summary.csv", index=False)
    pd.set_option("display.width", 200, "display.max_rows", 100)
    print(t.to_string(index=False))
