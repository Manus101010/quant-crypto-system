"""
Research: INTRADAY trend setups aligned with lower-timeframe BTC (the way the
user actually trades) — Bybit USDT perps, 1h execution, Jan 2025 → now.

Shorts (and the mirrored longs):
  breakdown   1h close below the lowest low of the prior N hours (24 / 72),
              coin below its 4h EMA20
  pullback    coin in a 4h downtrend (below a FALLING 4h EMA20); a 1h bar pokes
              above the 1h EMA20 and closes back below it (lower high)
BTC filter (tested with and without): BTC below its 4h EMA20 AND 1h EMA50
(for longs: above both).
Plan: stop 2 x ATR(1h) beyond entry; target 2R; 48h time stop. Exit variant:
trail 2 x ATR(1h) off the best price. One position per coin at a time.
Costs 0.36% round trip + real funding where we have it. 1R = $12.50.
Baseline: random 1h shorts on the same coins, same plan.

Run:  ./venv/bin/python research/intraday_trend.py overext.pkl [report.md]
"""
from __future__ import annotations
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

import os
R_USD, COST = 12.50, float(os.environ.get("COST", 0.0036))   # 0.36% legacy; Bybit realistic ~0.15%
RNG = np.random.default_rng(11)
PRIOR_TESTS = 54          # leaderboard (22) + overextension study (16) + its extras


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    c = df["close"]
    tr = pd.concat([df["high"] - df["low"], (df["high"] - c.shift()).abs(), (df["low"] - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def h4_on_1h(h: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """4h EMA20 and its 24h-ago value, as known at each 1h bar's close."""
    h4 = h["close"].resample("4h", label="left", closed="left").last().dropna()
    e = ema(h4, 20)
    avail = lambda s: s.set_axis(s.index + pd.Timedelta(hours=4)).reindex(  # noqa: E731
        (h.index + pd.Timedelta(hours=1)).union(s.index + pd.Timedelta(hours=4))).ffill().reindex(h.index + pd.Timedelta(hours=1)).to_numpy()
    return avail(e), avail(e.shift(6))


def prep(h: pd.DataFrame, btc: pd.DataFrame) -> pd.DataFrame:
    f = h[["open", "high", "low", "close"]].copy()
    f["atr"] = atr(h)
    f["e20"], f["e50"] = ema(h["close"], 20), ema(h["close"], 50)
    f["e4"], f["e4_prev"] = h4_on_1h(h)
    for n in (24, 72):
        f[f"lo{n}"] = h["low"].shift().rolling(n).min()
        f[f"hi{n}"] = h["high"].shift().rolling(n).max()
    f["dvol"] = (h["volume"] * h["close"]).rolling(24 * 20, min_periods=48).mean() * 24
    b = btc.reindex(f.index).ffill()
    f["btc_bear"], f["btc_bull"] = b["bear"].fillna(False).to_numpy(), b["bull"].fillna(False).to_numpy()
    return f


def signals(f: pd.DataFrame, kind: str) -> np.ndarray:
    c = f["close"]
    if kind == "breakdown24":
        s = (c < f["lo24"]) & (c < f["e4"])
    elif kind == "breakdown72":
        s = (c < f["lo72"]) & (c < f["e4"])
    elif kind == "pullback":
        s = (c < f["e4"]) & (f["e4"] < f["e4_prev"]) & (f["high"] > f["e20"]) & (c < f["e20"]) & (c < f["open"])
    elif kind == "breakout24":
        s = (c > f["hi24"]) & (c > f["e4"])
    elif kind == "breakout72":
        s = (c > f["hi72"]) & (c > f["e4"])
    elif kind == "dip":
        s = (c > f["e4"]) & (f["e4"] > f["e4_prev"]) & (f["low"] < f["e20"]) & (c > f["e20"]) & (c > f["open"])
    else:
        raise ValueError(kind)
    return s.fillna(False).to_numpy()


def simulate(f, idx, short, fund, exit_kind="2R", hours=48):
    hi, lo, cl, at = (f[k].to_numpy() for k in ("high", "low", "close", "atr"))
    out, busy_until = [], -1
    sg = -1 if short else 1
    for i in idx:
        if i <= busy_until or i + 1 >= len(f) or not np.isfinite(at[i]) or at[i] <= 0:
            continue
        entry, risk = cl[i], 2 * at[i]
        if risk / entry > 0.25:
            continue
        stop, target = entry - sg * risk, entry + sg * 2 * risk
        best, ex, why = entry, None, "time"
        j = i
        for j in range(i + 1, min(len(f), i + 1 + hours)):
            if (short and hi[j] >= stop) or (not short and lo[j] <= stop):
                ex, why = stop, "stop"
                break
            if exit_kind == "2R" and ((short and lo[j] <= target) or (not short and hi[j] >= target)):
                ex, why = target, "target"
                break
            if exit_kind == "trail":
                best = min(best, lo[j]) if short else max(best, hi[j])
                new = best - sg * 2 * at[i]
                stop = min(stop, new) if short else max(stop, new)
        if ex is None:
            ex = cl[j]
        busy_until = j
        t0, t1 = f.index[i], f.index[j]
        fr = 0.0
        if fund is not None and len(fund):
            rates = fund[(fund.index > t0) & (fund.index <= t1)]
            fr = float(rates.sum()) * entry / risk * (1 if short else -1)
        r = sg * (ex - entry) / risk - COST * entry / risk + fr
        out.append({"t": t0, "x": t1, "r": r, "liquid": f["dvol"].iat[i] >= 2e6})
    return out


def stats(tr):
    if not tr:
        return None
    r = np.array([t["r"] for t in sorted(tr, key=lambda t: t["x"])])
    gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    eq = np.cumsum(r)
    return {"n": len(r), "win": (r > 0).mean() * 100, "pf": gw / gl if gl else 99, "avg": r.mean(),
            "tot": r.sum(), "dd": (eq - np.maximum.accumulate(eq)).min(),
            "t": r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if len(r) > 2 else 0}


HDR = ("| setup | trades | win | PF | avg R | total R | total $ | max DD (R) | t | PF 1st half | PF 2nd half | liquid PF | small PF |\n"
       "|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def line(name, tr):
    s = stats(tr)
    if not s:
        return f"| {name} | 0 |"
    mid = sorted(t["t"] for t in tr)[len(tr) // 2]
    pf = lambda g: (stats(g) or {"pf": 0})["pf"]  # noqa: E731
    return (f"| {name} | {s['n']} | {s['win']:.0f}% | {s['pf']:.2f} | {s['avg']:+.3f} | {s['tot']:+.0f} | "
            f"${s['tot'] * R_USD:+,.0f} | {s['dd']:.0f} | {s['t']:.2f} | {pf([t for t in tr if t['t'] < mid]):.2f} | "
            f"{pf([t for t in tr if t['t'] >= mid]):.2f} | {pf([t for t in tr if t['liquid']]):.2f} | "
            f"{pf([t for t in tr if not t['liquid']]):.2f} |")


def main(pkl, report=None):
    d = pickle.loads(Path(pkl).read_bytes())
    b15 = d["btc15"]
    b1 = b15.resample("1h", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    e4, _ = h4_on_1h(b1)
    btc = pd.DataFrame({"bear": (b1["close"] < e4) & (b1["close"] < ema(b1["close"], 50)),
                        "bull": (b1["close"] > e4) & (b1["close"] > ema(b1["close"], 50))}, index=b1.index)
    frames = {}
    for sym, rec in d["coins"].items():
        if rec and rec.get("h1") is not None and len(rec["h1"]) > 600:
            frames[sym] = (prep(rec["h1"], btc), rec.get("funding"))
    del d
    cfgs = [("SHORT breakdown 24h", "breakdown24", True), ("SHORT breakdown 72h", "breakdown72", True),
            ("SHORT pullback in 4h downtrend", "pullback", True),
            ("LONG breakout 24h", "breakout24", False), ("LONG breakout 72h", "breakout72", False),
            ("LONG dip in 4h uptrend", "dip", False)]
    res = {}
    for name, kind, short in cfgs:
        for filt in (False, True):
            tr = []
            for sym, (f, fund) in frames.items():
                s = signals(f, kind)
                if filt:
                    s = s & (f["btc_bear"] if short else f["btc_bull"]).astype(bool)
                tr += simulate(f, np.flatnonzero(s), short, fund)
            res[(name, filt)] = tr
    n_tests = PRIOR_TESTS + len(res) + 4
    t_need = float(norm.ppf(1 - 0.05 / (2 * n_tests)))
    out = [f"# Intraday trend setups aligned with lower-timeframe BTC — Bybit perps, 1h\n",
           f"Coins: {len(frames)} · Jan 2025 → now · stop 2×ATR(1h), target 2R, 48h · 0.36% + funding · "
           f"1R = ${R_USD}. Tests so far: {n_tests} → t needed {t_need:.2f}.\n", HDR]
    for (name, filt), tr in res.items():
        out.append(line(name + (" + BTC aligned" if filt else ""), tr))
    best = max(res, key=lambda k: (stats(res[k]) or {"t": -9})["t"])
    name, filt = best
    kind, short = next((k, s) for n, k, s in cfgs if n == name)
    out += [f"\n## Best by t-stat: {name}{' + BTC aligned' if filt else ''} — exits and baseline\n", HDR]
    tr_trail, tr_rand = [], []
    for sym, (f, fund) in frames.items():
        s = signals(f, kind)
        if filt:
            s = s & (f["btc_bear"] if short else f["btc_bull"]).astype(bool)
        idx = np.flatnonzero(s)
        tr_trail += simulate(f, idx, short, fund, "trail")
        if len(idx):
            tr_rand += simulate(f, np.sort(RNG.choice(np.arange(100, len(f) - 2), size=min(len(idx), len(f) - 102), replace=False)), short, fund)
    out += [line("target 2R (as above)", res[best]), line("trailing 2×ATR off best price", tr_trail),
            line("BASELINE random entries, same coins & count", tr_rand)]
    by_year = {}
    for t in res[best]:
        by_year.setdefault(t["t"].year, []).append(t)
    out.append("\nBy year: " + " · ".join(f"{y}: n{len(g)} PF {stats(g)['pf']:.2f} avgR {stats(g)['avg']:+.3f}" for y, g in sorted(by_year.items())))
    s = stats(res[best])
    ok = s and s["n"] >= 50 and s["pf"] > 1 and s["avg"] > 0 and s["t"] >= t_need
    out.append(f"\n**Verdict: {'PASS' if ok else 'FAIL'}** (needs PF > 1, avg R > 0, t ≥ {t_need:.2f}; best t = {s['t']:.2f}).")
    txt = "\n".join(out)
    print(txt)
    if report:
        Path(report).write_text(txt)


if __name__ == "__main__":
    main(*sys.argv[1:])
