"""
Signal 4: Credit Spreads
Proxy: HYG (high-yield bond ETF) yield spread against IEF (7-10yr Treasury).
We compute a z-score of the HYG/IEF price ratio against trailing 1-year history.
Low / tightening spreads = risk-on = high score.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import yfinance as yf
from config import LOOKBACK_DAYS
from utils.logger import get_logger

log = get_logger(__name__)


def compute() -> dict:
    try:
        raw = yf.download(["HYG", "IEF"], period="2y", interval="1d",
                          progress=False, auto_adjust=True)
        closes = raw["Close"].dropna()
        if "HYG" not in closes.columns or "IEF" not in closes.columns:
            raise ValueError("HYG or IEF data missing")

        # Use HYG/IEF ratio as a proxy for spread: higher ratio = tighter spreads = good
        ratio = (closes["HYG"] / closes["IEF"]).dropna()
        lookback = ratio.iloc[-LOOKBACK_DAYS:]
        current = float(ratio.iloc[-1])
        mean = float(lookback.mean())
        std = float(lookback.std())
        if std == 0:
            raise ValueError("Zero std in credit spread proxy")

        z = (current - mean) / std
        # High z = HYG outperforming = spreads tight = bullish -> high score
        # Map z=-2 -> 0, z=0 -> 50, z=+2 -> 100
        score = float(np.clip(50 + z * 25, 0, 100))

        return {
            "name": "Credit Spreads",
            "score": score,
            "value": round(z, 2),
            "unit": "z-score",
            "detail": f"HYG/IEF z-score={z:.2f} (1yr) | HYG={closes['HYG'].iloc[-1]:.2f} IEF={closes['IEF'].iloc[-1]:.2f}",
            "raw": ratio.tail(LOOKBACK_DAYS).tolist(),
        }

    except Exception as exc:
        log.warning("credit_spreads failed: %s", exc)
        return {"name": "Credit Spreads", "score": 50.0, "value": None,
                "unit": "z-score", "detail": f"Error: {exc}", "raw": []}
