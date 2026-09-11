"""
Paper Trading Loop API
======================
Exposes the automated loop for manual triggering and configuration.
The scheduler (APScheduler) runs jobs automatically; these endpoints
allow the user to also trigger runs from the UI.
"""
from __future__ import annotations
import datetime
from fastapi import APIRouter
from pydantic import BaseModel
from utils.logger import get_logger
from paper_trades import stats as pstats

log = get_logger(__name__)
router = APIRouter(prefix="/api/loop")

# Shared scheduler reference — set by server.py on startup
_scheduler = None

def set_scheduler(sched):
    global _scheduler
    _scheduler = sched


class LoopConfig(BaseModel):
    universe:    str   = "crypto"   # crypto | stocks | both
    top_n:       int   = 100
    macro_score: float | None = None


@router.post("/run")
async def manual_run(cfg: LoopConfig):
    """Trigger one full loop run immediately (scan + check + open)."""
    from paper_trades.loop import full_loop
    log.info("loop: manual trigger — universe=%s top_n=%d", cfg.universe, cfg.top_n)
    result = full_loop(
        universe    = cfg.universe,
        top_n       = cfg.top_n,
        macro_score = cfg.macro_score,
    )
    return result


@router.post("/check")
async def manual_check():
    """Check open positions only — no new trades."""
    from paper_trades.loop import check_positions
    return check_positions()


@router.get("/risk-state")
def risk_state():
    """
    Portfolio-level risk governor: regime-conditional exposure scalar
    (from the macro Deployment Score) × drawdown governor (peak-to-current
    on the closed-trade equity curve). Shows whether new auto-trades are
    scaled down or halted.
    """
    from paper_trades import portfolio_risk
    from api.macro import cached_deployment_score
    return portfolio_risk.risk_state(cached_deployment_score())


@router.get("/validation-report")
def validation_report():
    """
    Per-setup Deflated Sharpe validation — shows which setups have a
    statistically significant edge (so their conviction multiplier is
    allowed to deviate from neutral 1.0) vs. those gated to 1.0 for
    insufficient/insignificant history.
    """
    return {"report": pstats.get_validation_report()}


@router.get("/status")
def loop_status():
    """Return scheduler status and next run times."""
    jobs = []
    if _scheduler:
        for job in _scheduler.get_jobs():
            nxt = job.next_run_time
            jobs.append({
                "id":       job.id,
                "name":     job.name,
                "next_run": nxt.isoformat() if nxt else None,
            })
    return {
        "scheduler_running": bool(_scheduler and _scheduler.running),
        "jobs":              jobs,
        "signal_stats":      pstats.get_all_stats(),
        "loop_log":          pstats.get_loop_log(limit=10),
    }


@router.post("/pause")
def pause_scheduler():
    if _scheduler:
        _scheduler.pause()
    return {"paused": True}


@router.post("/resume")
def resume_scheduler():
    if _scheduler:
        _scheduler.resume()
    return {"resumed": True}
