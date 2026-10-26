"""
Do positioning features (funding, OI, long/short) add edge to the live setups?

Two modes:

  ledger    Join the feature snapshot stored on each fired trigger
            (triggers.features_json, see docs/night/features.md) with its paper
            outcome (triggers.r_multiple from triggers/outcomes.py) and report
            expectancy R, PF and n by feature bucket. This is the forward test:
            it only means something once a few dozen signals have closed.

  backtest  Historical test for the two edge-gated setups in skills/new_setups.py
            (Distribution Short, Downtrend Bounce Fade). Daily MEXC perp candles,
            the exact live detector, the research exit model
            (research/bear_shorts.sim_short, 0.36% round trip), and at each
            signal day the positioning that was knowable at that close:
              OKX rubik daily (UTC) OI in coin units and L/S account ratio
                (history reaches back to ~2024-03; earlier pages return empty)
              MEXC funding history (reaches back to 2025-05-05 for every coin;
                OKX keeps only ~3 months so it is not used for history)
            Reports PF / expectancy by bucket and whether simple crowding filters
            improve PF. Survivor-only universe (coins that still trade).

Run:
  python research/features_eval.py ledger
  python research/features_eval.py backtest [--cache DIR] [--max-coins N]
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features._http import fnum, get_json, split_symbol  # noqa: E402

OKX = "https://www.okx.com"
MEXC = "https://contract.mexc.com"
COST = 0.0036
OKX_HIST_START = pd.Timestamp("2024-04-01")      # first date with full 100d OI/LS lookback


# ── shared stats ────────────────────────────────────────────────────────────
def pf(rs) -> float | None:
    a = np.asarray([r for r in rs if r is not None and np.isfinite(r)], dtype=float)
    if len(a) == 0:
        return None
    loss = -a[a < 0].sum()
    return float(a[a > 0].sum() / loss) if loss > 0 else float("inf")


def summarise(rs) -> dict:
    a = np.asarray([r for r in rs if r is not None and np.isfinite(r)], dtype=float)
    if len(a) == 0:
        return {"n": 0, "exp_r": None, "pf": None, "win": None}
    return {"n": int(len(a)), "exp_r": round(float(a.mean()), 3),
            "pf": None if pf(a) is None else round(pf(a), 2),
            "win": round(float((a > 0).mean()), 3)}


def bucket_table(df: pd.DataFrame, feature: str, r_col: str = "r",
                 edges: list[float] | None = None, q: int = 3) -> list[dict]:
    """Expectancy by bucket of `feature`. Fixed `edges` or `q` quantiles.
    A None/NaN feature gets its own 'missing' row."""
    rows = []
    x = pd.to_numeric(df[feature], errors="coerce")
    have = df[x.notna()]
    if len(have) >= q * 3 or edges:
        try:
            if edges:
                cats = pd.cut(x[x.notna()], edges, include_lowest=True)
            else:
                cats = pd.qcut(x[x.notna()], q, duplicates="drop")
            for cat, grp in have.groupby(cats, observed=True):
                rows.append({"feature": feature, "bucket": str(cat), **summarise(grp[r_col])})
        except ValueError:
            pass
    miss = df[x.isna()]
    if len(miss):
        rows.append({"feature": feature, "bucket": "missing", **summarise(miss[r_col])})
    return rows


def print_rows(rows: list[dict]) -> None:
    for r in rows:
        e = "  n/a" if r["exp_r"] is None else f"{r['exp_r']:+.3f}"
        p = "  n/a" if r["pf"] is None else f"{r['pf']:5.2f}"
        print(f"  {r['feature']:<22}{r['bucket']:<26}n={r['n']:<5}expR={e}  PF={p}")


# ── ledger mode ─────────────────────────────────────────────────────────────
FLAG_COLS = ("crowded_longs", "crowded_shorts", "oi_spike", "dex_hype", "squeeze_risk",
             "flush_risk")
NUM_COLS = ("funding_pct_7d", "funding_8h", "oi_chg_24h", "oi_chg_4h", "ls_pct_4d",
            "ls_ratio", "taker_ratio_24h", "dex_vol_exp_1h", "dex_buy_ratio_h1")


def ledger_frame(trades: list[dict]) -> pd.DataFrame:
    """Closed fired trades with a stored snapshot -> one row per trade."""
    rows = []
    for t in trades:
        if t.get("r_multiple") is None or not t.get("features_json"):
            continue
        try:
            snap = json.loads(t["features_json"])
        except (TypeError, ValueError):
            continue
        rows.append({"id": t.get("id"), "setup": t.get("setup_label"),
                     "direction": t.get("direction"), "r": float(t["r_multiple"]), **snap})
    return pd.DataFrame(rows)


def run_ledger(trades: list[dict] | None = None) -> dict:
    if trades is None:
        from triggers import db as tdb
        trades = tdb.get_fired_trades()
    closed = [t for t in trades if t.get("r_multiple") is not None]
    df = ledger_frame(trades)
    print(f"ledger: {len(trades)} fired, {len(closed)} closed, {len(df)} closed with a feature snapshot")
    out = {"fired": len(trades), "closed": len(closed), "with_features": len(df), "rows": []}
    if df.empty:
        print("  nothing to evaluate yet (snapshots start once the integration patch is live)")
        return out
    print("  all:", summarise(df["r"]))
    rows = []
    for f in FLAG_COLS:
        if f in df:
            rows += bucket_table(df, f, edges=[-0.5, 0.5, 1.5])
    for f in NUM_COLS:
        if f in df:
            rows += bucket_table(df, f, q=3)
    print_rows(rows)
    out["rows"] = rows
    return out


# ── backtest mode: data ─────────────────────────────────────────────────────
class Cache:
    def __init__(self, path: Path | None):
        self.path = path
        self.d: dict = {}
        if path and path.exists():
            self.d = pickle.loads(path.read_bytes())

    def get(self, key, fn):
        if key not in self.d:
            self.d[key] = fn()
        return self.d[key]

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(pickle.dumps(self.d))


def mexc_daily(base: str) -> pd.DataFrame | None:
    now = int(time.time())
    js = get_json(f"{MEXC}/api/v1/contract/kline/{base}_USDT",
                  {"interval": "Day1", "start": now - 2000 * 86400, "end": now},
                  bucket="mexc", rate=(8, 2.0), timeout=15)
    d = (js or {}).get("data") or {}
    if not d.get("time"):
        return None
    df = pd.DataFrame({"open": d["open"], "high": d["high"], "low": d["low"],
                       "close": d["close"], "volume": d["vol"]},
                      index=pd.to_datetime(d["time"], unit="s")).astype(float)
    # MEXC 'vol' is contracts; turnover 'amount' is quote USD: use amount/close as
    # base volume so qvol20 (close*volume) equals the USD turnover the gate expects.
    if d.get("amount"):
        df["volume"] = np.asarray(d["amount"], dtype=float) / df["close"].replace(0, np.nan)
    df = df[~df.index.duplicated()].sort_index()
    return df


def mexc_funding(base: str) -> pd.Series | None:
    out = []
    for page in range(1, 8):
        js = get_json(f"{MEXC}/api/v1/contract/funding_rate/history",
                      {"symbol": f"{base}_USDT", "page_num": page, "page_size": 1000},
                      bucket="mexc", rate=(8, 2.0), timeout=15)
        d = (js or {}).get("data") or {}
        rl = d.get("resultList") or []
        out += [(r["settleTime"], fnum(r.get("fundingRate")), fnum(r.get("collectCycle")) or 8)
                for r in rl]
        if page >= (d.get("totalPage") or 0):
            break
    if not out:
        return None
    s = pd.DataFrame(out, columns=["t", "r", "cyc"]).dropna()
    s["r8"] = s["r"] * 8.0 / s["cyc"]
    return pd.Series(s["r8"].values, index=pd.to_datetime(s["t"], unit="ms")).sort_index()


def okx_daily(endpoint: str, inst: str, end_day: pd.Timestamp) -> pd.DataFrame:
    """100 UTC-daily rows ending at end_day (inclusive)."""
    end_ms = int((end_day + pd.Timedelta(days=1)).timestamp() * 1000)
    js = get_json(f"{OKX}/api/v5/rubik/stat/contracts/{endpoint}",
                  {"instId": inst, "period": "1Dutc", "end": end_ms, "limit": 100},
                  bucket="okx_rubik", rate=(4, 2.0), timeout=15)
    data = (js or {}).get("data") or []
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data).iloc[:, :4] if endpoint == "open-interest-history" else pd.DataFrame(data)
    df.index = pd.to_datetime(df.iloc[:, 0].astype("int64"), unit="ms")
    return df.sort_index()


def okx_insts() -> set[str]:
    js = get_json(f"{OKX}/api/v5/public/instruments", {"instType": "SWAP"}, timeout=15)
    return {d["instId"][:-10] for d in (js or {}).get("data", [])
            if d.get("instId", "").endswith("-USDT-SWAP")}


# ── backtest mode: features at a signal ─────────────────────────────────────
def hist_features(day: pd.Timestamp, oi: pd.DataFrame, ls: pd.DataFrame,
                  fund: pd.Series | None) -> dict:
    """Positioning knowable at the close of `day` (entry is that close)."""
    f: dict = {}
    if not oi.empty:
        s = pd.to_numeric(oi.iloc[:, 2], errors="coerce").loc[:day].dropna()   # OI in coin
        if len(s) >= 8 and s.index[-1] >= day - pd.Timedelta(days=1):
            f["oi_chg_1d"] = (s.iloc[-1] / s.iloc[-2] - 1) * 100
            f["oi_chg_3d"] = (s.iloc[-1] / s.iloc[-4] - 1) * 100
            f["oi_chg_7d"] = (s.iloc[-1] / s.iloc[-8] - 1) * 100
            if len(s) >= 31:
                f["oi_chg_30d"] = (s.iloc[-1] / s.iloc[-31] - 1) * 100
    if not ls.empty:
        s = pd.to_numeric(ls.iloc[:, 1], errors="coerce").loc[:day].dropna()
        if len(s) >= 30 and s.index[-1] >= day - pd.Timedelta(days=1):
            f["ls_ratio"] = s.iloc[-1]
            w = s.iloc[-30:]
            f["ls_pct_30d"] = float((w < s.iloc[-1]).mean() * 100 + (w == s.iloc[-1]).mean() * 50)
            f["ls_chg_3d"] = (s.iloc[-1] / s.iloc[-4] - 1) * 100
    if fund is not None and len(fund):
        cut = day + pd.Timedelta(days=1)                 # settlements up to the entry
        h = fund.loc[:cut]
        if len(h) and h.index[-1] >= day - pd.Timedelta(days=1) and h.index[0] <= day - pd.Timedelta(days=30):
            last3 = h.loc[cut - pd.Timedelta(days=3):]
            w30 = h.loc[cut - pd.Timedelta(days=30):]
            f["fund_3d_8h"] = float(last3.mean())
            f["fund_last_8h"] = float(h.iloc[-1])
            f["fund_pct_30d"] = float((w30 < last3.mean()).mean() * 100
                                      + (w30 == last3.mean()).mean() * 50)
    return f


def run_backtest(cache_dir: Path | None, max_coins: int | None = None, verbose: bool = True) -> dict:
    from research.bear_shorts import sim_short
    from skills import new_setups as NS

    cache = Cache(cache_dir / "features_eval_cache.pkl" if cache_dir else None)
    perps = json.loads((Path(__file__).resolve().parents[1] / "data" / "bybit_perps.json")
                       .read_text())["symbols"]
    okx = cache.get("okx_insts", okx_insts)
    pairs = []                                       # (bybit symbol, mexc base, okx core)
    for s in perps:
        base, core = split_symbol(s)
        if core in okx:
            pairs.append((s, core))
    if max_coins:
        pairs = pairs[:max_coins]
    btc = cache.get("k:BTC", lambda: mexc_daily("BTC"))
    btc_close = btc["close"]
    btc_close.index = btc_close.index.normalize()

    trades = []
    t0 = time.time()
    for i, (sym, core) in enumerate(pairs):
        df = cache.get(f"k:{core}", lambda: mexc_daily(core))
        if df is None or len(df) < 260:
            continue
        df = df.copy()
        df.index = df.index.normalize()
        det = NS.detect(df, btc_close)
        c, h, l = df["close"], df["high"], df["low"]
        idx = np.flatnonzero(det["label"].notna().values)
        last = {NS.DIST: -99, NS.FADE: -99}
        for j in idx:
            day = df.index[j]
            lab = det["label"].iat[j]
            if j < 205 or day < OKX_HIST_START or j - last[lab] < 5:
                continue
            last[lab] = j
            tgt = det["target"].iat[j]
            tgt = None if pd.isna(tgt) else float(tgt)
            trail = det["trail_atr"].iat[j]
            r = sim_short(c, h, l, j, float(det["stop"].iat[j]), tgt,
                          None if pd.isna(trail) else float(trail),
                          float(det["atr"].iat[j]), int(det["max_hold"].iat[j]))
            if r is None or not np.isfinite(r) or abs(r) > 50:
                continue
            inst = f"{core}-USDT-SWAP"
            oi = cache.get(f"oi:{core}:{day.date()}",
                           lambda: okx_daily("open-interest-history", inst, day))
            ls = cache.get(f"ls:{core}:{day.date()}",
                           lambda: okx_daily("long-short-account-ratio-contract", inst, day))
            fund = cache.get(f"f:{core}", lambda: mexc_funding(core))
            trades.append({"symbol": sym, "setup": lab, "day": day, "r": float(r),
                           **hist_features(day, oi, ls, fund)})
        if verbose and i % 25 == 0:
            print(f"  .. {i}/{len(pairs)} coins, {len(trades)} trades, {time.time() - t0:.0f}s",
                  flush=True)
            cache.save()
    cache.save()
    res = pd.DataFrame(trades)
    return analyse_backtest(res, verbose)


FILTERS = {
    # name: (columns it needs, keep-mask). Trades missing a needed column are KEPT
    # (the filter only acts where the feature is known), and the PF of the base
    # setup on the covered subset is printed alongside for a fair comparison.
    "skip OI 7d up >= 10%":       (("oi_chg_7d",), lambda d: ~(d["oi_chg_7d"] >= 10)),
    "skip OI 7d down <= -10%":    (("oi_chg_7d",), lambda d: ~(d["oi_chg_7d"] <= -10)),
    "need OI 3d rising (> 0)":    (("oi_chg_3d",), lambda d: d["oi_chg_3d"] > 0),
    "skip L/S p30 <= 20":         (("ls_pct_30d",), lambda d: ~(d["ls_pct_30d"] <= 20)),
    "need L/S p30 >= 50":         (("ls_pct_30d",), lambda d: d["ls_pct_30d"] >= 50),
    "skip funding < 0 (3d avg)":  (("fund_3d_8h",), lambda d: ~(d["fund_3d_8h"] < 0)),
    "need funding > clamp":       (("fund_3d_8h",), lambda d: d["fund_3d_8h"] > 0.000105),
    "skip funding p30 <= 20":     (("fund_pct_30d",), lambda d: ~(d["fund_pct_30d"] <= 20)),
    "only crowded longs (L/S p30>=80 & OI7d>0)":
        (("ls_pct_30d", "oi_chg_7d"), lambda d: (d["ls_pct_30d"] >= 80) & (d["oi_chg_7d"] > 0)),
}


def _r2(x):
    return None if x is None else round(x, 2)


def analyse_backtest(res: pd.DataFrame, verbose: bool = True) -> dict:
    out: dict = {"n": int(len(res)), "by_setup": {}}
    if res.empty:
        if verbose:
            print("backtest: no trades")
        return out
    if verbose:
        print(f"\nbacktest: {len(res)} trades {res['day'].min().date()} -> {res['day'].max().date()}")
    for setup, g in res.groupby("setup"):
        g = g.sort_values("day")
        base = summarise(g["r"])
        cover = {k: int(g[k].notna().sum()) for k in ("oi_chg_7d", "ls_pct_30d", "fund_3d_8h")
                 if k in g}
        block = {"base": base, "coverage": cover, "buckets": [], "filters": []}
        if verbose:
            print(f"\n== {setup}: base {base}  feature coverage {cover}")
        for f in ("oi_chg_1d", "oi_chg_7d", "oi_chg_30d", "ls_pct_30d", "ls_chg_3d",
                  "fund_3d_8h", "fund_pct_30d"):
            if f in g:
                rows = bucket_table(g, f, q=3)
                block["buckets"] += rows
                if verbose:
                    print_rows(rows)
        mid = g["day"].iloc[len(g) // 2] if len(g) else None
        for name, (need, fn) in FILTERS.items():
            if not all(c in g for c in need):
                continue
            covered = g.dropna(subset=list(need))
            mask = pd.Series(True, index=g.index)
            if not covered.empty:
                mask.loc[covered.index] = fn(covered).astype(bool)
            kept = g[mask]
            kept_cov = covered[mask.loc[covered.index]] if not covered.empty else covered
            row = {"filter": name, **summarise(kept["r"]),
                   "covered_n": int(len(covered)),
                   "covered_base": summarise(covered["r"]),
                   "covered_kept": summarise(kept_cov["r"]),
                   "pf_h1": _r2(pf(kept[kept["day"] < mid]["r"])),
                   "pf_h2": _r2(pf(kept[kept["day"] >= mid]["r"]))}
            block["filters"].append(row)
            if verbose:
                cb, ck = row["covered_base"], row["covered_kept"]
                print(f"  filter {name:<42} all: n={row['n']:<4} PF={row['pf']} expR={row['exp_r']}"
                      f" halves {row['pf_h1']}/{row['pf_h2']} | covered: base n={cb['n']} PF={cb['pf']}"
                      f" -> kept n={ck['n']} PF={ck['pf']} expR={ck['exp_r']}")
        out["by_setup"][setup] = block
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["ledger", "backtest"])
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--max-coins", type=int, default=None)
    ap.add_argument("--json-out", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.mode == "ledger":
        res = run_ledger()
    else:
        res = run_backtest(a.cache, a.max_coins)
    if a.json_out:
        a.json_out.write_text(json.dumps(res, default=str, indent=1))


if __name__ == "__main__":
    main()
