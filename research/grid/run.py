"""
Grid backtest sweep: which Bybit futures grid rules (if any) pass the edge gate.

Data: research/grid/cache/*.parquet (MEXC USDT-perp 5m + funding; run
research/grid/data.py first). Signals are evaluated once per hour on CLOSED 1h
bars (features at the hour labelled t are used from the 5m bar opening at
t+1h), one bot per coin at a time, entry at that 5m open, simulated on 5m OHLC
with research/grid/sim.py (maker 0.02% fills, taker 0.055% + 0.05% slip on
open/close/stop, MEXC funding, isolated liquidation).

Strategies (filter -> grid mode):
  neutral_*   range regime (ADX, BB-width percentile, Hurst) -> neutral grid
              centred on price, stops just beyond both edges
  short_trend close < 4h EMA50 and BTC < its 4h EMA50 -> short grid
  long_trend  mirror -> long grid
  short_spike close > EMA20(1h) + X*ATR(1h) (overextended pump) -> short grid
  *_always    no filter (control: is the filter worth anything?)
Range = width_k x ATR(1h) wide. Neutral: centred. Directional: price sits at
1/3 of the range from the stop side (short: 1/3 below the top), so the grid
opens 2/3 of its position at start and has 2/3 of the range to work in.
Directional grids also close when price leaves the range on the profitable
side (they are flat there, nothing left to earn).
Rules: $50 margin, a straight run through the stop must lose <= $12.50 (25%)
and liquidation must be >= 2x the stop distance, else rejected pre-trade.

Run:  python research/grid/run.py
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.grid.sim import (  # noqa: E402
    MAKER_FEE, MMR, MODES, OK, REJ_LIQ, REJ_LOSS, REJ_STEP, SKIP, SLIPPAGE, TAKER_FEE,
    REASONS, run_batch,
)
from utils.logger import get_logger  # noqa: E402

log = get_logger(__name__)
HERE = Path(__file__).resolve().parent
CACHE, RESULTS = HERE / "cache", HERE / "results"
MARGIN, R_USD = 50.0, 12.5
STOP_BUF = 0.002                     # stop 0.2% beyond the range edge
GRIDS = (20, 50, 100, 200)
LEVS = (3, 5, 10)
WIDTHS = (4, 8, 16, 32)              # range width in 1h ATRs
HOLDS = (24, 72, 168)                # hours
STRATS = {
    "neutral_adx":    ("neutral", "adx"),
    "neutral_bbw":    ("neutral", "bbw"),
    "neutral_hurst":  ("neutral", "hurst"),
    "neutral_always": ("neutral", "always"),
    "short_trend":    ("short", "trend_dn"),
    "long_trend":     ("long", "trend_up"),
    "short_spike3":   ("short", "spike3"),
    "short_spike5":   ("short", "spike5"),
    "short_always":   ("short", "always"),
    "long_always":    ("long", "always"),
}


# ── features (1h, no look-ahead) ──────────────────────────────────────────────
def _atr(h: pd.DataFrame, n: int = 14) -> pd.Series:
    c = h["close"]
    tr = pd.concat([h["high"] - h["low"], (h["high"] - c.shift()).abs(),
                    (h["low"] - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _adx(h: pd.DataFrame, n: int = 14) -> pd.Series:
    up, dn = h["high"].diff(), -h["low"].diff()
    pdm = up.where((up > dn) & (up > 0), 0.0)
    mdm = dn.where((dn > up) & (dn > 0), 0.0)
    atr = _atr(h, n)
    pdi = 100 * pdm.ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * mdm.ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def features(m5: pd.DataFrame, btc_trend: pd.Series | None) -> pd.DataFrame:
    h = m5[["open", "high", "low", "close"]].resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    c = h["close"]
    f = pd.DataFrame(index=h.index)
    f["close"] = c
    f["atr"] = _atr(h)
    f["adx"] = _adx(h)
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    bbw = 4 * sd / mid
    f["bbw_pct"] = bbw.rolling(720, min_periods=240).rank(pct=True)
    r1 = np.log(c).diff()
    r8 = np.log(c).diff(8)
    f["hurst"] = np.log(r8.rolling(168).std() / r1.rolling(168).std()) / np.log(8)
    ema4h = c.resample("4h").last().ewm(span=50, adjust=False).mean()
    # a 4h bar labelled T closes at T+4h: only use it from then on
    ema4h.index = ema4h.index + pd.Timedelta(hours=3)
    f["ema4h"] = ema4h.reindex(f.index, method="ffill")
    f["ema20"] = c.ewm(span=20, adjust=False).mean()
    f["ext"] = (c - f["ema20"]) / f["atr"]
    if btc_trend is not None:
        f["btc_up"] = btc_trend.reindex(f.index, method="ffill")
    else:
        f["btc_up"] = c > f["ema4h"]
    return f


def signal(f: pd.DataFrame, kind: str) -> pd.Series:
    ok = f["atr"].notna() & f["ema4h"].notna() & (f.index >= f.index[0] + pd.Timedelta(days=10))
    if kind == "always":
        s = ok
    elif kind == "adx":
        s = f["adx"] < 20
    elif kind == "bbw":
        s = f["bbw_pct"] < 0.3
    elif kind == "hurst":
        s = f["hurst"] < 0.45
    elif kind == "trend_dn":
        s = (f["close"] < f["ema4h"]) & (~f["btc_up"].astype(bool))
    elif kind == "trend_up":
        s = (f["close"] > f["ema4h"]) & (f["btc_up"].astype(bool))
    elif kind.startswith("spike"):
        s = f["ext"] > float(kind[5:])
    else:
        raise ValueError(kind)
    return (s & ok).fillna(False)


# ── sweep ────────────────────────────────────────────────────────────────────
def load() -> tuple[dict, dict]:
    uni = {x["base"]: x for x in json.loads((CACHE / "universe.json").read_text())}
    coins = {}
    for p in sorted(CACHE.glob("*.parquet")):
        if p.stem.startswith(("okx1m_", "trades")):
            continue
        df = pd.read_parquet(p)
        if len(df) >= 20_000:
            coins[p.stem] = df
    return coins, uni


def prepare(coins: dict) -> dict:
    btc = coins["BTC"]["close"].resample("1h").last().dropna()
    b4 = btc.resample("4h").last()
    e = b4.ewm(span=50, adjust=False).mean()
    up = (b4 > e)
    up.index = up.index + pd.Timedelta(hours=3)
    prep = {}
    for sym, df in coins.items():
        f = features(df, up)
        arr = tuple(np.ascontiguousarray(df[k].to_numpy(np.float64))
                    for k in ("open", "high", "low", "close", "funding"))
        sig = {k: signal(f, k) for k in {v[1] for v in STRATS.values()}}
        prep[sym] = {"f": f, "arr": arr, "sig": sig, "idx": df.index}
    return prep


def entries(p: dict, kind: str, mode: str, width: float) -> tuple[np.ndarray, ...]:
    f, idx = p["f"], p["idx"]
    t = f.index[p["sig"][kind].to_numpy()]
    pos = idx.searchsorted(t + pd.Timedelta(hours=1))
    keep = pos < len(idx) - 1
    pos, t = pos[keep], t[keep]
    o = p["arr"][0][pos]
    w = width * f["atr"].reindex(t).to_numpy()
    if mode == "neutral":
        lo, hi = o - w / 2, o + w / 2
    elif mode == "short":
        lo, hi = o - 2 * w / 3, o + w / 3
    else:
        lo, hi = o - w / 3, o + 2 * w / 3
    good = np.isfinite(lo) & (lo > 0)
    return pos[good].astype(np.int64), lo[good], hi[good], t[good]


def _trades_for(prep: dict, uni: dict, cfg: tuple, ent_cache: dict) -> pd.DataFrame:
    strat, n, lev, width, hold = cfg
    mode, kind = STRATS[strat]
    rows = []
    for sym, p in prep.items():
        key = (sym, kind, mode, width)
        if key not in ent_cache:
            ent_cache[key] = entries(p, kind, mode, width)
        pos, lo, hi, t = ent_cache[key]
        if len(pos) == 0:
            continue
        o, h, l, c, fu = p["arr"]
        out = run_batch(o, h, l, c, fu, pos, lo, hi, n, MODES[mode], False, MARGIN,
                        float(lev), STOP_BUF, mode != "neutral", hold * 12, R_USD, 2.0,
                        MMR, MAKER_FEE, TAKER_FEE, SLIPPAGE, True)
        take = out[:, 0] != SKIP
        if not take.any():
            continue
        d = pd.DataFrame(out[take], columns=["status", "reason", "exit_bar", "pnl", "grid_profit",
                                             "fees", "funding", "mdd", "wc_loss", "fills"])
        d["entry_time"] = t[take]
        d["width_pct"] = ((hi - lo) / ((hi + lo) / 2))[take] * 100
        eb = d["exit_bar"].fillna(0).astype(int).clip(0, len(p["idx"]) - 1)
        d["exit_time"] = p["idx"][eb.to_numpy()]
        d["btc_up"] = p["f"]["btc_up"].reindex(d["entry_time"]).to_numpy()
        d["sym"] = sym
        d["tier"] = uni.get(sym, {}).get("tier", "top")
        rows.append(d)
    if not rows:
        return pd.DataFrame()
    d = pd.concat(rows, ignore_index=True)
    d["strat"], d["grids"], d["lev"], d["width"], d["hold"] = strat, n, lev, width, hold
    return d


def _worker(args: tuple) -> tuple[list[dict], list[pd.DataFrame]]:
    cfgs, mid = args
    coins, uni = load()
    prep = prepare(coins)
    ent_cache: dict = {}
    recs, keep = [], []
    t0 = time.time()
    for i, cfg in enumerate(cfgs):
        d = _trades_for(prep, uni, cfg, ent_cache)
        if d.empty:
            continue
        rec = summarise_one(d, mid, cfg)
        recs.append(rec)
        if rec.get("n", 0) >= 25 and (rec.get("pf") or 0) > 1:
            keep.append(d[d["status"] == OK])
        if (i + 1) % 40 == 0:
            log.info("  worker %d/%d configs (%.0fs)", i + 1, len(cfgs), time.time() - t0)
    return recs, keep


def run_all(mid: pd.Timestamp, procs: int = 2) -> tuple[pd.DataFrame, pd.DataFrame]:
    from multiprocessing import Pool
    configs = list(itertools.product(STRATS, GRIDS, LEVS, WIDTHS, HOLDS))
    log.info("grid sweep: %d configs, %d procs", len(configs), procs)
    chunks = [configs[i::procs] for i in range(procs)]
    with Pool(procs) as pool:
        res = pool.map(_worker, [(c, mid) for c in chunks])
    recs = [r for a, _ in res for r in a]
    keep = [k for _, b in res for k in b]
    return pd.DataFrame(recs), (pd.concat(keep, ignore_index=True) if keep else pd.DataFrame())


# ── evaluation ───────────────────────────────────────────────────────────────
def _pf(x: pd.Series) -> float:
    g, b = x[x > 0].sum(), -x[x < 0].sum()
    return float(g / b) if b > 0 else (float("inf") if g > 0 else float("nan"))


def summarise_one(g: pd.DataFrame, mid: pd.Timestamp, cfg: tuple) -> dict:
    keys = ["strat", "grids", "lev", "width", "hold"]
    t = g[g["status"] == OK]
    rec = dict(zip(keys, cfg))
    rec["signals"] = len(g)
    rec["rej_step"] = int((g["status"] == REJ_STEP).sum())
    rec["rej_loss"] = int((g["status"] == REJ_LOSS).sum())
    rec["rej_liq"] = int((g["status"] == REJ_LIQ).sum())
    rec["n"] = len(t)
    if len(t) == 0:
        return rec
    r = t["pnl"] / R_USD
    rs = t.sort_values("exit_time")["pnl"] / R_USD
    eq = rs.cumsum()
    a, b = t[t["entry_time"] < mid], t[t["entry_time"] >= mid]
    rec.update({
        "pf": _pf(t["pnl"]), "win": float((t["pnl"] > 0).mean()), "exp_r": float(r.mean()),
        "tot_r": float(r.sum()), "max_dd_r": float((eq.cummax() - eq).max()),
        "worst_r": float(r.min()), "avg_width_pct": float(t["width_pct"].mean()),
        "avg_hours": float((t["exit_time"] - t["entry_time"]).dt.total_seconds().mean() / 3600),
        "grid_r": float(t["grid_profit"].mean() / R_USD), "fees_r": float(t["fees"].mean() / R_USD),
        "fund_r": float(t["funding"].mean() / R_USD),
        "n1": len(a), "pf1": _pf(a["pnl"]), "r1": float(a["pnl"].sum() / R_USD),
        "exp1": float(a["pnl"].mean() / R_USD) if len(a) else np.nan,
        "n2": len(b), "pf2": _pf(b["pnl"]), "r2": float(b["pnl"].sum() / R_USD),
        "exp2": float(b["pnl"].mean() / R_USD) if len(b) else np.nan,
        "pf_btc_up": _pf(t.loc[t["btc_up"] == True, "pnl"]),     # noqa: E712
        "pf_btc_dn": _pf(t.loc[t["btc_up"] == False, "pnl"]),    # noqa: E712
        "pf_top": _pf(t.loc[t["tier"] == "top", "pnl"]),
        "pf_small": _pf(t.loc[t["tier"] == "small", "pnl"]),
        "coins_pos": int((t.groupby("sym")["pnl"].sum() > 0).sum()),
        "coins": int(t["sym"].nunique()),
    })
    for code, name in REASONS.items():
        rec[f"x_{name}"] = float((t["reason"] == code).mean())
    return rec


def mark_robust(s: pd.DataFrame) -> pd.DataFrame:
    keys = ["strat", "grids", "lev", "width", "hold"]
    s = s.copy()
    s["gate"] = (s["pf"] > 1) & (s["n"] >= 25) & (s["r1"] > 0) & (s["r2"] > 0)
    s["robust"] = False
    s["nb_pass"], s["nb_tot"] = np.nan, np.nan
    dims = {"grids": GRIDS, "lev": LEVS, "width": WIDTHS, "hold": HOLDS}
    gate = {tuple(r[k] for k in keys): bool(r["gate"]) for _, r in s.iterrows()}
    enough = {tuple(r[k] for k in keys) for _, r in s.iterrows() if r["n"] >= 25}
    for i, r in s[s["gate"]].iterrows():
        nb_pass, nb_tot = 0, 0
        for d, vals in dims.items():
            j = vals.index(r[d])
            for jj in (j - 1, j + 1):
                if 0 <= jj < len(vals):
                    kk = tuple(vals[jj] if kn == d else r[kn] for kn in keys)
                    if kk in enough:
                        nb_tot += 1
                        nb_pass += gate.get(kk, False)
        s.loc[i, "nb_pass"], s.loc[i, "nb_tot"] = nb_pass, nb_tot
        s.loc[i, "robust"] = nb_tot >= 2 and nb_pass == nb_tot
    return s


def walk_forward(s: pd.DataFrame) -> pd.DataFrame:
    """Per strategy: pick the best config on the FIRST half only (highest
    expectancy among n1 >= 25 and PF1 > 1), report it untouched on the second."""
    out = []
    for strat in STRATS:
        c = s[(s["strat"] == strat) & (s["n1"] >= 25) & (s["pf1"] > 1)]
        if c.empty:
            out.append({"strat": strat, "pick": None})
            continue
        r = c.loc[c["exp1"].idxmax()]
        out.append({"strat": strat, "pick": f"{r.grids}g/{r.lev}x/{r.width}ATR/{r.hold}h",
                    "is_n": int(r.n1), "is_pf": r.pf1, "is_exp_r": r.exp1,
                    "oos_n": int(r.n2), "oos_pf": r.pf2, "oos_exp_r": r.exp2, "oos_tot_r": r.r2})
    return pd.DataFrame(out)


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    btc = pd.read_parquet(CACHE / "BTC.parquet")
    lo = btc.index[0] + pd.Timedelta(days=10)          # feature warm-up
    hi = btc.index[-1]
    mid = lo + (hi - lo) / 2
    s, keep = run_all(mid)
    s = mark_robust(s)
    s.to_csv(RESULTS / "grid_sweep.csv", index=False)
    if not keep.empty:
        keep.to_parquet(CACHE / "trades_pf_gt1.parquet")
    wf = walk_forward(s)
    wf.to_csv(RESULTS / "walk_forward.csv", index=False)
    meta = {"period": [str(lo), str(hi)], "split": str(mid), "configs": int(len(s)),
            "signals": int(s["signals"].sum()), "taken": int(s["n"].sum()),
            "rej_step": int(s["rej_step"].sum()), "rej_loss": int(s["rej_loss"].sum()),
            "rej_liq": int(s["rej_liq"].sum()),
            "configs_all_rejected": int((s["n"] == 0).sum()),
            "configs_pf_gt1": int(((s["pf"] > 1) & (s["n"] >= 25)).sum()),
            "configs_gate": int(s["gate"].sum()), "configs_robust": int(s["robust"].sum()),
            "runtime_s": round(time.time() - t0)}
    (RESULTS / "meta.json").write_text(json.dumps(meta, indent=1))
    log.info("%s", meta)
    cols = ["strat", "grids", "lev", "width", "hold", "n", "pf", "win", "exp_r", "tot_r",
            "max_dd_r", "pf1", "pf2", "gate", "robust"]
    print(s.sort_values("exp_r", ascending=False)[cols].head(30).to_string())
    print(wf.to_string())


if __name__ == "__main__":
    main()
