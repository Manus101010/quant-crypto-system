"""New perp listings drift down. See PREREG.txt. Run: python run.py"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/claude/quant-crypto-system/research/my_edge")
import core as C  # noqa: E402

OUT = Path(__file__).resolve().parent
NAN = float("nan")
DS_START = pd.Timestamp("2021-06-01")
RENAMES = {"1000BTTCUSDT", "AUSDT", "RENDERUSDT", "POLUSDT", "GUSDT", "SUSDT", "VICUSDT",
           "SKYUSDT", "1000LUNCUSDT"}
TRADFI = set("""XAU XAG TSLA XPT XPD HOOD INTC MSTR AMZN CRCL COIN PLTR COPPER EWY EWJ PAYP GOOGL META
XAUT NVDA CL BZ NATGAS QQQ AAPL SPY TSM MU SNDK AVGO BABA MSFT AMD QCOM USAR CSCO LITE HD ORCL DIS
UBER SOXL MRVL BRKB WMT V FLNC CRWV JPM DRAM RKLB CBRS SPCX OPENAI WDC NBIS BE COHR ARM QNTX ASTS
NOK NVO LLY EWT HYUNDAI SKHYNIX SAMSUNG ANTHROPIC DELL CRM IBM NOW IREN ONDS AXTI AAOI CRDO HPE AMAT
IWM BX CRWD EBAY NFLX URNM COST HIMS GME ZM DKNG RIVN XLE EWZ STXX ADBE BMNR GLW UVXY ASML ALAB SMCI
CIEN LRCX KLAC KORU SONY TQQQ SQQQ MVLL STRC KSTR CAT FLEX TTWO TXN TER SNXX BNC XBI FWDI INTW GEV
APP SNOW VRT SKHY SOXS MUU TZA MINIMAX ZHIPU SHAZ PANW SOFI HK1810 HK0700 TENCENT POPMART TBT TMF
BITO SMH GS PYPL GIGADEV RDDT KO KUAISHOU MEITUAN CSOPSAMSUNG2L CSOPSKHYNIX2L ZHONGJI NAVER KODEX200
LGELECTRONICS HANMI SAMSUNGEM VST NET SHOP LYTE GDX CXMT UNITREE RAM SKDD MRNA SKUU DJT IONQ MRK TEM
PDD MARA HK0625 ZS MDB NVDL GTLB TSLL TEAM DDOG GPRO BYD HK0992 ANET CYPH PATH HUT AGPU APLD AMC USDBRL
OURA XOM OKLO CVNA RUM TWST BWET UNH MP SECZ NKE ACN CRML BBX BOT DATAIP""".split()) | C.STOCKS
PIONEX = {s.replace("-USD", "") for s in json.loads(
    Path("/home/claude/quant-crypto-system/data/pionex_perps.json").read_text())["symbols"]}
VARIANTS = ["V1", "V2", "V3", "V4", "V5", "V6"]


def base(sym):
    b = sym[:-4]
    for p in ("1000000", "1000"):
        if b.startswith(p) and len(b) > len(p):
            return b[len(p):]
    return b


def in_pionex(sym):
    b = sym[:-4]
    return b in PIONEX or base(sym) in PIONEX


def spans():
    s = pd.read_csv(OUT / "symbol_span.csv", parse_dates=["first", "last"])
    s = s[s.sym.str.endswith("USDT")]
    s["crypto"] = ~s.sym.str[:-4].isin(TRADFI) & ~s.sym.map(base).isin(TRADFI)
    # Pionex membership overrides the manual TradFi list (Pionex list is crypto only)
    s.loc[s.sym.map(in_pionex), "crypto"] = True
    s["pionex"] = s.sym.map(in_pionex)
    return s


def arrays(k):
    return tuple(k[x].to_numpy(np.float64) for x in ("open", "high", "low", "close", "fund"))


def run_trade(arr, i, stop, tgt_r, bars, dead):
    o, h, l, c, fu = arr
    j, net, sp, code, gross = C.sim(o, h, l, c, fu, int(i), -1, float(stop), 0.0, NAN, float(tgt_r), int(bars), 0.0, dead)
    return j, net, sp, code


EXIT = {"V1": (NAN, 720), "V2": (NAN, 720), "V3": (NAN, 336), "V4": (2.0, 720), "V5": (3.0, 720), "V6": (NAN, 720)}


def listing_events(sp):
    new = sp[(sp["first"] > DS_START + pd.Timedelta(days=1)) & sp.crypto & ~sp.sym.isin(RENAMES)].sort_values("first")
    rows = []
    for _, r in new.iterrows():
        k = C.load(r.sym)
        if k is None:
            # load() drops coins with < 40 days of data: keep them via raw reindex
            p = C.BUM / "k1h" / f"{r.sym}.parquet"
            k = pd.read_parquet(p)
            k = k[~k.index.duplicated()].sort_index()
            k = k.reindex(pd.date_range(k.index[0], k.index[-1], freq="1h"))
            k["fund"] = 0.0
            fp = C.BUM / "fund" / f"{r.sym}.parquet"
            if fp.exists():
                f = pd.read_parquet(fp)["rate"]
                f.index = pd.DatetimeIndex(f.index).floor("h")
                f = f.groupby(level=0).sum()
                k["fund"] = f.reindex(k.index + pd.Timedelta(hours=1)).fillna(0.0).to_numpy()
            dead = True
        else:
            dead = bool(k["dead"].iloc[0])
        arr = arrays(k)
        o, h, l, c, fu = arr
        idx = k.index
        tclose = idx + pd.Timedelta(hours=1)
        age_h = np.arange(len(k)) + 1                      # hours elapsed at bar close
        daily = (tclose.hour == 0)
        q24 = np.nansum(k["quote_volume"].to_numpy()[:24])
        low24 = np.nanmin(l[:24])
        runhi = np.fmax.accumulate(np.nan_to_num(h, nan=-np.inf))
        ev = dict(sym=r.sym, listed=r["first"], pionex=bool(r.pionex), q24=q24, dead=dead)
        ent = {}
        for N, name in ((1, "D1"), (3, "D3"), (7, "D7")):
            cand = np.flatnonzero(daily & (age_h >= N * 24) & np.isfinite(c))
            if len(cand):
                ent[name] = cand[0]
        cand = np.flatnonzero(daily & (age_h >= 24) & (age_h <= 720) & np.isfinite(c) & (c < low24))
        if len(cand):
            ent["BRK"] = cand[0]
        for v, e in (("V1", "D1"), ("V2", "D3"), ("V3", "D7"), ("V4", "D3"), ("V5", "BRK"), ("V6", "D3")):
            if e not in ent:
                continue
            i = ent[e]
            entry = c[i]
            raw = runhi[i] * 1.02
            stop = min(max(raw, entry * 1.03), entry * 1.25)
            tgt_r, bars = EXIT[v]
            j, net, spct, code = run_trade(arr, i, stop, tgt_r, bars, dead)
            if code == 5:
                continue
            rows.append(dict(ev, variant=v, t=tclose[i], exit_t=tclose[min(j, len(idx) - 1)], net0=net,
                             stop_pct=spct, capped=raw > entry * 1.25, code=code, tgt_r=tgt_r, bars=bars,
                             raw_stop_pct=raw / entry - 1))
    df = pd.DataFrame(rows)
    # V6 filter: q24 > median of the previous 30 listings (chronological, all Binance)
    ev = df.drop_duplicates("sym")[["sym", "listed", "q24"]].sort_values("listed")
    med = ev["q24"].shift(1).rolling(30, min_periods=10).median()
    keep = set(ev.loc[ev["q24"] > med, "sym"])
    df = df[(df.variant != "V6") | df.sym.isin(keep)]
    return df


def controls(df, sp, reps=100, seed=11):
    """Same timestamp, same stop %, same exits: (a) BTCUSDT, (b) random seasoned coin."""
    rng = np.random.default_rng(seed)
    pool = sp[sp.crypto & (sp.sym != "BTCUSDT")].reset_index(drop=True)
    draws = []  # (trade_idx, rep, sym)
    for ti, r in df.iterrows():
        age = (r.t - pool["first"]).dt.days
        ok = pool[(age >= 182) & (age <= 730) & (pool["last"] > r.t + pd.Timedelta(days=1))].sym.to_numpy()
        if not len(ok):
            continue
        for rep, s in enumerate(rng.choice(ok, size=reps, replace=True)):
            draws.append((ti, rep, s))
    dr = pd.DataFrame(draws, columns=["ti", "rep", "sym"])
    out = []
    jobs = [("BTCUSDT", pd.DataFrame({"ti": df.index, "rep": -1}))] + list(dr.groupby("sym"))
    for s, g in jobs:
        k = C.load(s)
        if k is None:
            continue
        arr = arrays(k)
        dead = bool(k["dead"].iloc[0])
        pos = k.index.get_indexer(df.loc[g.ti, "t"] - pd.Timedelta(hours=1))
        for (ti, rep), i in zip(g[["ti", "rep"]].itertuples(index=False), pos):
            if i < 0 or not np.isfinite(arr[3][i]):
                continue
            r = df.loc[ti]
            entry = arr[3][i]
            j, net, spct, code = run_trade(arr, i, entry * (1 + r.stop_pct), r.tgt_r, r.bars, dead)
            if code == 5:
                continue
            out.append((ti, rep, s, net, spct))
    return pd.DataFrame(out, columns=["ti", "rep", "sym", "net0", "stop_pct"])


if __name__ == "__main__":
    sp = spans()
    df = listing_events(sp).reset_index(drop=True)
    df.to_parquet(OUT / "trades.parquet")
    print("trades", len(df), df.groupby("variant").size().to_dict())
    ctl = controls(df, sp)
    ctl.to_parquet(OUT / "controls.parquet")
    print("controls", len(ctl))
