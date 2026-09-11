"""
Total Market Cap Trend — is the whole crypto market expanding or contracting?

Above a rising 50-day average = capital flowing in = risk-on (higher score);
below a falling average = contraction = risk-off (lower). Reconstructed from
free per-coin history (see utils.crypto_macro.total_mcap_history).
"""
from __future__ import annotations
import numpy as np
from utils.crypto_macro import total_mcap_history
from utils.logger import get_logger

log = get_logger(__name__)

_MA = 50


def compute() -> dict:
    try:
        hist = total_mcap_history(180)
        if len(hist) < _MA + 5:
            raise ValueError("insufficient market-cap history")

        current = hist[-1]
        ma = float(np.mean(hist[-_MA:]))
        dist_pct = (current / ma - 1) * 100                 # above/below MA
        slope_pct = (ma / float(np.mean(hist[-_MA - 20:-20])) - 1) * 100  # MA slope over ~20d

        # Above a rising MA scores high; below a falling MA scores low.
        score = float(np.clip(50 + dist_pct * 2.0 + slope_pct * 2.5, 0, 100))

        regime = ("expanding" if dist_pct > 0 and slope_pct > 0 else
                  "contracting" if dist_pct < 0 and slope_pct < 0 else "transitioning")
        return {
            "name":  "Total Market Cap",
            "score": round(score, 1),
            "value": round(current / 1e12, 3),
            "unit":  "$T total",
            "detail": f"Total mcap ${current/1e12:.2f}T | {dist_pct:+.1f}% vs {_MA}d MA | "
                      f"MA slope {slope_pct:+.1f}% — {regime}",
            "raw":   [round(x / 1e9, 1) for x in hist[-60:]],
        }
    except Exception as exc:
        log.warning("total_mcap failed: %s", exc)
        return {"name": "Total Market Cap", "score": 50.0, "value": None,
                "unit": "$T", "detail": f"unavailable: {exc}", "raw": []}
