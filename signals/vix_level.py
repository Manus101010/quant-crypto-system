"""
Signal 1: VIX Level
Low VIX = calm market = favorable for deployment.
Percentile-ranks current VIX against trailing 1 year.
"""
from __future__ import annotations
import numpy as np
import yfinance as yf
from config import LOOKBACK_DAYS
from utils.logger import get_logger

log = get_logger(__name__)


def compute() -> dict:
    try:
        df = yf.download("^VIX", period="2y", interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError("No VIX data returned")

        closes = df["Close"].squeeze().dropna()
        current = float(closes.iloc[-1])
        lookback = closes.iloc[-LOOKBACK_DAYS:]

        # Percentile rank: how often was VIX *lower* than today?
        # Low VIX = good, so score = 100 - percentile
        percentile = float(np.sum(lookback < current) / len(lookback) * 100)
        score = 100.0 - percentile

        # Adjustments
        if current < 15:
            score = min(100, score + 5)
        if current > 30:
            score = max(0, score - 10)

        score = float(np.clip(score, 0, 100))

        return {
            "name": "VIX Level",
            "score": score,
            "value": current,
            "unit": "pts",
            "detail": f"VIX={current:.1f}, {percentile:.0f}th pct (trailing 1yr)",
            "raw": closes.tail(252).tolist(),
        }

    except Exception as exc:
        log.warning("vix_level failed: %s", exc)
        return {"name": "VIX Level", "score": 50.0, "value": None, "unit": "pts",
                "detail": f"Error: {exc}", "raw": []}
