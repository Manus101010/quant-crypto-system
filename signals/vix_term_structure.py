"""
Signal 2: VIX Term Structure
Ratio = ^VIX / ^VIX3M.
Contango (ratio < 1) = market calm about future = bullish.
Backwardation (ratio > 1) = near-term fear premium = bearish.
"""
from __future__ import annotations
import numpy as np
import yfinance as yf
from utils.logger import get_logger

log = get_logger(__name__)

_RATIO_MIN = 0.70
_RATIO_MAX = 1.20


def compute() -> dict:
    try:
        raw = yf.download(["^VIX", "^VIX3M"], period="1y", interval="1d",
                          progress=False, auto_adjust=True)
        closes = raw["Close"].dropna()
        if closes.empty or "^VIX" not in closes or "^VIX3M" not in closes:
            raise ValueError("Missing VIX / VIX3M data")

        vix = float(closes["^VIX"].iloc[-1])
        vix3m = float(closes["^VIX3M"].iloc[-1])
        ratio = vix / vix3m

        # Linear map: ratio 0.70 -> 100, ratio 1.20 -> 0
        score = float(np.clip(
            ((_RATIO_MAX - ratio) / (_RATIO_MAX - _RATIO_MIN)) * 100,
            0, 100
        ))

        structure = "Contango" if ratio < 1.0 else "Backwardation"
        ratio_series = (closes["^VIX"] / closes["^VIX3M"]).dropna()

        return {
            "name": "VIX Term Structure",
            "score": score,
            "value": ratio,
            "unit": "ratio",
            "detail": f"{structure} | VIX={vix:.1f} / VIX3M={vix3m:.1f} = {ratio:.3f}",
            "raw": ratio_series.tolist(),
        }

    except Exception as exc:
        log.warning("vix_term_structure failed: %s", exc)
        return {"name": "VIX Term Structure", "score": 50.0, "value": None,
                "unit": "ratio", "detail": f"Error: {exc}", "raw": []}
