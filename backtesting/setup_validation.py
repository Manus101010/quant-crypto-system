"""
Walk-Forward Setup Validation Backtester
=========================================

Measures the REAL historical edge of each scanner setup so conviction scores
can be calibrated from data instead of from literature.

Method
------
For a universe of tickers (default: scanner.DEFAULT_STOCK_WATCHLIST):
  1. Download ~2y daily OHLC via yfinance.
  2. Walk each ticker bar-by-bar with an expanding window. At each bar `i`
     (where enough history exists), compute the SAME indicators the live
     scanner uses, using ONLY data up to and including bar `i` (no lookahead),
     and call `skills.scanner.classify_setup`.
  3. When the setup is an actionable BUY, simulate the trade forward over the
     SUBSEQUENT bars using an ATR-based stop (2×ATR) and a structure target
     (BB midline, else +2R), holding up to `max_hold` bars.
  4. Record the outcome (win/loss, return %, R-multiple, bars held).
  5. Aggregate per setup_label: sample size, win rate, avg win/loss %,
     profit factor, expectancy (avg R), median bars held.

Lookahead bias is avoided because classification only ever sees `close[:i+1]`
(etc.), and the trade is simulated on bars strictly after `i`.

Import-clean: heavy deps (yfinance) are imported lazily inside functions.
"""
from __future__ import annotations

import statistics
from typing import Iterable

import numpy as np
import pandas as pd

from skills.scanner import (
    DEFAULT_STOCK_WATCHLIST,
    classify_setup,
    trade_suggestion,
    _rsi,
    _rsi2,
    _bollinger,
    _zscore,
    _williams_r,
    _atr,
)
from utils.logger import get_logger

log = get_logger(__name__)

# Setups whose trade_suggestion action is a BUY — only these are simulated.
# (SELL/EXIT, WAIT and neutral labels are not entries.)
ACTIONABLE_BUY_SETUPS = {
    "RSI-2 Pullback (Connors)",
    "Oversold in Uptrend",
    "BB Bounce Setup",
    "Williams %R Oversold",
    "Momentum Runner",
    "Confirmed Uptrend",
    "Pullback to SMA50",
    "Counter-Trend Bounce",
    "Donchian Breakout (55d)",
    "Volume Breakout",
    "Squeeze Breakout",
    "Relative Strength Leader",
}

# Minimum history before we start classifying a bar.
# 200 SMA + a little buffer so the long-term trend filter is meaningful.
_MIN_HISTORY = 210


# ── Per-bar indicator computation (point-in-time, no lookahead) ───────────────

def _indicators_at(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    i: int,
    volume: pd.Series | None = None,
    btc_close: pd.Series | None = None,
) -> dict | None:
    """
    Compute the scanner's indicators using ONLY bars [0 .. i] (inclusive).
    Returns None if not enough history. When `volume` is given, also computes the
    breakout/volume/squeeze features; when `btc_close` (aligned to `close`) is
    given, computes 30d relative strength vs BTC so that leg can be validated.
    """
    if i < _MIN_HISTORY:
        return None

    s  = close.iloc[: i + 1]
    h  = high.iloc[: i + 1]
    lo = low.iloc[: i + 1]

    if len(s) < 63:
        return None

    price  = float(s.iloc[-1])
    sma50  = float(s.iloc[-50:].mean())
    sma200 = float(s.iloc[-200:].mean()) if len(s) >= 200 else sma50
    base63 = float(s.iloc[-63])
    mom3m  = (price - base63) / base63 * 100 if base63 else 0.0
    rsi    = _rsi(s, 14)
    rsi_2  = _rsi2(s)

    bb_upper, bb_mid, bb_lower, bb_pct, _bb_bw = _bollinger(s, 20, 2.0)
    zsc   = _zscore(s, 20)
    wil_r = _williams_r(s, 14)
    atr   = _atr(h, lo, s, 14) if len(h) and len(lo) else None

    out = {
        "price": price, "sma50": sma50, "sma200": sma200, "mom3m": mom3m,
        "rsi": rsi, "rsi2": rsi_2,
        "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower, "bb_pct": bb_pct,
        "zscore": zsc, "williams_r": wil_r, "atr": atr,
        "vol_ratio": None, "donch_hi20": None, "donch_hi55": None,
        "donch_lo20": None, "squeeze": None, "rel_strength": None,
    }
    if volume is not None:
        from skills.scanner import breakout_signals
        v = volume.iloc[: i + 1]
        out.update(breakout_signals(s, h, v, lo))
    if btc_close is not None and i >= 30:
        b_now, b_prev = btc_close.iloc[i], btc_close.iloc[i - 30]
        if b_now == b_now and b_prev and b_prev == b_prev and base63:
            coin_ret = (price / float(s.iloc[-31]) - 1) * 100 if len(s) >= 31 else 0.0
            btc_ret = (float(b_now) / float(b_prev) - 1) * 100
            out["rel_strength"] = coin_ret - btc_ret
    return out


