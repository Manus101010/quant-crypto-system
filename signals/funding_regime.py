"""
Funding Rate Regime — leverage & positioning across perp markets.

Mean funding across top USDT perps (via ccxt, read-only). Slightly-positive
funding is normal/healthy. Extremely positive = crowded longs / froth → caution
(lower score). Negative = shorts paying / fear → often a contrarian bottom, so
scored moderate-to-high rather than punished. Per-interval rate (typically 8h).
"""
from __future__ import annotations
import numpy as np
from utils.exchange import get_funding_rates
from utils.crypto_universe import get_top_crypto
from utils.logger import get_logger

log = get_logger(__name__)

_TOP_N = 15


def compute() -> dict:
    try:
        universe = get_top_crypto(_TOP_N)
        rates = get_funding_rates(universe)
        if not rates:
            raise ValueError("no funding data")

        vals = list(rates.values())
        mean = float(np.mean(vals))
        mean_bps = mean * 1e4                    # rate → basis points per interval

        # Peak score at mildly-positive funding (~0-3bps). Penalise froth (>8bps)
        # and, more gently, deep negative funding (stress).
        if mean_bps >= 0:
            score = 68 - max(mean_bps - 3, 0) * 6      # 3bps→68, 8bps→38, 13bps→8
        else:
            score = 60 + mean_bps * 3                  # -2bps→54, -6bps→42 (contrarian floor)
        score = float(np.clip(score, 0, 100))

        regime = ("froth / crowded longs" if mean_bps > 6 else
                  "healthy positive" if mean_bps >= 0 else
                  "fear / shorts paying")
        pos = sum(1 for v in vals if v > 0)
        return {
            "name":  "Funding Regime",
            "score": round(score, 1),
            "value": round(mean_bps, 3),
            "unit":  "bps/interval",
            "detail": f"Mean funding {mean_bps:+.2f}bps across {len(vals)} perps "
                      f"({pos} positive) — {regime}",
            "raw":   [],
        }
    except Exception as exc:
        log.warning("funding_regime failed: %s", exc)
        return {"name": "Funding Regime", "score": 50.0, "value": None,
                "unit": "bps", "detail": f"unavailable: {exc}", "raw": []}
