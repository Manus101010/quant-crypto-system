"""
Setup Validation API
====================

Exposes the walk-forward setup-validation backtester (see
`backtesting.setup_validation`) over HTTP. The orchestrator is responsible for
registering this router in server.py — this file only defines it.

Mirrors the style of `api/scanner.py`.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

from api import log_store as L

router = APIRouter()

_last_validation: dict = {}


@router.get("/run")
async def run_setup_validation(
    tickers:  str   = "",
    period:   str   = "2y",
    max_hold: int   = 20,
    step:     int   = 1,
    cooldown: int   = 5,
):
    """
    Run the walk-forward setup validation and return per-setup empirical stats
    plus recommended 0-100 base conviction scores.

    Query params:
      tickers  — comma-separated override (default: full stock watchlist)
      period   — yfinance history window (default 2y)
      max_hold — max bars to hold each simulated trade
      step     — evaluate every Nth bar (1 = every bar)
      cooldown — bars to wait after a fire before re-evaluating
    """
    from backtesting.setup_validation import run_validation, DEFAULT_STOCK_WATCHLIST

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] \
                  or list(DEFAULT_STOCK_WATCHLIST)

    L.info(f"Setup validation: {len(ticker_list)} tickers (period={period}, max_hold={max_hold})…")
    try:
        result = await asyncio.to_thread(
            run_validation, ticker_list, period, max_hold, step, cooldown,
        )
        global _last_validation
        _last_validation = result
        meta = result.get("meta", {})
        L.ok(
            f"SETUP VALIDATION — {meta.get('total_trades', 0)} trades, "
            f"{len(result.get('stats', {}))} setups, "
            f"{meta.get('tickers_with_data', 0)} tickers"
        )
        return result
    except Exception as exc:   # noqa: BLE001
        L.err(f"Setup validation error: {exc}")
        raise


@router.get("/latest")
async def latest_validation():
    """Return the most recent validation result (empty until /run is called)."""
    return _last_validation
