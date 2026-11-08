"""Structural / forced trading tests (funding extremes, OI flush). See ../PREREG.md."""
import json, sys, zlib
from multiprocessing import Pool
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, "/home/claude/quant-crypto-system/research/my_edge")
sys.path.insert(0, "/home/claude/quant-crypto-system")
import core as C
from skills import new_setups as NS

BASE = Path("/tmp/claude-0/-home-claude/f9afb357-b96a-5c99-93e3-0ac2bb39e920/scratchpad/edge2/forced")
OI = BASE / "oi"
NAN = float("nan")
NREP = 20
PIONEX = {s.replace("-USD", "") for s in json.loads(Path("/home/claude/quant-crypto-system/data/pionex_perps.json").read_text())["symbols"]}


def on_pionex(sym):
    b = sym[:-4]
    for p in ("1000000", "1000", "1M"):
        if b.startswith(p) and b[len(p):] in PIONEX:
            return True
    return b in PIONEX or (b == "MATIC" and "POL" in PIONEX) or (b == "RNDR" and "RENDER" in PIONEX)


def btc_daily():
    k = C.load("BTCUSDT")
    d = k["close"].resample("1D").last()
    return d


BTC_D = None


def period(t):
    if C.IS_START <= t < C.IS_END:
        return "IS"
    if C.IS_END <= t < C.DATA_END:
        return "OOS"
    return None


def funding8(sym, idx):
    fp = C.BUM / "fund" / f"{sym}.parquet"
    out = np.full(len(idx), NAN)
    if not fp.exists():
        return out
    f = pd.read_parquet(fp)["rate"]
    f.index = pd.DatetimeIndex(f.index).round("h")
    f = f.groupby(level=0).sum()
    iv = f.index.to_series().diff().dt.total_seconds().div(3600).clip(1, 8).fillna(8).to_numpy()
    r8 = f.to_numpy() * 8.0 / iv
    pos = idx.get_indexer(f.index - pd.Timedelta(hours=1))   # print at hh closes bar opening hh-1
    m = pos >= 0
    out[pos[m]] = r8[m]
    return out


def signals(sym, k, btc_up_h):
    o, h, l, c = (k[x].to_numpy() for x in ("open", "high", "low", "close"))
    atr = C.atr(k["high"], k["low"], k["close"], 14).to_numpy()
    idx = k.index
    fr = funding8(sym, idx)
    sig = {}
    stops = {}
    # V1
    sig["V1"] = np.nan_to_num(fr, nan=0) >= 0.0010
    stops["V1"] = c + 3 * atr
    # V2: 3 consecutive prints >= 0.05%, fire on the 3rd
    pp = np.flatnonzero(np.isfinite(fr))
    v2 = np.zeros(len(c), bool)
    streak = 0
    for p in pp:
        streak = streak + 1 if fr[p] >= 0.0005 else 0
        if streak == 3:
            v2[p] = True
    sig["V2"], stops["V2"] = v2, c + 3 * atr
    sig["V3"] = (np.nan_to_num(fr, nan=0) <= -0.0010) & btc_up_h
    stops["V3"] = c - 3 * atr
    # OI
    flush = np.zeros(len(c), bool)
    has_oi = False
    op = OI / f"{sym}.parquet"
    if op.exists():
        oi = pd.read_parquet(op)["oiv"]
        oi = oi[~oi.index.duplicated()]
        # oi notional at bar close; use contracts-independent notional? notional moves with price,
        # so use contracts (oi) for the flush condition
        oic = pd.read_parquet(op)["oi"]
        oic = oic[~oic.index.duplicated()]
        ob = oic.reindex(idx + pd.Timedelta(hours=1)).to_numpy()
        has_oi = np.isfinite(ob).sum() > 24 * 30
        ob_l = np.roll(ob, 24); ob_l[:24] = NAN
        c_l = np.roll(c, 24); c_l[:24] = NAN
        with np.errstate(invalid="ignore", divide="ignore"):
            cond = (c / c_l - 1 <= -0.10) & (ob / ob_l - 1 <= -0.15)
        cond = np.nan_to_num(cond, nan=0).astype(bool)
        prior = pd.Series(cond).shift(1, fill_value=False).rolling(24, min_periods=1).max().astype(bool).to_numpy()
        flush = cond
        v4 = cond & ~prior
    else:
        v4 = np.zeros(len(c), bool)
    lo24 = pd.Series(l).rolling(24).min().to_numpy()
    sig["V4"] = sig["V5"] = v4
    stops["V4"] = stops["V5"] = lo24 - 0.5 * atr
    return sig, stops, flush, has_oi, atr, lo24, fr


SPEC = {"V1": (-1, 72), "V2": (-1, 72), "V3": (1, 72), "V4": (1, 72), "V5": (1, 24)}


def stop_at(name, i, c, atr, lo24):
    if name in ("V1", "V2"):
        return c[i] + 3 * atr[i]
    if name == "V3":
        return c[i] - 3 * atr[i]
    return lo24[i] - 0.5 * atr[i]


