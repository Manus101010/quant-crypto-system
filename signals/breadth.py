"""
Signal 3: Market Breadth
% of S&P 500 stocks above their 200-day SMA.
Proxy: use a basket of sector ETFs above 200-SMA as a breadth gauge.
For a faster version we track the "percentage above 200-day" indirectly
via $SPXA200R (if available) or via a sample basket of S&P components.
"""
from __future__ import annotations
import numpy as np
import yfinance as yf
from utils.logger import get_logger

log = get_logger(__name__)

# Broad basket of sector ETFs — all 11 GICS sectors
_SECTOR_ETFS = [
    "XLK", "XLF", "XLV", "XLY", "XLI",
    "XLE", "XLP", "XLU", "XLRE", "XLB", "XLC",
]

# We also attempt the NYSE internals ticker first
_BREADTH_TICKER = "^SPXA200R"  # % S&P 500 above 200 SMA (available on Yahoo)


def compute() -> dict:
    try:
        # Try the direct breadth index first
        df = yf.download(_BREADTH_TICKER, period="1y", interval="1d",
                         progress=False, auto_adjust=True)
        if not df.empty and "Close" in df.columns:
            closes = df["Close"].squeeze().dropna()
            current_pct = float(closes.iloc[-1])
            score = float(np.clip(
                (current_pct - 30) / (80 - 30) * 100,
                0, 100
            ))
            return {
                "name": "Market Breadth",
                "score": score,
                "value": current_pct,
                "unit": "%",
                "detail": f"{current_pct:.1f}% of S&P 500 above 200-SMA",
                "raw": closes.tolist(),
            }
    except Exception:
        pass

    # Fallback: sector ETF basket
    try:
        prices = yf.download(_SECTOR_ETFS, period="1y", interval="1d",
                              progress=False, auto_adjust=True)["Close"].dropna()
        above = 0
        for etf in _SECTOR_ETFS:
            if etf not in prices.columns:
                continue
            s = prices[etf].dropna()
            if len(s) >= 200:
                sma200 = s.iloc[-200:].mean()
                if s.iloc[-1] > sma200:
                    above += 1
        pct = above / len(_SECTOR_ETFS) * 100
        score = float(np.clip((pct - 30) / (80 - 30) * 100, 0, 100))
        return {
            "name": "Market Breadth",
            "score": score,
            "value": pct,
            "unit": "%",
            "detail": f"{above}/{len(_SECTOR_ETFS)} sector ETFs above 200-SMA ({pct:.0f}%)",
            "raw": [],
        }
    except Exception as exc:
        log.warning("breadth failed: %s", exc)
        return {"name": "Market Breadth", "score": 50.0, "value": None,
                "unit": "%", "detail": f"Error: {exc}", "raw": []}
