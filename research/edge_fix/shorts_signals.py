"""
Build every short signal 2022-01..2026-10 on the survivorship-free Binance UM
panel and simulate the base plan plus the exit/entry variants on 1h bars.
Writes one row per signal to <out>/short_trades.parquet.

Run:  python research/edge_fix/shorts_signals.py <data_dir> <out_dir>
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.edge_fix import shorts_core as C  # noqa: E402
from skills import new_setups as NS  # noqa: E402

START = pd.Timestamp("2022-01-01")
HOLD = {C.DS: 60, C.DBF: 10, C.BDS: 60}          # live max hold, days
HOLD_SHORT = {C.DS: 20, C.DBF: 5, C.BDS: 20}     # variant V4


def pass1(root: Path):
    syms = pd.read_csv(root / "symbols.csv").iloc[:, 0].tolist()
    daily, meta = {}, {}
    for s in syms:
        if C.base_of(s) in C.EXCLUDE_BASES:
            continue
        k = C.load_1h(root, s)
        if k is None:
            continue
        d = C.daily_from_1h(k)
        if len(d) < 60:
            continue
        daily[s] = d
        meta[s] = {"first": k.index[0], "last": k.index[-1],
                   "dead": k.index[-1] < C.DATA_END_ALIVE}
    return daily, meta


def context(root: Path, daily: dict) -> pd.DataFrame:
    btc = daily["BTCUSDT"]["close"]
    k = C.load_1h(root, "BTCUSDT")
    k4 = k["close"].resample("4h").last().dropna()
    ema50 = k4.ewm(span=50, adjust=False).mean()
    below = (k4 < ema50)
    # value at the last 4h bar of each UTC day (opens 20:00, closes 24:00)
    below_d = below.groupby(below.index.normalize()).last()
    s50, s200 = btc.rolling(50).mean(), btc.rolling(200).mean()
    # breadth: share of liquid coins above their own 50d SMA
    cl = pd.DataFrame({s: d["close"] for s, d in daily.items()})
    qv = pd.DataFrame({s: d["quote_volume"] for s, d in daily.items()}).rolling(20).mean()
    sma = cl.rolling(50).mean()
    ok = sma.notna() & (qv >= 0.5e6)
    breadth = ((cl > sma) & ok).sum(axis=1) / ok.sum(axis=1).replace(0, np.nan)
    ctx = pd.DataFrame({"btc": btc, "btc_above50": btc > s50, "btc_above200": btc > s200,
                        "btc_trend": NS.btc_trend(btc), "btc_4h_below_ema50": below_d,
                        "breadth50": breadth, "n_coins": ok.sum(axis=1),
                        "btc_r7": btc / btc.shift(7) - 1})
    return ctx


def _confirm(o, h, l, c, hours, s, stop, level, target, window, every4):
    """First close below `level` within `window` hourly bars from s (4h closes
    only when every4). Cancel if price trades up to the stop first."""
    n = len(c)
    for j in range(s, min(s + window, n)):
        if h[j] >= stop:
            return -1, np.nan
        if every4 and (hours[j] + 1) % 4 != 0:
            continue
        if c[j] < level:
            if not np.isnan(target) and c[j] <= target:
                return -1, np.nan
            return j, c[j]
    return -1, np.nan


def run_symbol(root: Path, sym: str, d: pd.DataFrame, meta: dict, ctx: pd.DataFrame,
               btc_close: pd.Series) -> list[dict]:
    if len(d) < 206:
        return []
    k = C.load_1h(root, sym)
    o, h, l, c = (k[x].values.astype(np.float64) for x in ("open", "high", "low", "close"))
    hours = k.index.hour.values
    cumf, fprints = C.load_funding(root, sym, k.index)
    det = NS.detect(d[["open", "high", "low", "close", "volume"]], btc_close)
    bd = C.breakdown_signals(d)
    x = NS._ind(d)
    sigs = []
    for i in range(205, len(d)):
        day = d.index[i]
        if day < START:
            continue
        lab = det["label"].iat[i]
        if lab:
            tgt = det["target"].iat[i]
            sigs.append((lab, i, float(det["stop"].iat[i]), np.nan if pd.isna(tgt) else float(tgt),
                         3.5 * float(det["atr"].iat[i]) if lab == C.DS else np.nan, False))
        if bd["sig"].iat[i]:
            sigs.append((C.BDS, i, float(bd["stop"].iat[i]), np.nan,
                         3.5 * float(bd["atr"].iat[i]), bool(bd["oversold"].iat[i])))
    rows, busy = [], {}
    idx = k.index
    for lab, i, stop, tgt, trail, oversold in sigs:
        day = d.index[i]
        t_entry = day + pd.Timedelta(days=1)
        s = int(idx.searchsorted(t_entry))
        if s >= len(c) or s == 0:
            continue
        if busy.get(lab) is not None and busy[lab] >= t_entry:
            continue
        entry = float(d["close"].iat[i])
        if not (np.isfinite(stop) and stop > entry):
            continue
        if not np.isnan(tgt) and tgt >= entry:
            continue
        dead = meta["dead"]

        def run(s0, e0, hold_days, tgt0=tgt, trail0=trail, be=np.nan):
            j, px, code = C.sim_short_1h(o, h, l, c, cumf, s0, e0, stop, tgt0, trail0, be,
                                         hold_days * 24, dead)
            if code == 5:
                return np.nan, j, code
            return C.r_of(e0, stop, px, cumf, s0 - 1, j), j, code

        r0, j0, code0 = run(s, entry, HOLD[lab])
        busy[lab] = idx[j0]
        r_time, _, _ = run(s, entry, HOLD_SHORT[lab])
        if lab == C.DBF:
            r_exit, _, _ = run(s, entry, HOLD[lab], be=0.5)
        else:
            r_exit, _, _ = run(s, entry, HOLD[lab], tgt0=entry - 2 * (stop - entry))
        lowD = float(d["low"].iat[i])
        out = {}
        for name, win, ev4 in (("conf4h", 48, True), ("conf1h", 24, False)):
            jj, ce = _confirm(o, h, l, c, hours, s, stop, lowD, tgt, win, ev4)
            if jj < 0:
                out[name] = np.nan
                out[name + "_hit"] = False
            else:
                r, _, _ = run(jj + 1, ce, HOLD[lab])
                out[name] = r
                out[name + "_hit"] = True
        fp = fprints[fprints.index <= t_entry]
        q20 = float(x["qvol20"].iat[i]) if lab != C.BDS else float(bd["qvol20"].iat[i])
        cx = ctx.loc[day] if day in ctx.index else None
        rows.append({
            "sym": sym, "setup": lab, "date": day, "entry": entry, "stop": stop, "target": tgt,
            "stop_pct": (stop / entry - 1) * 100, "atr": float(x["atr"].iat[i]),
            "qvol20": q20, "oversold": oversold, "dead": dead,
            "age_days": (day - meta["first"]).days,
            "listed_before_archive": meta["first"] <= pd.Timestamp("2021-06-02"),
            "fund_last": float(fp.iat[-1]) if len(fp) else np.nan,
            "fund3": float(fp.iloc[-3:].mean()) if len(fp) >= 3 else np.nan,
            "macro_next2": bool(((C.MACRO >= t_entry) & (C.MACRO <= t_entry + pd.Timedelta(days=1))).any()),
            "r": r0, "exit_code": int(code0), "bars_h": int(j0 - s + 1),
            "r_time": r_time, "r_exit": r_exit, **out,
            **({} if cx is None else {kk: cx[kk] for kk in
                ("btc_above50", "btc_above200", "btc_trend", "btc_4h_below_ema50", "breadth50",
                 "btc_r7")}),
        })
    return rows


def main():
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    daily, meta = pass1(root)
    print(f"pass1: {len(daily)} symbols, {sum(m['dead'] for m in meta.values())} delisted "
          f"({time.time()-t0:.0f}s)", flush=True)
    ctx = context(root, daily)
    ctx.to_parquet(out / "short_ctx.parquet")
    btc_close = daily["BTCUSDT"]["close"]
    rows = []
    for n, (s, d) in enumerate(daily.items(), 1):
        try:
            rows += run_symbol(root, s, d, meta[s], ctx, btc_close)
        except Exception as e:                     # noqa: BLE001
            print("  fail", s, e, flush=True)
        if n % 100 == 0:
            print(f"  {n}/{len(daily)} symbols, {len(rows)} signals ({time.time()-t0:.0f}s)", flush=True)
    T = pd.DataFrame(rows)
    T.to_parquet(out / "short_trades.parquet")
    pd.DataFrame(meta).T.to_parquet(out / "short_meta.parquet")
    print(T.groupby("setup").size(), flush=True)


if __name__ == "__main__":
    main()