def run_coin(sym):
    k = C.load(sym)
    if k is None:
        return []
    k = k[k.index >= pd.Timestamp("2022-09-01")]
    if len(k) < 24 * 60:
        return []
    idx = k.index
    tc = idx + pd.Timedelta(hours=1)
    bd = BTC_D
    up = (bd > bd.rolling(50).mean()).shift(1)          # yesterday's close vs SMA50, known today
    btc_up_h = up.reindex(idx.normalize()).fillna(False).to_numpy().astype(bool)
    sig, stops, flush, has_oi, atr, lo24, fr = signals(sym, k, btc_up_h)
    o, h, l, c, fu = (k[x].to_numpy() for x in ("open", "high", "low", "close", "fund"))
    dead = bool(k["dead"].iloc[0])
    liquid = np.nan_to_num(k["dvol30"].to_numpy()) >= C.MIN_DVOL
    per = np.array([period(t) or "" for t in tc])
    rng = np.random.default_rng(zlib.crc32(sym.encode()))
    pion = on_pionex(sym)
    rows = []
    for name, (side, mb) in SPEC.items():
        if name in ("V4", "V5") and not has_oi:
            continue
        ii = np.flatnonzero(sig[name] & liquid & (per != ""))
        busy = -1
        taken = []
        for i in ii:
            if i <= busy:
                continue
            st = stops[name][i]
            sp = (c[i] - st) * side / c[i]
            if not np.isfinite(sp) or sp < C.MIN_STOP or sp > C.MAX_STOP:
                continue
            j, net, sp2, code, gross = C.sim(o, h, l, c, fu, i, side, st, 0.0, NAN, 2.0, mb, 0.0, dead)
            if code == 5:
                continue
            busy = j
            taken.append(i)
            rows.append(dict(v=name, kind="sig", rep=-1, sym=sym, t=tc[i], per=per[i], net=net, sp=sp2, code=code, pionex=pion))
        # random baseline: same coin, same period, liquid bars
        for pr in ("IS", "OOS"):
            cnt = sum(1 for i in taken if per[i] == pr)
            if cnt == 0:
                continue
            pool = np.flatnonzero(liquid & (per == pr) & np.isfinite(atr))
            if len(pool) == 0:
                continue
            for rep in range(NREP):
                got = 0
                tries = 0
                while got < cnt and tries < cnt * 20:
                    tries += 1
                    i = int(rng.choice(pool))
                    st = stop_at(name, i, c, atr, lo24)
                    sp = (c[i] - st) * side / c[i]
                    if not np.isfinite(sp) or sp < C.MIN_STOP or sp > C.MAX_STOP:
                        continue
                    j, net, sp2, code, gross = C.sim(o, h, l, c, fu, i, side, st, 0.0, NAN, 2.0, mb, 0.0, dead)
                    if code == 5:
                        continue
                    got += 1
                    rows.append(dict(v=name, kind="rand", rep=rep, sym=sym, t=tc[i], per=pr, net=net, sp=sp2, code=code, pionex=pion))
    # ── V6: Distribution Short on daily bars, flush flag ──
    if has_oi:
        d = k[["open", "high", "low", "close", "volume"]].resample("1D").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        cnt = k["close"].resample("1D").count()
        d = d[cnt == 24]
        fd = k["fund"].resample("1D").sum().reindex(d.index).fillna(0).to_numpy()
        det = NS.detect(d, BTC_D)
        fl = pd.Series(flush.astype(float), index=tc).rolling("72h").max()
        do, dh, dl, dc = (d[x].to_numpy() for x in ("open", "high", "low", "close"))
        dd = k["dead"].iloc[0]
        busy = -1
        for i in np.flatnonzero(det["label"].to_numpy() == NS.DIST):
            t = d.index[i] + pd.Timedelta(days=1)
            pr = period(t)
            if pr is None or i <= busy:
                continue
            st = det["stop"].iat[i]
            a = det["atr"].iat[i]
            trail = 3.5 * a / dc[i]
            j, net, sp, code, gross = C.sim(do, dh, dl, dc, fd, i, -1, st, 0.0, trail, 2.0, 60, 0.0, bool(dd))
            if code == 5:
                continue
            busy = j
            f = fl.asof(t) if t >= fl.index[0] else 0.0
            rows.append(dict(v="V6", kind="flush" if f and f > 0 else "noflush", rep=-1, sym=sym, t=t, per=pr,
                             net=net, sp=sp, code=code, pionex=pion))
    return rows


def init():
    global BTC_D
    BTC_D = btc_daily()


if __name__ == "__main__":
    syms = C.universe_symbols()
    with Pool(2, initializer=init) as p:
        out = p.map(run_coin, syms, chunksize=4)
    df = pd.DataFrame([r for rs in out for r in rs])
    df.to_parquet(BASE / "trades.parquet")
    print(len(df), df.groupby(["v", "kind"]).size())
