"""
Signal 7: Market Momentum
Combines SPY 50/200 SMA golden-cross status, 3-month price momentum,
and 12-1 month momentum (standard academic factor).
Strong uptrend = high score.
"""
from __future__ import annotations
import numpy as np
import yfinance as yf
from utils.logger import get_logger

log = get_logger(__name__)


def compute() -> dict:
    try:
        df = yf.download("SPY", period="2y", interval="1d",
                         progress=False, auto_adjust=True)
        closes = df["Close"].squeeze().dropna()
        if len(closes) < 252:
            raise ValueError("Insufficient SPY history")

        price = float(closes.iloc[-1])
        sma50  = float(closes.iloc[-50:].mean())
        sma200 = float(closes.iloc[-200:].mean())

        # Golden cross score (0 or 1)
        golden_cross = 1.0 if sma50 > sma200 else 0.0

        # 3-month momentum (63 days)
        mom_3m = (price - float(closes.iloc[-63])) / float(closes.iloc[-63])

        # 12-1 month momentum (skip most recent month)
        mom_12_1 = (float(closes.iloc[-21]) - float(closes.iloc[-252])) / float(closes.iloc[-252])

        # Combine: 40% golden cross, 30% 3m momentum, 30% 12-1 momentum
        mom_3m_score  = float(np.clip(50 + mom_3m  * 200, 0, 100))
        mom_121_score = float(np.clip(50 + mom_12_1 * 150, 0, 100))
        score = 0.40 * golden_cross * 100 + 0.30 * mom_3m_score + 0.30 * mom_121_score

        status = "Golden Cross ✓" if golden_cross else "Death Cross ✗"

        return {
            "name": "Market Momentum",
            "score": float(np.clip(score, 0, 100)),
            "value": round(mom_3m * 100, 1),
            "unit": "% 3M",
            "detail": (f"{status} | SPY={price:.2f} | SMA50={sma50:.2f} | SMA200={sma200:.2f}"
                       f" | 3M={mom_3m*100:+.1f}% | 12-1M={mom_12_1*100:+.1f}%"),
            "raw": closes.tail(252).tolist(),
        }

    except Exception as exc:
        log.warning("momentum failed: %s", exc)
        return {"name": "Market Momentum", "score": 50.0, "value": None,
                "unit": "% 3M", "detail": f"Error: {exc}", "raw": []}
