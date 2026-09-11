from __future__ import annotations
import asyncio
from fastapi import APIRouter
from pydantic import BaseModel
from api import log_store as L

router = APIRouter()


class BacktestRequest(BaseModel):
    ticker: str = "SPY"
    start: str = "2020-01-01"
    end: str = "2024-12-31"
    init_cash: float = 100_000.0
    fees: float = 0.001
    strategy: str = "sma_cross"
    fast_window: int = 50
    slow_window: int = 200
    min_deploy_score: float = 50.0


@router.post("/run")
async def run_backtest(body: BacktestRequest):
    from backtesting.engine import BacktestConfig, run_backtest as _run
    cfg = BacktestConfig(
        ticker=body.ticker.upper(),
        start=body.start,
        end=body.end,
        init_cash=body.init_cash,
        fees=body.fees,
        strategy=body.strategy,
        fast_window=body.fast_window,
        slow_window=body.slow_window,
        min_deploy_score=body.min_deploy_score,
    )
    L.info(f"Backtest: {cfg.ticker} {cfg.strategy} {cfg.start}→{cfg.end}")
    result = await asyncio.to_thread(_run, cfg)
    if "error" not in result:
        L.ok(f"Backtest done — return={result.get('total_return_pct',0):.1f}% alpha={result.get('alpha',0):.1f}%")
    else:
        L.warn(f"Backtest error: {result['error']}")
    return result
