"""
"Your setup" research core: the trader's own discretionary edge, codified.

  A  ROLLOVER SHORT     coin ran up hard (>= X% from its N day base to a peak inside the
                        last 72h, or the peak sat >= k ATR(4h) above the 4h EMA50), then a
                        1h or 4h breakdown trigger: close below the prior 5 bar swing low
                        (SW), first close below EMA20 of that timeframe (EMA), or a lower
                        high confirmed (pivot high below the peak, then close below the
                        swing low between them) (LH). Tight stop above the local high
                        (max high of the last 3 trigger timeframe bars + 0.1 ATR(1h)).
  B  CAPITULATION LONG  exact mirror: dumped >= X% from an N day top to a trough inside the
                        last 72h (or trough <= k ATR(4h) below 4h EMA50), then reclaim:
                        close above the prior 5 bar swing high, first close above EMA20,
                        or a higher low confirmed. Stop below the local low.
  C  TREND PULLBACK     strong 4h trend (4h close > EMA20 > EMA50, EMA50 rising over 6 4h
                        bars, 7d return >= +Y%), 1h pullback that touched the 1h EMA20 (or
                        4h EMA20) in the last 3 bars, entry on the first 1h close above the
                        prior 1h high and above the 1h EMA20. Mirror for shorts. Stop
                        beyond the 6h pullback extreme + 0.1 ATR(1h).

EXIT (his, exactly): initial tight stop; once the price is +ACT% in profit (best price
reached), a TRAIL% trailing stop follows the best price (Bybit native trailing stop,
which sits alongside the initial stop: whichever is tighter applies). 7 day time stop
(he "watches carefully"; nothing in the data runs that long in practice).

Fills on 1h bars: stop checked first with the level known at the start of the bar
(gap through fills at the open). Then the bar's extreme updates the best price; if the
bar CLOSED beyond the new trail level, the trail must have been hit inside the bar
after the new extreme, so the trade exits at that level (not optimistic). A wick
through the new level that closes back inside is assumed NOT hit (slightly optimistic,
1h bars cannot tell; flagged in the report).

Costs: R = (price move - cost + funding) / stop%, cost 0.36% (taker + slippage, repo
standard) or 0.11% (limit entry maker 0.02% + taker stop 0.055% + slippage). Funding:
real Binance prints, shorts receive positive funding. Leverage does not change R.
Data: Binance USDT-M 1h klines + funding, delisted coins included, 2021-06..2026-10-26.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numba
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BUM = Path("/tmp/claude-0/-home-claude/f9afb357-b96a-5c99-93e3-0ac2bb39e920/scratchpad/bum")
MIN_DVOL = 10e6
MIN_STOP, MAX_STOP = 0.010, 0.08
COSTS = {"taker": 0.0036, "maker": 0.0011}
PRE_START = pd.Timestamp("2021-08-01")
IS_START, IS_END = pd.Timestamp("2023-01-01"), pd.Timestamp("2025-07-01")
DATA_END = pd.Timestamp("2026-10-27")
STOCKS = {"PAXG", "XAUT", "BTCDOM", "DEFI", "FOOTBALL", "BLUEBIRD", "AMD", "APLD", "TSLA", "NVDA",
          "AAPL", "MSTR", "COIN", "HOOD", "META", "GOOGL", "AMZN", "MSFT", "PLTR", "CRCL", "SPY",
          "QQQ", "XAU", "XAG", "INTC", "ORCL", "NFLX", "BABA", "USDC", "BUSD", "TUSD", "USDP",
          "FDUSD", "USDE", "DAI", "USD1", "RLUSD", "EUR", "GBP", "AUD", "XPT", "XPD", "OPENAI"}


def universe_symbols() -> list[str]:
    bybit = {s.replace("-USD", "") for s in json.loads((ROOT / "data/bybit_perps.json").read_text())["symbols"]}
    out = []
    for p in sorted((BUM / "k1h").glob("*.parquet")):
        s = p.stem
        b = s[:-4]
        if not s.endswith("USDT") or b in STOCKS:
            continue
        if b in bybit or b.replace("1000", "") in bybit or b in ("MATIC", "RNDR"):
            out.append(s)
            continue
        idx = pd.read_parquet(p, columns=["close"]).index
        if len(idx) and idx[-1] < pd.Timestamp("2026-09-01"):     # delisted crypto, keep
            out.append(s)
    return out


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def load(sym: str) -> pd.DataFrame | None:
    p = BUM / "k1h" / f"{sym}.parquet"
    k = pd.read_parquet(p)
    k = k[~k.index.duplicated()].sort_index()
    live = np.flatnonzero(k["volume"].values > 0)
    if len(live) < 24 * 40:
        return None
    k = k.iloc[:live[-1] + 1]
    full = pd.date_range(k.index[0], k.index[-1], freq="1h")
    k = k.reindex(full)
    fp = BUM / "fund" / f"{sym}.parquet"
    f = pd.read_parquet(fp)["rate"] if fp.exists() else pd.Series(dtype=float)
    if len(f):
        f.index = pd.DatetimeIndex(f.index).floor("h")
        f = f.groupby(level=0).sum()
    # print at hh:00 is paid by positions held over that instant -> bar opening hh-1
    k["fund"] = f.reindex(k.index + pd.Timedelta(hours=1)).fillna(0.0).to_numpy() if len(f) else 0.0
    k["dvol30"] = k["quote_volume"].rolling(24 * 30, min_periods=24 * 20).mean() * 24
    k["age_h"] = np.arange(len(k))
    k["dead"] = k.index[-1] < pd.Timestamp("2026-10-20")
    return k


def h4_frame(k: pd.DataFrame) -> pd.DataFrame:
    h4 = k[["open", "high", "low", "close", "volume"]].resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    # a 4h bar is complete only if all 4 hours exist
    cnt = k["close"].resample("4h", label="left", closed="left").count()
    h4 = h4[cnt == 4]
    return h4


def to_h1(series: pd.Series, bar: pd.Timedelta, idx: pd.DatetimeIndex) -> np.ndarray:
    """Value known at the CLOSE of each 1h bar (no look ahead)."""
    s = series.copy()
    s.index = s.index + bar
    at = idx + pd.Timedelta(hours=1)
    return s.reindex(s.index.union(at)).ffill().reindex(at).to_numpy()


def h4_pos_in_h1(h4idx: pd.DatetimeIndex, idx: pd.DatetimeIndex) -> np.ndarray:
    """1h positions whose close equals each 4h bar's close (-1 if missing)."""
    pos = idx.get_indexer(h4idx + pd.Timedelta(hours=3))
    return pos


