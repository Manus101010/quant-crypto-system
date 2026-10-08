"""
Shared harness for the new signal-family research (exhaustion fades, compression
breakouts, neutral grids).

Conventions match the production validation so results are comparable:
  * daily bars, entry on the CLOSE of the signal bar, stop checked before target
    on every later bar (conservative when both are touched the same day)
  * 0.36% round-trip cost deducted from every trade (backtesting.crypto_validation)
  * short return on notional = (entry - exit) / entry  (capped at +100%)
  * adoption bar = research/mr_shorts.py (PF > 1.0, n >= 25, PF > 1 in BOTH halves)
    PLUS expectancy in R > 0, because the live bot sizes by fixed risk, not notional
  * one open trade per coin per variant (no stacking)
  * liquidity floor: 20-day average quote volume >= $0.5M on the signal bar
    (the live scanner's AUTO_SCAN_PARAMS floor)

Nothing here imports the live scanner, so the research cannot change live alerts.
"""
from __future__ import annotations
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

COST_PCT = 0.36
MIN_VOL_USD = 0.5e6
MIN_N = 25


# ── data ──────────────────────────────────────────────────────────────────────
def load(path: str | Path, min_rows: int = 260):  # pass ~45 to keep young listings
    d = pickle.loads(Path(path).read_bytes())
    coins = {}
    for sym, df in d["coins"].items():
        if df is None or len(df) < min_rows:
            continue
        df = df[(df["close"] > 0) & df["high"].notna()].copy()
        df.index = pd.DatetimeIndex(df.index).normalize()
        coins[sym] = df
    btc = d["btc"].copy()
    btc.index = pd.DatetimeIndex(btc.index).normalize()
    return coins, btc


# ── indicators ────────────────────────────────────────────────────────────────
def rsi(c: pd.Series, n: int) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    """All indicators use data up to and including bar t only (no lookahead).
    'prev' columns exclude the current bar (e.g. the 20-day high BEFORE today)."""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    x = pd.DataFrame(index=df.index)
    x["o"], x["h"], x["l"], x["c"] = df["open"], h, l, c
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    x["tr"] = tr
    x["atr"] = tr.rolling(14).mean()
    x["tr3"] = tr.rolling(3).mean()
    x["ema9"] = c.ewm(span=9, adjust=False).mean()
    x["ema20"] = c.ewm(span=20, adjust=False).mean()
    x["sma20"] = c.rolling(20).mean()
    x["sma50"] = c.rolling(50).mean()
    x["sma200"] = c.rolling(200).mean()
    x["rsi14"] = rsi(c, 14)
    r5 = c / c.shift(5) - 1
    x["z5"] = (r5 - r5.rolling(90).mean()) / r5.rolling(90).std()
    x["ret120"] = c / c.shift(120) - 1
    std20 = c.rolling(20).std()
    x["bbw"] = 4 * std20 / x["sma20"]
    x["bbw_pct"] = x["bbw"].rolling(180).rank(pct=True)
    x["hh20p"] = h.rolling(20).max().shift(1)
    x["ll20p"] = l.rolling(20).min().shift(1)
    x["hh55p"] = h.rolling(55).max().shift(1)
    x["ll55p"] = l.rolling(55).min().shift(1)
    x["volr"] = v / v.rolling(20).mean().shift(1)
    x["qv"] = c * v                                        # daily $ volume
    x["qvol20"] = x["qv"].rolling(20).mean()
    # Kaufman efficiency ratio: 1 = straight line, ~0 = pure chop
    x["er20"] = (c - c.shift(20)).abs() / c.diff().abs().rolling(20).sum()
    x["stretch"] = (c - x["ema20"]) / x["atr"]          # ATR units from the mean
    return x


def btc_context(btc: pd.DataFrame) -> pd.DataFrame:
    c = btc["close"]
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    lab = pd.Series("MIXED", index=c.index)
    lab[(c > s200) & (s50 > s200) & (c > s50)] = "UP"
    lab[(c < s200) & (s50 < s200) & (c < s50)] = "DOWN"
    return pd.DataFrame({"btc_regime": lab, "btc_up_200_50": (c > s200) & (c > s50)})


def breadth50(coins: dict) -> pd.Series:
    closes = pd.DataFrame({s: df["close"] for s, df in coins.items()})
    ma = closes.rolling(50).mean()
    return (closes > ma).sum(axis=1) / ma.notna().sum(axis=1)


# ── trade simulation ──────────────────────────────────────────────────────────
@dataclass
class Plan:
    direction: str            # "long" | "short"
    stop: float
    target: float | None      # None = no fixed target
    trail_atr: float | None   # trailing stop distance in ATR (None = fixed stop)
    max_hold: int


def simulate(x: pd.DataFrame, i: int, plan: Plan) -> dict | None:
    h, l, c = x["h"].values, x["l"].values, x["c"].values
    atr = float(x["atr"].iat[i])
    entry = float(c[i])
    short = plan.direction == "short"
    stop = plan.stop
    risk = (stop - entry) if short else (entry - stop)
    if not np.isfinite(risk) or risk <= 0 or atr <= 0:
        return None
    n, exit_p, reason, k = len(c), None, "time", 0
    for k in range(1, plan.max_hold + 1):
        j = i + k
        if j >= n:
            k -= 1
            break
        if short:
            if h[j] >= stop:
                exit_p, reason = stop, "stop"; break
            if plan.target is not None and l[j] <= plan.target:
                exit_p, reason = plan.target, "target"; break
            if plan.trail_atr:
                stop = min(stop, c[j] + plan.trail_atr * atr)
        else:
            if l[j] <= stop:
                exit_p, reason = stop, "stop"; break
            if plan.target is not None and h[j] >= plan.target:
                exit_p, reason = plan.target, "target"; break
            if plan.trail_atr:
                stop = max(stop, c[j] - plan.trail_atr * atr)
    if exit_p is None:
        if k <= 0:
            return None                      # signal on the last bar: no outcome yet
        exit_p = float(c[i + k])
    move = (entry - exit_p) if short else (exit_p - entry)
    ret = move / entry * 100
    return {"ret_pct": ret, "r_mult": move / risk, "bars": k, "reason": reason,
            "entry": x.index[i], "exit": x.index[min(i + max(k, 1), n - 1)],
            "risk_pct": risk / entry * 100}


