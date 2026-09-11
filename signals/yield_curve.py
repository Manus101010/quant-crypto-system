"""
Signal 6: Yield Curve (10Y - 2Y Spread)
Positive and widening = healthy economy = bullish for deployment.
Inverted (negative) = recession signal = reduce exposure.
Uses ^TNX (10Y) and ^IRX (13-week) as proxies; falls back to ETF ratios.
"""
from __future__ import annotations
import numpy as np
import yfinance as yf
from config import LOOKBACK_DAYS
from utils.logger import get_logger

log = get_logger(__name__)

# Direct yield tickers on Yahoo Finance
_T10 = "^TNX"   # 10-Year Treasury yield (×10 = actual %)
_T2  = "^TYX"   # 30-Year (use as long-end proxy when 2Y unavailable)


def compute() -> dict:
    try:
        raw = yf.download([_T10, "^IRX"], period="2y", interval="1d",
                          progress=False, auto_adjust=True)
        closes = raw["Close"].dropna()

        if _T10 in closes.columns and "^IRX" in closes.columns:
            y10 = closes[_T10] / 10   # Yahoo reports ×10
            y3m = closes["^IRX"] / 10
            spread = (y10 - y3m).dropna()
        else:
            # Fallback: IEF (7-10yr) / SHY (1-3yr) ratio z-score
            raw2 = yf.download(["IEF", "SHY"], period="2y", interval="1d",
                                progress=False, auto_adjust=True)
            c2 = raw2["Close"].dropna()
            spread = (c2["IEF"] / c2["SHY"]).dropna()

        current_spread = float(spread.iloc[-1])
        lookback = spread.iloc[-LOOKBACK_DAYS:]
        spread_mean = float(lookback.mean())
        spread_std = float(lookback.std())

        if spread_std > 0:
            z = (current_spread - spread_mean) / spread_std
        else:
            z = 0.0

        # Positive spread + recent improvement -> high score
        # Map: z=-2 -> 0, z=0 -> 50, z=+2 -> 100
        score = float(np.clip(50 + z * 25, 0, 100))

        # Hard penalty for inverted curve
        if current_spread < 0:
            score = max(0, score - 15)

        return {
            "name": "Yield Curve",
            "score": score,
            "value": round(current_spread, 3),
            "unit": "spread",
            "detail": f"10Y-3M spread={current_spread:.3f}, z={z:.2f} (1yr)",
            "raw": spread.tail(LOOKBACK_DAYS).tolist(),
        }

    except Exception as exc:
        log.warning("yield_curve failed: %s", exc)
        return {"name": "Yield Curve", "score": 50.0, "value": None,
                "unit": "spread", "detail": f"Error: {exc}", "raw": []}
