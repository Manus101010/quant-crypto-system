"""
QuantCore — FastAPI server
Run: python server.py  →  http://localhost:8501
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from api import macro, analyst, scanner, journal_api, backtest_api, log_store as L
from api import paper_trades_api, loop_api, webhooks_api, setup_validation_api, monitoring_api


# ── Scheduler setup ───────────────────────────────────────────────────────────
def _build_scheduler():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger
    from paper_trades.loop import check_positions, full_loop

    sched = AsyncIOScheduler(timezone="UTC")

    # Check open positions every hour
    sched.add_job(
        check_positions,
        trigger=IntervalTrigger(hours=1),
        id="check_positions",
        name="Check open paper trade positions",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Full loop: scan + open new trades once daily at 08:00 UTC
    sched.add_job(
        lambda: full_loop(universe="crypto", top_n=100),
        trigger=CronTrigger(hour=8, minute=0, timezone="UTC"),
        id="daily_loop",
        name="Daily scan + auto-open paper trades",
        replace_existing=True,
        misfire_grace_time=600,
    )

    return sched


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched = _build_scheduler()
    sched.start()
    loop_api.set_scheduler(sched)
    L.ok("APScheduler started — daily loop @ 08:00 UTC, position check every 1h")
    yield
    sched.shutdown(wait=False)
    L.ok("APScheduler stopped")


app = FastAPI(title="QuantCore API", version="2.0", docs_url="/api/docs", lifespan=lifespan)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(macro.router,              prefix="/api/macro",         tags=["macro"])
app.include_router(analyst.router,            prefix="/api/analyst",       tags=["analyst"])
app.include_router(scanner.router,            prefix="/api/scanner",       tags=["scanner"])
app.include_router(journal_api.router,        prefix="/api/journal",       tags=["journal"])
app.include_router(backtest_api.router,       prefix="/api/backtest",      tags=["backtest"])
app.include_router(paper_trades_api.router,                                tags=["paper_trades"])
app.include_router(loop_api.router,                                        tags=["loop"])
app.include_router(webhooks_api.router,       prefix="/api/webhooks",      tags=["webhooks"])
app.include_router(setup_validation_api.router, prefix="/api/validation",  tags=["validation"])
app.include_router(monitoring_api.router,     prefix="/api/monitoring",    tags=["monitoring"])


@app.get("/api/system/logs")
def get_logs(n: int = 30):
    return {"logs": L.get_logs(n)}


@app.get("/api/system/status")
def system_status():
    from config import ANTHROPIC_API_KEY
    return {
        "status": "online",
        "api_key_set": bool(ANTHROPIC_API_KEY),
        "version": "2.0",
    }


# ── Static frontend ───────────────────────────────────────────────────────────
FRONTEND = Path(__file__).parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND), html=False), name="static")

@app.middleware("http")
async def no_cache_js(request, call_next):
    response = await call_next(request)
    if request.url.path.endswith((".js", ".css")):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", response_class=FileResponse)
def root():
    return FileResponse(str(FRONTEND / "index.html"))


# Catch-all SPA fallback
@app.get("/{path:path}", response_class=FileResponse)
def spa_fallback(path: str):
    return FileResponse(str(FRONTEND / "index.html"))


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    L.ok("QuantCore v2.0 starting…")
    uvicorn.run("server:app", host="0.0.0.0", port=8501, reload=True,
                log_level="warning")
