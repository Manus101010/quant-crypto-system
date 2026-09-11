"""
Risk Manager
Kelly criterion + fixed-fraction position sizing.
ATR-based stop calculations.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import yfinance as yf
from utils.logger import get_logger

log = get_logger(__name__)


def kelly_size(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    kelly_fraction: float = 0.25,
    max_position_pct: float = 0.10,
) -> float:
    """
    Returns Kelly-fractional position size as a decimal of portfolio.
    win_rate: 0-1 probability of winning trade
    avg_win / avg_loss: absolute values in same units (e.g. percent)
    """
    if avg_loss == 0:
        return 0.0
    odds = avg_win / avg_loss
    kelly = win_rate - (1 - win_rate) / odds
    size = kelly * kelly_fraction
    return float(np.clip(size, 0, max_position_pct))


def atr_stop(
    ticker: str,
    atr_multiple: float = 2.0,
    period: int = 14,
    lookback: str = "3mo",
) -> dict:
    """
    Returns ATR-based stop info for ticker.
    """
    try:
        df = yf.download(ticker, period=lookback, interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError("No data")
        closes = df["Close"].dropna()
        highs  = df["High"].dropna()
        lows   = df["Low"].dropna()

        tr = pd.concat([
            highs - lows,
            (highs - closes.shift(1)).abs(),
            (lows  - closes.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.ewm(span=period, min_periods=period).mean().iloc[-1])
        price = float(closes.iloc[-1])
        stop_long  = price - atr * atr_multiple
        stop_short = price + atr * atr_multiple

        return {
            "ticker": ticker,
            "price": round(price, 2),
            "atr": round(atr, 3),
            "stop_long":  round(stop_long, 2),
            "stop_short": round(stop_short, 2),
            "risk_pct_long":  round(atr * atr_multiple / price * 100, 2),
        }
    except Exception as exc:
        log.warning("atr_stop failed %s: %s", ticker, exc)
        return {"ticker": ticker, "error": str(exc)}


def position_size_pct(
    portfolio_value: float,
    risk_per_trade_pct: float,
    stop_distance_pct: float,
) -> float:
    """
    Fixed-risk sizing: risk_per_trade_pct of portfolio, stop_distance_pct from entry.
    Returns position as % of portfolio.
    """
    if stop_distance_pct == 0:
        return 0.0
    return min(risk_per_trade_pct / stop_distance_pct, 0.20)
