"""
Intraday OVEREXTENSION SHORT research (Bybit USDT perps, 15m execution).

Each variant = one idea from the brief; all share the trade plan:
  entry  : short on the 15m close that confirms the turn
  stop   : swing high (highest high of the last 12h) + 0.25 x ATR(1h)
  target : the 4h EMA20 at entry ("back to its MA")   [exit variants: 1h EMA50, trailing]
  time   : 48h                                        [exit variant: 24h]
  costs  : 0.36% round trip + REAL Bybit funding while short (shorts receive
           positive funding, pay negative)
  1 trade per pump episode. Measured in R (1R = $12.50).
Higher-timeframe values only use bars that had CLOSED at decision time.

Baselines (does the setup beat "pumps fall"?):
  A  random 15m entry anywhere inside the same pump episodes (no hindsight), same plan
  B  short the first moment the coin is overextended, no turn confirmation

Run:  ./venv/bin/python research/overext/backtest.py overext.pkl [report.md]
"""
from __future__ import annotations
import csv
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[2]
R_USD = 12.50
COST = 0.0036
RNG = np.random.default_rng(7)


# ── indicators ────────────────────────────────────────────────────────────────
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df, n=14):
    c = df["close"]
    tr = pd.concat([df["high"] - df["low"], (df["high"] - c.shift()).abs(),
                    (df["low"] - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def avail(series: pd.Series, bar: pd.Timedelta, at: pd.DatetimeIndex) -> np.ndarray:
    """Value of a higher-TF series as known at each time in `at` (bar must have closed)."""
    s = series.copy()
    s.index = s.index + bar
    return s.reindex(s.index.union(at)).ffill().reindex(at).to_numpy()


def coin_frame(rec: dict, btc: dict) -> pd.DataFrame | None:
    m = rec.get("m15")
    h = rec["h1"]
    if m is None or len(m) < 200:
        return None
    m = m[~m.index.duplicated()].sort_index()
    t_close = m.index + pd.Timedelta(minutes=15)
    seg = (m.index.to_series().diff() != pd.Timedelta(minutes=15)).cumsum()
    f = pd.DataFrame({"open": m["open"].values, "high": m["high"].values, "low": m["low"].values,
                      "close": m["close"].values, "seg": seg.values}, index=t_close)
    g = f.groupby("seg")["close"]
    f["ema20_15"] = g.transform(lambda c: c.ewm(span=20, adjust=False).mean())
    f["rsi3_15"] = g.transform(lambda c: rsi(c, 3))
    f["hh12"] = f.groupby("seg")["high"].transform(lambda x: x.rolling(48, min_periods=4).max())
    # 1h (closed bars)
    H1 = pd.Timedelta(hours=1)
    c1 = h["close"]
    i1 = pd.DataFrame({"ema20": ema(c1, 20), "ema50": ema(c1, 50), "atr": atr(h), "rsi14": rsi(c1, 14),
                       "rsi3": rsi(c1, 3), "high": h["high"], "low": h["low"], "close": c1,
                       "prev_high": h["high"].shift(), "prev_low": h["low"].shift(),
                       "volx": h["volume"] / h["volume"].rolling(20).mean(),
                       "bbu": c1.rolling(20).mean() + 2 * c1.rolling(20).std(),
                       "g24": c1 / c1.shift(24) - 1, "g72": c1 / c1.shift(72) - 1,
                       "dvol": (h["volume"] * c1).rolling(24 * 20, min_periods=24).mean() * 24})
    r24 = i1["g24"]
    i1["z24"] = (r24 - r24.rolling(24 * 60, min_periods=24 * 10).mean()) / r24.rolling(24 * 60, min_periods=24 * 10).std()
    i1["volx_max12"] = i1["volx"].rolling(12).max()
    i1["g24_max12"] = i1["g24"].rolling(12).max()
    i1["z24_max12"] = i1["z24"].rolling(12).max()
    i1["above_bb_rsi"] = ((c1 > i1["bbu"]) & (i1["rsi14"] >= 80)).astype(float).rolling(12).max()
    for k in i1.columns:
        f[f"h_{k}"] = avail(i1[k], H1, f.index)
    # 4h from 1h (closed bars)
    h4 = h.resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    c4 = h4["close"]
    i4 = pd.DataFrame({"ema20": ema(c4, 20), "atr": atr(h4), "rsi14": rsi(c4, 14)})
    i4["rsi14_max3"] = i4["rsi14"].rolling(3).max()
    for k in i4.columns:
        f[f"q_{k}"] = avail(i4[k], pd.Timedelta(hours=4), f.index)
    # funding (per settlement) and open interest
    fund = rec.get("funding")
    f["fund_now"] = avail(fund, pd.Timedelta(0), f.index) if fund is not None and len(fund) else np.nan
    oi = rec.get("oi")
    if oi is not None and len(oi) > 30:
        oi = oi[~oi.index.duplicated()].sort_index().astype(float)
        f["oi_chg24"] = avail(oi / oi.shift(24) - 1, H1, f.index)
    else:
        f["oi_chg24"] = np.nan
    # BTC turning over (15m + 1h)
    for k in ("btc_down",):
        f[k] = btc["down"].reindex(btc["down"].index.union(f.index)).ffill().reindex(f.index).to_numpy()
    f["btc_up_trend"] = btc["trend_up"].reindex(btc["trend_up"].index.union(f.index)).ffill().reindex(f.index).to_numpy()
    f["funding_series"] = None
    return f


def btc_state(b15: pd.DataFrame) -> dict:
    t = b15.index + pd.Timedelta(minutes=15)
    c15 = pd.Series(b15["close"].values, index=t)
    e15 = ema(c15, 20)
    h1 = b15.resample("1h", label="left", closed="left").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    e1 = ema(h1["close"], 20)
    lower_high = h1["high"] < h1["high"].shift()
    k1 = pd.DataFrame({"below": (h1["close"] < e1), "lh": lower_high})
    k1.index = k1.index + pd.Timedelta(hours=1)
    k1 = k1.reindex(k1.index.union(t)).ffill().reindex(t)
    down = (c15 < e15).to_numpy() & k1["below"].fillna(False).to_numpy() & k1["lh"].fillna(False).to_numpy()
    d1 = b15["close"].resample("1D").last()
    trend = d1 > d1.rolling(50).mean()
    trend.index = trend.index + pd.Timedelta(days=1)
    return {"down": pd.Series(down, index=t), "trend_up": trend.astype(float)}


# ── setup definitions (overextended "ext" + "turn") ───────────────────────────
def ext_atr(f):
    peak = f["hh12"]
    return (peak - f["q_ema20"]) / f["q_atr"], (peak - f["h_ema20"]) / f["h_atr"]


def turn_core(f):
    lower_high = f["h_high"] < f["hh12"] * 0.999
    return (f["close"] < f["ema20_15"]) & (lower_high | (f["h_close"] < f["h_prev_low"]))


def v_core(f):
    e4, e1 = ext_atr(f)
    return (e4 >= 3) & (e1 >= 3), turn_core(f)


def v_zscore(f):
    return (f["h_z24_max12"] >= 3), turn_core(f)


def v_nfi(f):
    return (f["q_rsi14_max3"] >= 80), (f["h_rsi3"] < 50) & (f["close"] < f["ema20_15"])


def v_volclimax(f):
    return (f["h_volx_max12"] >= 8) & (f["h_g24_max12"] >= 0.30), turn_core(f)


def v_overlev(f):
    drop = 1 - f["close"] / f["hh12"]
    return (f["oi_chg24"] >= 0.30) & (f["fund_now"] > 0), (drop >= 0.03) & (drop <= 0.07)


def v_bbfade(f):
    return (f["h_above_bb_rsi"] >= 1), (f["h_close"] < f["h_bbu"]) & (f["close"] < f["ema20_15"])


VARIANTS = {"core: 3 ATR above 4h+1h EMA20": v_core,
            "z-score: 24h gain z>=3": v_zscore,
            "NFI: 4h RSI>=80, 1h RSI3 turns": v_nfi,
            "volume climax 8x + 30%/24h": v_volclimax,
            "overleverage: OI +30%, funding>0": v_overlev,
            "freqtrade: BB+RSI80 fade": v_bbfade}


# ── simulation ────────────────────────────────────────────────────────────────
def simulate(f: pd.DataFrame, i: int, fund: pd.Series | None, exit_kind="ema4h", hours=48) -> dict | None:
    entry = f["close"].iat[i]
    stop = f["hh12"].iat[i] + 0.25 * f["h_atr"].iat[i]
    risk = stop - entry
    if not np.isfinite(risk) or risk <= 0 or risk / entry > 0.5:
        return None
    target = {"ema4h": f["q_ema20"].iat[i], "ema50_1h": f["h_ema50"].iat[i], "trail": -np.inf}[exit_kind]
    if exit_kind != "trail" and (not np.isfinite(target) or target >= entry):
        return None
    seg = f["seg"].iat[i]
    hi, lo, cl, sg = f["high"].to_numpy(), f["low"].to_numpy(), f["close"].to_numpy(), f["seg"].to_numpy()
    trail = stop
    lowest = entry
    exit_p, why, j = None, "time", i
    last = min(len(f) - 1, i + hours * 4)
    for j in range(i + 1, last + 1):
        if sg[j] != seg:
            j -= 1
            break
        if hi[j] >= trail:
            exit_p, why = trail, ("stop" if trail >= stop else "trail")
            break
        if lo[j] <= target:
            exit_p, why = target, "target"
            break
        if exit_kind == "trail":
            lowest = min(lowest, lo[j])
            trail = min(trail, lowest + 2 * f["h_atr"].iat[j])
    if exit_p is None:
        exit_p = cl[j]
    t0, t1 = f.index[i], f.index[j]
    fund_r = 0.0
    if fund is not None and len(fund):
        rates = fund[(fund.index > t0) & (fund.index <= t1)]
        fund_r = float(rates.sum()) * entry / risk       # shorts receive +rate
    r = (entry - exit_p) / risk - COST * entry / risk + fund_r
    return {"entry_t": t0, "exit_t": t1, "entry": entry, "exit": exit_p, "stop": stop,
            "target": target, "r": r, "why": why, "fund_r": fund_r,
            "liquid": f["h_dvol"].iat[i] >= 2e6, "btc_down": bool(f["btc_down"].iat[i]),
            "btc_trend_up": bool(f["btc_up_trend"].iat[i] == 1.0)}


def run(frames, variant, btc_filter, exit_kind="ema4h", hours=48, mode="setup", attempts=1):
    out = []
    for sym, (f, eps, fund) in frames.items():
        ext, trn = variant(f)
        ok = (ext & trn).fillna(False).to_numpy()
        if btc_filter:
            ok &= f["btc_down"].fillna(False).to_numpy().astype(bool)
        exto = ext.fillna(False).to_numpy()
        for a, b in eps:
            w = np.flatnonzero((f.index >= a) & (f.index <= b))
            if not len(w):
                continue
            if mode == "setup":
                hits = w[ok[w]]
            elif mode == "no_turn":                       # baseline B
                hits = w[exto[w]]
            else:                                         # baseline A: random bar in the same pump
                # window — no knowledge of where the top is (that would be hindsight)
                hits = RNG.choice(w, size=1)
            k, done = 0, 0
            while k < len(hits) and done < attempts:
                t = simulate(f, int(hits[k]), fund, exit_kind, hours)
                if not t:
                    k += 1
                    continue
                t["sym"] = sym
                t["attempt"] = done + 1
                out.append(t)
                done += 1
                if t["why"] != "stop":                   # only retry after being stopped out
                    break
                k = int(np.searchsorted(hits, f.index.get_indexer([t["exit_t"]])[0] + 1))
    return out


def stats(tr):
    if not tr:
        return {"n": 0}
    r = np.array([t["r"] for t in sorted(tr, key=lambda t: t["exit_t"])])
    gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    eq = np.cumsum(r)
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else 0.0
    return {"n": len(r), "win": (r > 0).mean() * 100, "pf": gw / gl if gl else 99.0, "avgR": r.mean(),
            "totR": r.sum(), "usd": r.sum() * R_USD, "maxdd": (eq - np.maximum.accumulate(eq)).min(), "t": t}


def fmt(name, s, extra=""):
    if not s.get("n"):
        return f"| {name} | 0 | | | | | | | |{extra}"
    return (f"| {name} | {s['n']} | {s['win']:.0f}% | {s['pf']:.2f} | {s['avgR']:+.3f} | {s['totR']:+.1f} | "
            f"${s['usd']:+,.0f} | {s['maxdd']:.1f} | {s['t']:.2f} |{extra}")


HDR = "| variant | trades | win | PF | avg R | total R | total $ | max DD (R) | t |\n|---|---|---|---|---|---|---|---|---|"


def split(tr, mid):
    out = {}
    out["liquid (20d vol >= $2M)"] = [t for t in tr if t["liquid"]]
    out["small (< $2M)"] = [t for t in tr if not t["liquid"]]
    out["BTC trending up (daily > 50d)"] = [t for t in tr if t["btc_trend_up"]]
    out["BTC trending down"] = [t for t in tr if not t["btc_trend_up"]]
    out["BTC turning over at entry"] = [t for t in tr if t["btc_down"]]
    out["BTC not turning"] = [t for t in tr if not t["btc_down"]]
    for y in sorted({t["entry_t"].year for t in tr}):
        out[f"year {y}"] = [t for t in tr if t["entry_t"].year == y]
    out["first half"] = [t for t in tr if t["entry_t"] < mid]
    out["second half"] = [t for t in tr if t["entry_t"] >= mid]
    return out


def prior_tests() -> int:
    try:
        txt = subprocess.run(["git", "show", "origin/research/signal-families:research/intake/leaderboard.csv"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return max(0, len(txt.strip().splitlines()) - 1)
    except Exception:                                  # noqa: BLE001
        return 0


def main(pkl, report=None):
    import pickle
    d = pickle.loads(Path(pkl).read_bytes())
    btc = btc_state(d["btc15"])
    frames = {}
    for sym, rec in d["coins"].items():
        if not rec or not rec.get("episodes"):
            continue
        f = coin_frame(rec, btc)
        if f is not None:
            frames[sym] = (f, rec["episodes"], rec.get("funding"))
    n_eps = sum(len(v[1]) for v in frames.values())
    lines = [f"# Intraday overextension short — Bybit USDT perps\n",
             f"Coins with pump episodes: {len(frames)} · episodes: {n_eps} · 1R = ${R_USD:.2f} · "
             f"costs 0.36% + real funding.\n"]
    rows, all_tr = [], {}
    for name, v in VARIANTS.items():
        for bf in (False, True):
            tr = run(frames, v, bf)
            all_tr[(name, bf)] = tr
            rows.append((f"{name}{' + BTC turning' if bf else ''}", stats(tr)))
    n_tests = prior_tests() + len(rows) + 4
    t_need = float(norm.ppf(1 - 0.05 / (2 * n_tests)))
    lines += [f"Tests counted (prior leaderboard + these): {n_tests} → t-stat needed: {t_need:.2f}\n",
              "## Variants (target = 4h EMA20, 48h time stop)\n", HDR]
    lines += [fmt(n, s) for n, s in rows]

    best_key = max(all_tr, key=lambda k: stats(all_tr[k]).get("totR", -1e9) if stats(all_tr[k]).get("n", 0) >= 30 else -1e9)
    best_v, best_bf = VARIANTS[best_key[0]], best_key[1]
    best = all_tr[best_key]
    lines += [f"\n## Baselines vs the best variant ({best_key[0]}{' + BTC turning' if best_bf else ''})\n", HDR,
              fmt("best variant", stats(best)),
              fmt("A: random entry in the same pump windows", stats(run(frames, best_v, best_bf, mode="random"))),
              fmt("B: short as soon as overextended (no turn)", stats(run(frames, best_v, best_bf, mode="no_turn")))]
    lines += ["\n## Exit variants for the best setup\n", HDR]
    for lbl, ek, hrs in (("target 4h EMA20, 48h", "ema4h", 48), ("target 4h EMA20, 24h", "ema4h", 24),
                         ("target 1h EMA50, 48h", "ema50_1h", 48), ("trailing 2xATR(1h), 48h", "trail", 48)):
        lines.append(fmt(lbl, stats(run(frames, best_v, best_bf, ek, hrs))))
    if best:
        mid = sorted(t["entry_t"] for t in best)[len(best) // 2]
        lines += ["\n## Best variant split\n", HDR]
        lines += [fmt(k, stats(g)) for k, g in split(best, mid).items()]
        fsum = np.mean([t["fund_r"] for t in best])
        lines.append(f"\nAverage funding effect per trade: {fsum:+.3f} R (negative = shorts paid).\n")

    # biggest single pumps and what the setup did
    pumps = []
    for sym, (f, eps, _) in frames.items():
        g = f["h_g24"].to_numpy()
        if np.isfinite(g).any():
            k = int(np.nanargmax(g))
            pumps.append((g[k], sym, f.index[k]))
    pumps.sort(reverse=True)
    by_sym = {}
    for t in best:
        by_sym.setdefault(t["sym"], []).append(t)
    lines += ["\n## Biggest pumps in the data and what the best setup did\n",
              "| coin | 24h gain | when (UTC) | setup trade |\n|---|---|---|---|"]
    want = [p for p in pumps[:15]] + [p for p in pumps if p[1] in ("ORCA-USD", "OGN-USD") and p not in pumps[:15]]
    for g, sym, when in want:
        ts = [t for t in by_sym.get(sym, []) if abs((t["entry_t"] - when).total_seconds()) < 5 * 86400]
        desc = "; ".join(f"short {t['entry']:.5g} → {t['why']} {t['exit']:.5g} = {t['r']:+.2f}R"
                         for t in ts) or "no trade"
        lines.append(f"| {sym.replace('-USD', '')} | {g * 100:+.0f}% | {when:%Y-%m-%d %H:%M} | {desc} |")

    s = stats(best)
    verdict = ("PASS" if s.get("n", 0) >= 50 and s["pf"] > 1 and s["avgR"] > 0 and s["t"] >= t_need else "FAIL")
    lines.append(f"\n**Verdict for the best variant: {verdict}** (needs n ≥ 50, PF > 1, avg R > 0, "
                 f"t ≥ {t_need:.2f}; best t = {s.get('t', 0):.2f}).\n")
    txt = "\n".join(lines)
    print(txt)
    if report:
        Path(report).write_text(txt)
        with open(Path(report).with_suffix(".csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["sym", "entry_t", "exit_t", "entry", "exit", "stop", "target", "r", "why", "fund_r", "liquid", "btc_down"])
            for t in best:
                w.writerow([t[k] for k in ("sym", "entry_t", "exit_t", "entry", "exit", "stop", "target", "r", "why", "fund_r", "liquid", "btc_down")])


if __name__ == "__main__":
    main(*sys.argv[1:])