# ── Forward trade simulation ──────────────────────────────────────────────────

def _simulate_trade(
    ind: dict,
    setup_label: str,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    entry_i: int,
    max_hold: int,
    atr_stop_mult: float = 2.0,
) -> dict | None:
    """
    Simulate a long trade entered at the close of `entry_i`.

    Stop  = entry - atr_stop_mult * ATR   (fallback 3% if no ATR)
    Target= BB midline if it's above entry, else entry + 2R (R = entry-stop)

    Walks bars entry_i+1 .. entry_i+max_hold. Intrabar: if the low pierces the
    stop, exit at stop; elif the high reaches the target, exit at target.
    (Stop checked first = conservative.) If neither hits, exit at the close of
    the final held bar.

    Returns a result dict, or None if there are no forward bars to simulate.
    """
    entry = ind["price"]
    atr   = ind["atr"]

    if atr and atr > 0:
        stop = entry - atr_stop_mult * atr
    else:
        stop = entry * 0.97
    risk = entry - stop
    if risk <= 0:
        return None

    bb_mid = ind["bb_mid"]
    if bb_mid is not None and bb_mid > entry:
        target = bb_mid
    else:
        target = entry + 2.0 * risk

    n = len(close)
    last_i = min(entry_i + max_hold, n - 1)
    if last_i <= entry_i:
        return None

    exit_price = None
    exit_reason = "time"
    bars_held = 0

    for j in range(entry_i + 1, last_i + 1):
        bars_held = j - entry_i
        hi = float(high.iloc[j])
        lo = float(low.iloc[j])
        if lo <= stop:
            exit_price = stop
            exit_reason = "stop"
            break
        if hi >= target:
            exit_price = target
            exit_reason = "target"
            break

    if exit_price is None:
        exit_price = float(close.iloc[last_i])
        exit_reason = "time"
        bars_held = last_i - entry_i

    ret_pct = (exit_price - entry) / entry * 100.0
    r_mult  = (exit_price - entry) / risk
    return {
        "setup": setup_label,
        "entry": entry,
        "exit": exit_price,
        "stop": stop,
        "target": target,
        "ret_pct": ret_pct,
        "r_mult": r_mult,
        "bars_held": bars_held,
        "reason": exit_reason,
        "win": ret_pct > 0,
    }


# ── Per-ticker walk ───────────────────────────────────────────────────────────

