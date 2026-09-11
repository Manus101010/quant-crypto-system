"""
Crypto Breadth — % of top coins trading above their 50-day moving average.

The crypto analogue of equity breadth (% of S&P above its 200-DMA): a broad,
healthy market has most large-caps in uptrends. Narrow breadth (few coins above
their MA) = a fragile, BTC-only rally. Score = the percentage directly.
"""
from __future__ import annotations
from utils.exchange import get_ohlcv_batch
from utils.crypto_universe import get_top_crypto
from utils.logger import get_logger

log = get_logger(__name__)

_TOP_N   = 30    # top coins by market cap
_MA_DAYS = 50


def compute() -> dict:
    try:
        universe = get_top_crypto(_TOP_N)
        data = get_ohlcv_batch(universe, "1d", limit=_MA_DAYS + 5)
        if not data:
            raise ValueError("no OHLC for universe")

        above = 0
        counted = 0
        for sym, df in data.items():
            if len(df) < _MA_DAYS:
                continue
            counted += 1
            price = float(df["close"].iloc[-1])
            ma = float(df["close"].iloc[-_MA_DAYS:].mean())
            if price > ma:
                above += 1

        if counted == 0:
            raise ValueError("no coins with enough history")

        pct = above / counted * 100
        health = ("broad, healthy" if pct >= 65 else
                  "mixed" if pct >= 40 else "narrow, fragile")
        return {
            "name":  "Crypto Breadth",
            "score": round(pct, 1),
            "value": round(pct, 1),
            "unit":  f"% > {_MA_DAYS}DMA",
            "detail": f"{above}/{counted} top coins above their {_MA_DAYS}-day MA "
                      f"({pct:.0f}%) — {health}",
            "raw":   [],
        }
    except Exception as exc:
        log.warning("crypto_breadth failed: %s", exc)
        return {"name": "Crypto Breadth", "score": 50.0, "value": None,
                "unit": "%", "detail": f"unavailable: {exc}", "raw": []}
