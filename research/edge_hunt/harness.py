"""
Edge hunt harness: point in time universe, 1h path simulator, cost model, stats.

Conventions (same as the repo's research):
  * Costs: backtesting.crypto_validation._COST_PCT (0.36% round trip of notional)
    plus real funding while the position is open (shorts receive positive
    funding, longs pay it). Everything is in R, 1R = distance entry to stop.
  * Entry at the CLOSE of the signal bar (all features use closed bars only).
  * Path: 1h bars after entry. If stop and target are both inside one bar the
    stop is taken first (conservative). Time stop exits at that bar's close.
  * One open trade per coin per candidate variant; a new signal on the same coin
    is ignored until the previous trade has closed.
  * Universe, point in time: every Binance USDT perp (delisted ones included)
    whose trailing 30 day average daily quote volume, known at the signal bar,
    is >= MIN_DVOL, and with >= 30 days of history.
  * Sizing sanity: 1R = $12.50 = 25% of $50 margin, so leverage = 0.25 / stop%.
    Signals whose stop is tighter than MIN_STOP (leverage above 20x) are skipped.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
try:
    from backtesting.crypto_validation import _COST_PCT
    COST = _COST_PCT / 100.0
except Exception:                                  # noqa: BLE001
    COST = 0.0036

CACHE = Path(__file__).resolve().parent / "cache"
H1 = CACHE / "h1"
OI = CACHE / "oi"
MIN_DVOL = 10e6          # Binance 30d avg daily quote volume (Bybit is roughly 1/3 of Binance)
MIN_STOP = 0.0125        # 25% / 20x
MAX_STOP = 0.25
IS_END = pd.Timestamp("2025-07-01")
START = pd.Timestamp("2023-02-01")   # first month is warm up


# ── indicators ────────────────────────────────────────────────────────────────
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    c = df["close"]
    tr = pd.concat([df["high"] - df["low"], (df["high"] - c.shift()).abs(),
                    (df["low"] - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def resample(df, rule):
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
           "qv": "sum", "tbq": "sum"}
    agg = {k: v for k, v in agg.items() if k in df.columns}
    return df.resample(rule, label="left", closed="left").agg(agg).dropna(subset=["close"])


def to_h1(series: pd.Series, bar: pd.Timedelta, h1_index: pd.DatetimeIndex) -> np.ndarray:
    """Value of a series computed on bars of length `bar` (indexed by open time),
    as known at the CLOSE of each 1h bar in h1_index (no look ahead)."""
    s = series.copy()
    s.index = s.index + bar                 # available when its bar has closed
    at = h1_index + pd.Timedelta(hours=1)   # 1h bar close times
    return s.reindex(s.index.union(at)).ffill().reindex(at).to_numpy()


def load(sym: str) -> pd.DataFrame | None:
    p = H1 / f"{sym}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p).astype(float)
    df = df[~df.index.duplicated()].sort_index()
    if len(df) < 24 * 5:      # short lived (dead) listings are kept
        return None
    # regularise to a continuous hourly grid (gaps stay NaN and block trades)
    full = pd.date_range(df.index[0], df.index[-1], freq="1h")
    df = df.reindex(full)
    f8 = df["funding"] * (8.0 / df["fint"].ffill().fillna(8.0))
    df["fund8"] = f8
    df["dvol30"] = (df["qv"].rolling(24 * 30, min_periods=24 * 20).mean() * 24)
    df["age_h"] = np.arange(len(df))
    return df


def load_oi(sym: str, idx: pd.DatetimeIndex) -> pd.DataFrame | None:
    p = OI / f"{sym}.parquet"
    if not p.exists():
        return None
    o = pd.read_parquet(p).astype(float)
    o = o[~o.index.duplicated()].sort_index()
    return o.reindex(idx)


def symbols() -> list[str]:
    return sorted(p.stem for p in H1.glob("*.parquet"))


def universe_ok(df: pd.DataFrame) -> np.ndarray:
    return ((df["dvol30"] >= MIN_DVOL) & (df["age_h"] >= 24 * 30)).to_numpy()


# ── simulator ─────────────────────────────────────────────────────────────────
EXITS = {
    "T2R_48h": dict(kind="target", r=2.0, hours=48),
    "T1R_24h": dict(kind="target", r=1.0, hours=24),
    "trail_96h": dict(kind="trail", be_at=1.0, k_atr=2.0, hours=96),
    # multi day exits (round 2, new listings)
    "T2R_14d": dict(kind="target", r=2.0, hours=336),
    "trail_14d": dict(kind="trail", be_at=1.0, k_atr=4.0, hours=336),
    "hold_7d": dict(kind="target", r=1e9, hours=168),
}


def arrays(df: pd.DataFrame) -> dict:
    return {k: df[k].to_numpy() for k in ("open", "high", "low", "close", "funding", "atr1h")} | {"index": df.index}


def simulate(A: dict, i: int, side: int, stop: float, exit_cfg: dict,
             cost: float = COST, target_px: float | None = None) -> dict | None:
    """side +1 long, -1 short. Entry at close[i]. A = arrays(df)."""
    o, h, l, c, fund = A["open"], A["high"], A["low"], A["close"], A["funding"]
    entry = c[i]
    risk = (entry - stop) * side
    if not np.isfinite(risk) or risk <= 0:
        return None
    sp = risk / entry
    if sp < MIN_STOP or sp > MAX_STOP:
        return None
    hours = exit_cfg["hours"]
    last = min(len(c) - 1, i + hours)
    tgt = None
    if exit_cfg["kind"] == "target":
        tgt = entry + side * exit_cfg["r"] * risk if target_px is None else target_px
    a = A["atr1h"]
    cur_stop = stop
    best = entry
    fsum = 0.0
    exit_p, why, j = None, "time", i
    for j in range(i + 1, last + 1):
        if not np.isfinite(c[j]):
            exit_p, why = c[j - 1], "gap"
            j -= 1
            break
        # stop first (conservative), gap through stop fills at the open
        if side == 1 and l[j] <= cur_stop:
            exit_p, why = min(cur_stop, o[j]), "stop"
            break
        if side == -1 and h[j] >= cur_stop:
            exit_p, why = max(cur_stop, o[j]), "stop"
            break
        if np.isfinite(fund[j]):
            fsum += fund[j]
        if tgt is not None:
            if side == 1 and h[j] >= tgt:
                exit_p, why = max(tgt, o[j]), "target"
                break
            if side == -1 and l[j] <= tgt:
                exit_p, why = min(tgt, o[j]), "target"
                break
        if exit_cfg["kind"] == "trail":
            best = max(best, h[j]) if side == 1 else min(best, l[j])
            if (best - entry) * side >= exit_cfg["be_at"] * risk:
                ts = best - side * exit_cfg["k_atr"] * a[j]
                if side == 1:
                    cur_stop = max(cur_stop, entry, ts)
                else:
                    cur_stop = min(cur_stop, entry, ts)
    if exit_p is None:
        exit_p = c[j]
    gross = (exit_p - entry) * side / entry
    fund_ret = -side * fsum                  # long pays positive funding
    net = gross - cost + fund_ret
    return {"entry_t": A["index"][i] + pd.Timedelta(hours=1), "exit_t": A["index"][j] + pd.Timedelta(hours=1),
            "side": side, "entry": entry, "stop_pct": sp, "lev": 0.25 / sp,
            "r": net / sp, "r_gross": gross / sp, "fund_r": fund_ret / sp, "why": why, "exit_j": j}


def run_signals(df: pd.DataFrame, sig_idx: np.ndarray, side: int | np.ndarray, stops: np.ndarray,
                exit_cfg: dict, sym: str, cost: float = COST, targets: np.ndarray | None = None) -> list[dict]:
    out, busy_until = [], -1
    A = df if isinstance(df, dict) else arrays(df)
    sides = np.broadcast_to(np.asarray(side), sig_idx.shape)
    for n, i in enumerate(sig_idx):
        if i <= busy_until:
            continue
        tp = None if targets is None else targets[n]
        t = simulate(A, int(i), int(sides[n]), float(stops[n]), exit_cfg, cost, tp)
        if t is None:
            continue
        t["sym"] = sym
        busy_until = t.pop("exit_j")
        out.append(t)
    return out


# ── stats ─────────────────────────────────────────────────────────────────────
def stats(tr: pd.DataFrame) -> dict:
    if tr is None or len(tr) == 0:
        return {"n": 0}
    r = tr["r"].to_numpy()
    gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    pf = gw / gl if gl > 0 else np.inf
    # day clustered t-stat: trades entered the same UTC day are correlated
    d = tr.groupby(tr["entry_t"].dt.floor("D"))["r"].sum()
    td = d.mean() / d.std(ddof=1) * np.sqrt(len(d)) if len(d) > 2 and d.std() > 0 else np.nan
    srt = tr.sort_values("entry_t")
    half = len(srt) // 2
    h1, h2 = srt["r"].iloc[:half], srt["r"].iloc[half:]
    days = max(1.0, (tr["entry_t"].max() - tr["entry_t"].min()).days)
    return {"n": len(r), "win": float((r > 0).mean()), "pf": float(pf), "exp": float(r.mean()),
            "tot": float(r.sum()), "t_day": float(td), "h1": float(h1.sum()), "h2": float(h2.sum()),
            "pf_h1": _pf(h1), "pf_h2": _pf(h2), "per_wk": len(r) / days * 7,
            "fund_r": float(tr["fund_r"].mean()), "lev_med": float(tr["lev"].median()),
            "maxdd": float(_maxdd(srt["r"].to_numpy()))}


def _pf(x):
    x = np.asarray(x)
    gl = -x[x < 0].sum()
    return float(x[x > 0].sum() / gl) if gl > 0 else float("inf")


def _maxdd(r):
    eq = np.cumsum(r)
    return (np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max() if len(r) else 0.0


def gate(s: dict) -> bool:
    return s.get("n", 0) >= 25 and s["pf"] > 1 and s["h1"] > 0 and s["h2"] > 0


def fmt(s: dict) -> str:
    if not s.get("n"):
        return "n 0"
    return (f"n {s['n']:5d} win {s['win']:.0%} PF {s['pf']:.2f} exp {s['exp']:+.3f}R tot {s['tot']:+.1f}R "
            f"t {s['t_day']:+.2f} halves {s['h1']:+.1f}/{s['h2']:+.1f} wk {s['per_wk']:.1f} "
            f"fund {s['fund_r']:+.3f} lev {s['lev_med']:.1f} dd {s['maxdd']:.1f}")
