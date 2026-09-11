from __future__ import annotations
import asyncio
from fastapi import APIRouter
from api import log_store as L

router = APIRouter()


@router.get("/attribution")
async def attribution():
    """P&L attribution by setup and conviction bucket (net of costs)."""
    from paper_trades.monitoring import attribution as _attr
    return await asyncio.to_thread(_attr)


@router.get("/decay")
async def decay():
    """Per-setup recent-vs-baseline edge decay report."""
    from paper_trades.monitoring import detect_decay
    return {"decay": await asyncio.to_thread(detect_decay)}


@router.post("/decay/run")
async def decay_run():
    """Detect decay and push webhook alerts for newly-decayed setups."""
    from paper_trades.monitoring import run_decay_alerts
    result = await asyncio.to_thread(run_decay_alerts)
    n = len(result.get("alerted", []))
    if n:
        L.warn(f"Signal decay alerts sent: {', '.join(result['alerted'])}")
    return result
