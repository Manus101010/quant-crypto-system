"""
Signal 9: M2 Liquidity Growth (FRED M2SL)
Year-over-year growth rate of the M2 money supply — a leading indicator of
how much liquidity is available to flow into risk assets.
Used by Bridgewater and systematic macro funds as a regime signal.

Positive M2 YoY growth → more liquidity → supportive of equities → HIGH score.
Negative M2 YoY growth → liquidity drain (as seen 2022-23) → LOW score.
Historical normal range: 0% to 8%. >10% is stimulative (COVID era: ~25%).
"""
from __future__ import annotations
import numpy as np
from utils.fred import fetch_fred
from utils.logger import get_logger

log = get_logger(__name__)


def compute() -> dict:
    try:
        m2 = fetch_fred("M2SL")               # monthly, ~4-week lag
        if len(m2) < 13:
            raise ValueError("Insufficient M2 history")

        yoy = float((m2.iloc[-1] / m2.iloc[-13] - 1) * 100)    # 12 months back
        mom = float((m2.iloc[-1] / m2.iloc[-4]  - 1) * 100)    # 3 months back (annualised direction)

        # Score: 50 at 0% growth, +5 per percentage point above 0, capped at 100
        # M2 YoY = +5%  → 75   (healthy liquidity)
        # M2 YoY = 0%   → 50
        # M2 YoY = -5%  → 25   (liquidity tightening)
        # M2 YoY = +12% → 100  (very stimulative)
        score = float(np.clip(50 + yoy * 5, 0, 100))

        trend = "accelerating" if mom > yoy / 4 else "decelerating" if mom < yoy / 4 else "stable"

        return {
            "name":   "M2 Liquidity Growth",
            "score":  round(score, 1),
            "value":  round(yoy, 2),
            "unit":   "% YoY",
            "detail": (
                f"M2 YoY = {yoy:+.1f}% | "
                f"M2 absolute = ${m2.iloc[-1]:,.0f}B | "
                f"Liquidity trend: {trend}"
            ),
            "raw": [],
        }

    except Exception as exc:
        log.warning("m2_growth failed: %s", exc)
        return {
            "name": "M2 Liquidity Growth", "score": 50.0, "value": None,
            "unit": "% YoY", "detail": f"FRED data unavailable: {exc}", "raw": [],
        }
