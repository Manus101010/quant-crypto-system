"""
Signal 5: Options Sentiment (improved)
Combines two complementary components:
  1. VIX 20-day Rate-of-Change — direction of fear over the past month
  2. VIX9D/VIX ratio — near-term (9-day) vs. 30-day implied vol.
     When near-term vol < 30-day vol (ratio < 1) = near-term calm = bullish.
     When near-term vol > 30-day vol (ratio > 1) = fear spike expected = bearish.

Research note: the plain VIX ROC alone is the weakest macro signal.
Adding the VIX term-structure short end (VIX9D) captures option-market
positioning more accurately than ROC alone.
"""
from __future__ import annotations
import numpy as np
import yfinance as yf
from utils.logger import get_logger

log = get_logger(__name__)

_ROC_PERIOD = 20
_ROC_CLIP   = 0.40   # ±40% mapped to score extremes


def compute() -> dict:
    try:
        raw = yf.download(["^VIX", "^VIX9D"], period="6mo", interval="1d",
                          progress=False, auto_adjust=True)

        closes = (
            raw["Close"].squeeze()
            if not isinstance(raw.columns, __import__("pandas").MultiIndex)
            else raw["Close"]
        )

        vix  = closes["^VIX"].dropna()
        v9d  = closes["^VIX9D"].dropna() if "^VIX9D" in closes.columns else None

        if len(vix) < _ROC_PERIOD + 1:
            raise ValueError("Insufficient VIX history")

        curr_vix = float(vix.iloc[-1])
        prev_vix = float(vix.iloc[-1 - _ROC_PERIOD])
        roc = (curr_vix - prev_vix) / prev_vix   # signed fraction

        # Component 1: VIX ROC score (60% weight)
        roc_score = float(np.clip(50 - (roc / _ROC_CLIP) * 50, 0, 100))

        # Component 2: VIX9D/VIX ratio score (40% weight) — if available
        if v9d is not None and len(v9d) >= 1:
            curr_v9d = float(v9d.iloc[-1])
            ratio    = curr_v9d / curr_vix if curr_vix else 1.0
            # ratio < 1 → near-term vol below 30-day → calm → high score
            # ratio > 1 → near-term fear spike → low score
            ratio_score = float(np.clip(50 + (1 - ratio) * 100, 0, 100))
            score = round(0.6 * roc_score + 0.4 * ratio_score, 1)
            detail = (
                f"VIX={curr_vix:.1f} | VIX9D={curr_v9d:.1f} | "
                f"9D/30D ratio={ratio:.3f} | 20d ROC={roc * 100:+.1f}%"
            )
        else:
            score  = round(roc_score, 1)
            detail = f"VIX 20d ROC = {roc * 100:+.1f}% | VIX9D unavailable"

        return {
            "name":   "Options Sentiment",
            "score":  score,
            "value":  round(roc * 100, 1),
            "unit":   "% ROC",
            "detail": detail,
            "raw":    vix.pct_change(_ROC_PERIOD).dropna().tolist(),
        }

    except Exception as exc:
        log.warning("put_call failed: %s", exc)
        return {
            "name": "Options Sentiment", "score": 50.0, "value": None,
            "unit": "% ROC", "detail": f"Error: {exc}", "raw": [],
        }
