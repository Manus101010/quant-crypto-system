"""
Crypto Fear & Greed Index (alternative.me, 0-100).

Contrarian-leaning mapping suited to a mean-reversion edge: extreme greed (>80)
= froth → caution (low score); a healthy 40-70 band scores high; fear (20-40)
is treated as opportunity (still high); extreme fear (<20) is capitulation —
rewarded but capped, since "cheap" can get cheaper.
"""
from __future__ import annotations
import numpy as np
from utils.crypto_macro import fear_greed
from utils.logger import get_logger

log = get_logger(__name__)


def _score(v: float) -> float:
    if v >= 80:   return 25 - (v - 80) * 1.0        # extreme greed → 25 down to 5
    if v >= 70:   return 55 - (v - 70) * 3.0        # greed → 55..25
    if v >= 40:   return 80 - abs(v - 55) * 0.5     # healthy band, peak ~80 near 55
    if v >= 20:   return 72 + (40 - v) * 0.4        # fear → opportunity 72..80
    return 68 - (20 - v) * 0.6                       # extreme fear, capped ~68..56


def compute() -> dict:
    try:
        series = fear_greed(365)
        if not series:
            raise ValueError("no F&G data")
        current = series[-1]
        score = float(np.clip(_score(current), 0, 100))
        label = ("Extreme Greed" if current >= 80 else "Greed" if current >= 60 else
                 "Neutral" if current >= 45 else "Fear" if current >= 25 else "Extreme Fear")
        return {
            "name":  "Fear & Greed",
            "score": round(score, 1),
            "value": float(current),
            "unit":  "index",
            "detail": f"Fear & Greed {current}/100 — {label} "
                      f"(contrarian: greed→caution, fear→opportunity)",
            "raw":   [float(x) for x in series[-60:]],
        }
    except Exception as exc:
        log.warning("fear_greed failed: %s", exc)
        return {"name": "Fear & Greed", "score": 50.0, "value": None,
                "unit": "index", "detail": f"unavailable: {exc}", "raw": []}