# ── numba helpers ─────────────────────────────────────────────────────────────
@numba.njit(cache=True)
def extreme_move(h, l, P, base_min, side):
    """side -1 (run up): for each i, k = argmax high in [i-P+1, i]; value = high[k]/base_min[k]-1.
    side +1 (dump): k = argmin low; value = 1 - low[k]/base_max[k] (base_min holds rolling max)."""
    n = len(h)
    out = np.full(n, np.nan)
    pk = np.full(n, -1)
    for i in range(P, n):
        k = -1
        best = np.nan
        for j in range(i - P + 1, i + 1):
            if side == -1:
                if np.isfinite(h[j]) and (k < 0 or h[j] > best):
                    best, k = h[j], j
            else:
                if np.isfinite(l[j]) and (k < 0 or l[j] < best):
                    best, k = l[j], j
        if k < 0 or not np.isfinite(base_min[k]):
            continue
        pk[i] = k
        if side == -1:
            out[i] = best / base_min[k] - 1.0
        else:
            out[i] = 1.0 - best / base_min[k]
    return out, pk


@numba.njit(cache=True)
def lower_high_break(h, l, c, P, side):
    """On bars of one timeframe. side -1: peak = max high in last P bars; latest confirmed
    pivot high j (2 bars each side) after the peak, below it; swing = min low between peak
    and j; fire on the first close below swing. side +1: mirror (higher low, reclaim)."""
    n = len(c)
    out = np.zeros(n, dtype=np.bool_)
    for i in range(P, n):
        k = i - P + 1
        for j in range(i - P + 1, i + 1):
            if side == -1:
                if h[j] > h[k]:
                    k = j
            else:
                if l[j] < l[k]:
                    k = j
        piv = -1
        for j in range(i - 2, k, -1):
            if j - 2 < 0 or j + 2 > i:
                continue
            if side == -1:
                if h[j] < h[k] and h[j] >= h[j - 1] and h[j] >= h[j - 2] and h[j] > h[j + 1] and h[j] > h[j + 2]:
                    piv = j
                    break
            else:
                if l[j] > l[k] and l[j] <= l[j - 1] and l[j] <= l[j - 2] and l[j] < l[j + 1] and l[j] < l[j + 2]:
                    piv = j
                    break
        if piv < 0:
            continue
        sw = l[k] if side == -1 else h[k]
        for j in range(k, piv + 1):
            if side == -1:
                sw = min(sw, l[j])
            else:
                sw = max(sw, h[j])
        if side == -1:
            if c[i] < sw and c[i - 1] >= sw:
                out[i] = True
        else:
            if c[i] > sw and c[i - 1] <= sw:
                out[i] = True
    return out


