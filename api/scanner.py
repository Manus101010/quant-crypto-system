from __future__ import annotations
import asyncio
import math
from fastapi import APIRouter
from api import log_store as L

router = APIRouter()
_last_scan: list[dict]        = []
_last_crypto_scan: list[dict] = []


def _json_safe(obj):
    """
    Recursively replace non-finite floats (NaN / ±Inf) with None so FastAPI can
    serialize scan results. A single NaN (e.g. an indicator with insufficient
    history) otherwise makes the whole endpoint 500 with an empty body.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


@router.get("/run")
async def run_stock_scan(
    tickers:      str   = "",
    universe:     str   = "default",   # "default" (~90 large-caps) | "sp500" (live S&P 500)
    min_rsi:      float = 0,
    max_rsi:      float = 100,
    above_sma200: bool  = True,
    min_momentum: float | None = None,
):
    from skills.scanner import run_scan as _scan, ScanCriteria, DEFAULT_STOCK_WATCHLIST
    if tickers.strip():
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        from utils.stock_universe import get_stock_universe
        ticker_list = get_stock_universe(universe)
    criteria = ScanCriteria(
        above_sma200    = above_sma200,
        min_rsi         = min_rsi,
        max_rsi         = max_rsi,
        min_momentum_3m = min_momentum,
    )
    from api.macro import cached_deployment_score
    regime = cached_deployment_score()
    L.info(f"Stock scanner: {len(ticker_list)} tickers… (regime={regime if regime is not None else 'n/a'})")
    try:
        df = await asyncio.to_thread(_scan, ticker_list, criteria, regime)
        results = _json_safe(df.to_dict("records")) if not df.empty else []
        global _last_scan
        _last_scan = results
        L.ok(f"SCAN — {len(results)} setups from {len(ticker_list)} stocks")
        return {"results": results, "total_scanned": len(ticker_list)}
    except Exception as exc:
        L.err(f"Stock scanner error: {exc}")
        raise


@router.get("/run/crypto")
async def run_crypto_scan(
    tickers:      str   = "",
    market_size:  int   = 0,      # 0 = use tickers; 50/100/150/200 = CoinGecko live top-N
    min_rsi:      float = 0,
    max_rsi:      float = 100,
    above_sma50:  bool  = False,
    min_momentum: float | None = None,
):
    from skills.scanner import run_crypto_scan as _scan, ScanCriteria, DEFAULT_CRYPTO_WATCHLIST

    if market_size > 0:
        # Live market cap universe from CoinGecko
        from utils.crypto_universe import get_top_crypto
        ticker_list = await asyncio.to_thread(get_top_crypto, market_size)
        L.info(f"Crypto universe: top-{market_size} by mktcap → {len(ticker_list)} tickers from CoinGecko")
    elif tickers.strip():
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        # Ensure yfinance crypto format (e.g. BTC → BTC-USD)
        ticker_list = [t if "-" in t else f"{t}-USD" for t in ticker_list]
    else:
        ticker_list = DEFAULT_CRYPTO_WATCHLIST
    criteria = ScanCriteria(
        min_price       = 0.0,
        above_sma200    = False,
        above_sma50     = above_sma50,
        min_rsi         = min_rsi,
        max_rsi         = max_rsi,
        min_momentum_3m = min_momentum,
    )
    from api.macro import cached_deployment_score
    regime = cached_deployment_score()
    L.info(f"Crypto scanner: {len(ticker_list)} coins… (regime={regime if regime is not None else 'n/a'})")
    try:
        df = await asyncio.to_thread(_scan, ticker_list, criteria, regime)
        results = _json_safe(df.to_dict("records")) if not df.empty else []
        global _last_crypto_scan
        _last_crypto_scan = results
        L.ok(f"CRYPTO SCAN — {len(results)} setups from {len(ticker_list)} coins")
        return {"results": results, "total_scanned": len(ticker_list)}
    except Exception as exc:
        L.err(f"Crypto scanner error: {exc}")
        raise


@router.get("/universe/crypto")
async def crypto_universe(size: int = 100):
    """Return the live CoinGecko top-N ticker list (for UI display)."""
    from utils.crypto_universe import get_top_crypto
    tickers = await asyncio.to_thread(get_top_crypto, size)
    return {"tickers": tickers, "count": len(tickers)}


@router.get("/latest")
async def latest_scan():
    return {"results": _last_scan}


@router.get("/latest/crypto")
async def latest_crypto_scan():
    return {"results": _last_crypto_scan}
