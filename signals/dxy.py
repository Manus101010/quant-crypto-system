"""
US Dollar Trend (DXY proxy) — the macro backdrop for risk assets.

Uses the FRED broad trade-weighted USD index (DTWEXBGS); no yfinance. A rising
dollar drains global liquidity and pressures crypto (lower score); a falling
dollar is a tailwind (higher score). Scored on the ~3-month trend.
"""
from __future__ import annotations
import numpy as np
from utils.fred import fetch_fred
from utils.logger import get_logger

log = get_logger(__name__)


def compute() -> dict:
    try:
        s = fetch_fred("DTWEXBGS")
        if s is None or len(s) < 70:
            raise ValueError("insufficient USD index history")
        current = float(s.iloc[-1])
        prior = float(s.iloc[-63])                  # ~3 months ago
        chg_pct = (current / prior - 1) * 100

        # Rising USD = headwind. +3%/qtr ≈ -30 pts; -3%/qtr ≈ +30 pts.
        score = float(np.clip(50 - chg_pct * 10, 0, 100))
        direction = ("strengthening (headwind)" if chg_pct > 0.5 else
                     "weakening (tailwind)" if chg_pct < -0.5 else "flat")
        return {
            "name":  "US Dollar (DXY)",
            "score": round(score, 1),
            "value": round(current, 2),
            "unit":  "broad USD idx",
            "detail": f"Broad USD index {current:.2f} | 3M {chg_pct:+.1f}% — {direction}",
            "raw":   [float(x) for x in s.tail(60)],
        }
    except Exception as exc:
        log.warning("dxy failed: %s", exc)
        return {"name": "US Dollar (DXY)", "score": 50.0, "value": None,
                "unit": "idx", "detail": f"unavailable: {exc}", "raw": []}
