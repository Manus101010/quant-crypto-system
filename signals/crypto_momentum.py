"""
Crypto Momentum (BTC) — the trend backbone of the deployment gate.

Adapted from the original equity momentum signal (SPY 50/200 golden cross +
3-month + 12-1 momentum), retargeted to BTC since the system is crypto-only and
yfinance is being retired. Higher score = BTC in a confirmed uptrend.
"""
from __future__ import annotations
import numpy as np
from utils.exchange import get_ohlcv
from utils.logger import get_logger

log = get_logger(__name__)


def compute() -> dict:
    try:
        df = get_ohlcv("BTC-USD", "1d", limit=400)
        if df.empty or len(df) < 210:
            raise ValueError("insufficient BTC history")
        close = df["close"]
        price = float(close.iloc[-1])
        sma50  = float(close.iloc[-50:].mean())
        sma200 = float(close.iloc[-200:].mean())
        golden = 1.0 if sma50 > sma200 else 0.0

        mom_3m  = (price / float(close.iloc[-63]) - 1) * 100
        mom_121 = (float(close.iloc[-21]) / float(close.iloc[-273]) - 1) * 100 if len(close) >= 273 else mom_3m

        # Map each return to 0-100 (0% → 50, +40% → ~100, −40% → ~0)
        m3_s  = float(np.clip(50 + mom_3m  * 1.25, 0, 100))
        m12_s = float(np.clip(50 + mom_121 * 0.6,  0, 100))
        score = float(np.clip(0.40 * golden * 100 + 0.30 * m3_s + 0.30 * m12_s, 0, 100))

        status = "Golden Cross ✓" if golden else "Death Cross ✗"
        return {
            "name":  "BTC Momentum",
            "score": round(score, 1),
            "value": round(mom_3m, 2),
            "unit":  "% 3M",
            "detail": (f"BTC {status} | 3M {mom_3m:+.1f}% | 12-1M {mom_121:+.1f}% | "
                       f"price ${price:,.0f} vs SMA200 ${sma200:,.0f}"),
            "raw":   [float(x) for x in close.iloc[-60:]],
        }
    except Exception as exc:
        log.warning("crypto_momentum failed: %s", exc)
        return {"name": "BTC Momentum", "score": 50.0, "value": None,
                "unit": "% 3M", "detail": f"unavailable: {exc}", "raw": []}