@numba.njit(cache=True)
def sim(o, h, l, c, fund, i, side, stop, act, trail, tgt_r, max_bars, cost, dead):
    """Entry at close[i]. side +1 long / -1 short. act, trail as fractions (nan trail = no
    trail). tgt_r: fixed R target (nan none). Returns exit_j, net_pct, stop_pct, code, mfe_pct.
    code 0 stop, 1 trail, 2 target, 3 time, 4 delisted end, 5 open at data end (drop), 6 gap."""
    entry = c[i]
    risk = (entry - stop) * side
    sp = risk / entry
    n = len(c)
    st = stop
    best = entry
    active = act <= 0.0
    tgt = entry + side * tgt_r * risk if np.isfinite(tgt_r) else np.nan
    fs = 0.0
    code = 3
    ex = np.nan
    j = i
    last = min(n - 1, i + max_bars)
    for j in range(i + 1, last + 1):
        if not np.isfinite(c[j]):
            ex = c[j - 1]
            j -= 1
            code = 6
            break
        # 1) stop known at bar start
        if side == 1:
            if o[j] <= st:
                ex, code = o[j], (1 if st > stop else 0)
                break
            if l[j] <= st:
                ex, code = st, (1 if st > stop else 0)
                break
        else:
            if o[j] >= st:
                ex, code = o[j], (1 if st < stop else 0)
                break
            if h[j] >= st:
                ex, code = st, (1 if st < stop else 0)
                break
        fs += fund[j]
        # 2) fixed target
        if np.isfinite(tgt):
            if (side == 1 and h[j] >= tgt) or (side == -1 and l[j] <= tgt):
                ex, code = tgt, 2
                break
        # 3) trail: update best with this bar's extreme
        if np.isfinite(trail):
            if side == 1:
                best = max(best, h[j])
            else:
                best = min(best, l[j])
            if not active and (best - entry) * side >= act * entry:
                active = True
            if active:
                lvl = best * (1.0 - trail) if side == 1 else best * (1.0 + trail)
                if side == 1:
                    if lvl > st:
                        st = lvl
                    if c[j] <= st and st > stop:     # crossed after the new high, inside the bar
                        ex, code = st, 1
                        break
                else:
                    if lvl < st:
                        st = lvl
                    if c[j] >= st and st < stop:
                        ex, code = st, 1
                        break
    if code == 3:
        ex = c[j]
        if j < i + max_bars:            # ran out of data
            code = 4 if dead else 5
    gross = (ex - entry) * side / entry
    net = gross - cost - side * fs
    return j, net, sp, code, gross
