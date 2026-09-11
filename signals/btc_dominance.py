"""
BTC Dominance — capital rotation between BTC and the broader market.

Falling dominance = capital rotating into alts = broad risk-on (higher score).
Rising dominance = flight to BTC / alts bleeding = risk-off (lower score).
Scored primarily on the ~30-day trend, with a mild penalty at extreme levels.
Current level from CoinGecko /global; trend reconstructed from BTC-vs-total mcap.
"""
from __future__ import annotations
import numpy as np
from utils.crypto_macro import global_snapshot, total_mcap_history, _coin_mcap_history
from utils.logger import get_logger

log = get_logger(__name__)


def compute() -> dict:
    try:
        g = global_snapshot()
        current = g.get("btc_dominance")
        if current is None:
            raise ValueError("no dominance data")

        # Reconstruct dominance history: BTC mcap / total mcap. 180d window shares
        # the cached fetches with the total-market-cap signal (no duplicate calls).
        btc = _coin_mcap_history("bitcoin", 180)
        total = total_mcap_history(180)
        dom_hist = []
        if btc and total:
            n = min(len(btc), len(total))
            dom_hist = [btc[i] / total[i] * 100 for i in range(n) if total[i]]

        trend = 0.0
        if len(dom_hist) >= 30:
            trend = dom_hist[-1] - dom_hist[-30]   # pp change over ~30d

        # Falling dominance → risk-on (higher). ~+2pp/mo trend ≈ -16 pts.
        score = 50 - trend * 8
        # Mild penalty at extremes (flight-to-BTC fear >62, or alt euphoria <42)
        if current > 62:
            score -= (current - 62) * 1.5
        elif current < 42:
            score -= (42 - current) * 1.0
        score = float(np.clip(score, 0, 100))

        direction = "falling (alts gaining)" if trend < -0.3 else \
                    "rising (flight to BTC)" if trend > 0.3 else "flat"
        return {
            "name":  "BTC Dominance",
            "score": round(score, 1),
            "value": round(current, 2),
            "unit":  "% dominance",
            "detail": f"BTC.D {current:.1f}% | 30d trend {trend:+.1f}pp — {direction}",
            "raw":   [round(x, 2) for x in dom_hist[-60:]],
        }
    except Exception as exc:
        log.warning("btc_dominance failed: %s", exc)
        return {"name": "BTC Dominance", "score": 50.0, "value": None,
                "unit": "%", "detail": f"unavailable: {exc}", "raw": []}