def apply_costs(trades: list[dict], cost: float = COST_PCT) -> list[dict]:
    out = []
    for t in trades:
        t = dict(t)
        c = t.get("cost", cost)
        t["r_mult"] -= c / t["risk_pct"]      # cost expressed in R
        t["ret_pct"] -= c
        out.append(t)
    return out


def tiered_cost(x: pd.DataFrame, i: int) -> float:
    """Round-trip cost by liquidity: thin coins slip more. >= $2M a day: 0.36%,
    $0.5M to $2M: 0.80% (small caps)."""
    return COST_PCT if x["qvol20"].iat[i] >= 2e6 else 0.80


def run_signals(coins_ind: dict, signal_fn, plan_fn, extra=None, min_i: int = 200,
                cost_fn=None, min_qv: float = MIN_VOL_USD) -> list[dict]:
    """signal_fn(x) -> boolean Series; plan_fn(x, i) -> Plan | None.
    One open trade per coin: signals while a trade is open are skipped.
    min_i = bars of history required before the first signal (200 for setups that
    use the 200 SMA; small-cap / new-listing setups can use ~40).
    cost_fn(x, i) -> round-trip cost %; default flat 0.36%."""
    trades = []
    for sym, x in coins_ind.items():
        sig = signal_fn(x)
        sig = sig & (x["qvol20"] >= min_qv)
        busy_until = -1
        for i in np.flatnonzero(sig.fillna(False).values):
            if i <= busy_until or i < min_i:
                continue
            p = plan_fn(x, i)
            if p is None:
                continue
            t = simulate(x, i, p)
            if t is None:
                continue
            t["sym"] = sym
            t["cost"] = cost_fn(x, i) if cost_fn else COST_PCT
            if extra is not None:
                t.update(extra(x, i))
            busy_until = i + t["bars"]
            trades.append(t)
    return apply_costs(trades)


# ── statistics ────────────────────────────────────────────────────────────────
def pf(trades) -> float:
    gw = sum(t["ret_pct"] for t in trades if t["ret_pct"] > 0)
    gl = abs(sum(t["ret_pct"] for t in trades if t["ret_pct"] <= 0))
    return gw / gl if gl else (99.0 if gw else 0.0)


def max_dd_r(trades) -> float:
    if not trades:
        return 0.0
    eq = np.cumsum([t["r_mult"] for t in sorted(trades, key=lambda t: t["exit"])])
    return float((eq - np.maximum.accumulate(np.maximum(eq, 0))).min())


def stats(trades: list[dict], split_date=None) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "pf": 0.0, "win": 0.0, "expR": 0.0, "totR": 0.0, "ddR": 0.0,
                "pf1": 0.0, "pf2": 0.0, "n1": 0, "n2": 0, "pass": False}
    if split_date is None:
        split_date = sorted(t["entry"] for t in trades)[n // 2]
    a = [t for t in trades if t["entry"] < split_date]
    b = [t for t in trades if t["entry"] >= split_date]
    s = {"n": n, "pf": pf(trades), "win": 100 * sum(t["ret_pct"] > 0 for t in trades) / n,
         "expR": float(np.mean([t["r_mult"] for t in trades])),
         "totR": float(np.sum([t["r_mult"] for t in trades])), "ddR": max_dd_r(trades),
         "pf1": pf(a), "pf2": pf(b), "n1": len(a), "n2": len(b)}
    # PF on % returns (equal notional, like production) AND positive expectancy in R
    # (fixed-risk sizing, like the live bot) must both hold, in both halves for PF.
    s["pass"] = (s["pf"] > 1.0 and n >= MIN_N and s["pf1"] > 1.0 and s["pf2"] > 1.0
                 and s["expR"] > 0)
    return s


def by(trades, key) -> dict:
    g: dict = {}
    for t in trades:
        g.setdefault(key(t), []).append(t)
    return g


def row(name: str, s: dict) -> str:
    return (f"| {name} | {s['n']} | {s['pf']:.2f} | {s['win']:.0f}% | {s['expR']:+.3f} | "
            f"{s['totR']:+.0f} | {s['ddR']:.0f} | {s['pf1']:.2f} | {s['pf2']:.2f} | "
            f"{'PASS' if s['pass'] else 'fail'} |")


HEADER = ("| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |\n"
          "|---|---|---|---|---|---|---|---|---|---|")


def prepare(path, min_rows: int = 260):
    """Load history and compute indicators + BTC context for every coin."""
    coins, btc = load(path, min_rows)
    ctx = btc_context(btc)
    br = breadth50(coins)
    out = {}
    for sym, df in coins.items():
        x = indicators(df)
        x = x.join(ctx, how="left")
        x["breadth50"] = br.reindex(x.index)
        out[sym] = x
    return out, btc


def tag(x: pd.DataFrame, i: int) -> dict:
    """Context recorded on every trade for the regime splits."""
    return {"btc": x["btc_regime"].iat[i] if isinstance(x["btc_regime"].iat[i], str) else "NA",
            "above200": bool(x["c"].iat[i] > x["sma200"].iat[i]),
            "year": x.index[i].year}