def _walk_ticker(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    max_hold: int,
    step: int,
    cooldown: int,
    volume: pd.Series | None = None,
    btc_close: pd.Series | None = None,
) -> list[dict]:
    """
    Walk one ticker bar-by-bar. Returns a list of simulated trade records.

    `step`     : evaluate every `step` bars (1 = every bar).
    `cooldown` : after firing a trade, skip this many bars before re-evaluating
                 the same setup pipeline (avoids stacking near-identical signals
                 on consecutive bars).
    `btc_close`: BTC daily closes for the relative-strength leg (aligned here).
    """
    close = close.dropna()
    high  = high.reindex(close.index)
    low   = low.reindex(close.index)
    if volume is not None:
        volume = volume.reindex(close.index)
    if btc_close is not None:
        btc_close = btc_close.reindex(close.index).ffill()
    n = len(close)
    if n < _MIN_HISTORY + 5:
        return []

    trades: list[dict] = []
    # Leave room for at least 1 forward bar.
    i = _MIN_HISTORY
    last_fire = -10_000
    while i < n - 1:
        ind = _indicators_at(close, high, low, i, volume, btc_close)
        if ind is None:
            i += step
            continue

        label, _desc, _cat = classify_setup(
            ind["price"], ind["sma50"], ind["sma200"],
            ind["rsi"], ind["mom3m"],
            ind["bb_pct"], ind["zscore"], ind["williams_r"], ind["rsi2"],
            vol_ratio=ind["vol_ratio"], donch_hi20=ind["donch_hi20"],
            donch_hi55=ind["donch_hi55"], donch_lo20=ind["donch_lo20"],
            squeeze=ind["squeeze"], rel_strength=ind["rel_strength"],
        )

        if label in ACTIONABLE_BUY_SETUPS and (i - last_fire) >= cooldown:
            # Confirm trade_suggestion really yields a BUY action.
            ts = trade_suggestion(
                label, ind["price"], ind["sma50"], ind["sma200"],
                ind["bb_upper"], ind["bb_mid"], ind["bb_lower"],
                ind["rsi"], ind["mom3m"], ind["atr"],
            )
            if ts.get("action") == "BUY":
                res = _simulate_trade(
                    ind, label, high, low, close, i, max_hold,
                )
                if res is not None:
                    trades.append(res)
                    last_fire = i
        i += step

    return trades


# ── Aggregation ───────────────────────────────────────────────────────────────

def _aggregate(trades: list[dict]) -> dict[str, dict]:
    """Aggregate raw trade records into per-setup stats."""
    by_setup: dict[str, list[dict]] = {}
    for t in trades:
        by_setup.setdefault(t["setup"], []).append(t)

    stats: dict[str, dict] = {}
    for label, recs in by_setup.items():
        n = len(recs)
        wins   = [r for r in recs if r["win"]]
        losses = [r for r in recs if not r["win"]]
        n_win  = len(wins)

        win_rate = n_win / n if n else 0.0
        avg_win  = float(np.mean([r["ret_pct"] for r in wins]))   if wins   else 0.0
        avg_loss = float(np.mean([r["ret_pct"] for r in losses])) if losses else 0.0

        gross_win  = sum(r["ret_pct"] for r in wins)
        gross_loss = abs(sum(r["ret_pct"] for r in losses))
        if gross_loss > 0:
            profit_factor = gross_win / gross_loss
        elif gross_win > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        expectancy_r = float(np.mean([r["r_mult"] for r in recs]))
        avg_ret      = float(np.mean([r["ret_pct"] for r in recs]))
        med_bars     = float(statistics.median([r["bars_held"] for r in recs]))
        n_target = sum(1 for r in recs if r["reason"] == "target")
        n_stop   = sum(1 for r in recs if r["reason"] == "stop")
        n_time   = sum(1 for r in recs if r["reason"] == "time")

        stats[label] = {
            "n":             n,
            "win_rate":      round(win_rate, 4),
            "avg_win":       round(avg_win, 3),
            "avg_loss":      round(avg_loss, 3),
            "avg_ret":       round(avg_ret, 3),
            "profit_factor": (round(profit_factor, 3)
                              if profit_factor != float("inf") else None),
            "expectancy_r":  round(expectancy_r, 4),
            "median_bars_held": med_bars,
            "exits": {"target": n_target, "stop": n_stop, "time": n_time},
        }
    return stats


# ── Recommended base conviction scores ────────────────────────────────────────

def recommend_base_scores(stats: dict[str, dict], min_n: int = 30) -> dict[str, dict]:
    """
    Map empirical profit factor / expectancy to a suggested 0-100 base
    conviction per setup (intended to replace scanner._SETUP_BASE).

    Score model (0-100):
        base 50 (coin-flip anchor)
        + profit-factor lift : (PF - 1) scaled, capped at +28
        + expectancy lift    : expectancy_r scaled, capped at +14
        + win-rate lift       : (win_rate - 0.5) scaled, capped at +8
    Then clamped to [5, 95].

    Setups with n < `min_n` are flagged `trusted: False` and their score is
    pulled toward a neutral 40 (shrinkage) since the sample is too thin.
    """
    out: dict[str, dict] = {}
    for label, s in stats.items():
        pf = s["profit_factor"]
        pf_val = pf if pf is not None else 3.0   # inf PF (no losers) → treat as strong
        expR = s["expectancy_r"]
        wr   = s["win_rate"]
        n    = s["n"]

        pf_lift = min(max((pf_val - 1.0) * 22.0, -25.0), 28.0)
        ex_lift = min(max(expR * 18.0, -14.0), 14.0)
        wr_lift = min(max((wr - 0.5) * 32.0, -10.0), 8.0)

        raw = 50.0 + pf_lift + ex_lift + wr_lift
        raw = min(max(raw, 5.0), 95.0)

        trusted = n >= min_n
        if not trusted:
            # Shrink toward neutral 40 proportional to how thin the sample is.
            w = n / min_n                      # 0..1
            raw = 40.0 * (1 - w) + raw * w

        out[label] = {
            "suggested_base": round(raw, 1),
            "n": n,
            "trusted": trusted,
            "profit_factor": pf,
            "expectancy_r": expR,
            "win_rate": s["win_rate"],
        }
    return out


# ── Public entry point ────────────────────────────────────────────────────────

def run_validation(
    tickers: Iterable[str] | None = None,
    period: str = "2y",
    max_hold: int = 20,
    step: int = 1,
    cooldown: int = 5,
) -> dict:
    """
    Run the walk-forward setup validation.

    Returns:
        {
          "stats":            {setup_label: {n, win_rate, profit_factor, ...}},
          "recommended":      {setup_label: {suggested_base, trusted, ...}},
          "meta": {tickers, with_data, total_trades, params},
        }
    """
    import yfinance as yf

    ticker_list = list(tickers) if tickers else list(DEFAULT_STOCK_WATCHLIST)
    log.info("Setup validation over %d tickers (period=%s)…", len(ticker_list), period)

    raw = yf.download(
        ticker_list, period=period, interval="1d",
        progress=False, auto_adjust=True, group_by="column",
    )

    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
        highs  = raw["High"]
        lows   = raw["Low"]
    else:
        # single ticker
        only = ticker_list[0]
        closes = raw[["Close"]].rename(columns={"Close": only})
        highs  = raw[["High"]].rename(columns={"High": only})
        lows   = raw[["Low"]].rename(columns={"Low": only})

    all_trades: list[dict] = []
    with_data = 0
    for tkr in ticker_list:
        if tkr not in closes.columns:
            continue
        c = closes[tkr]
        h = highs[tkr] if tkr in highs.columns else c
        lo = lows[tkr] if tkr in lows.columns else c
        if c.dropna().shape[0] < _MIN_HISTORY + 5:
            continue
        with_data += 1
        try:
            t = _walk_ticker(c, h, lo, max_hold, step, cooldown)
            all_trades.extend(t)
        except Exception as exc:   # noqa: BLE001
            log.warning("Validation failed for %s: %s", tkr, exc)

    stats = _aggregate(all_trades)
    recommended = recommend_base_scores(stats)

    return {
        "stats": stats,
        "recommended": recommended,
        "meta": {
            "tickers_requested": len(ticker_list),
            "tickers_with_data": with_data,
            "total_trades": len(all_trades),
            "params": {
                "period": period, "max_hold": max_hold,
                "step": step, "cooldown": cooldown,
                "atr_stop_mult": 2.0, "min_history": _MIN_HISTORY,
            },
        },
    }
