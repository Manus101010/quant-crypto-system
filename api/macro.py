from __future__ import annotations
import asyncio
import time
from fastapi import APIRouter
from api import log_store as L

router = APIRouter()

_cache: dict = {"result": None, "ts": 0.0}
_CACHE_TTL = 300  # 5 min


@router.get("/run")
async def run_macro():
    L.info("Macro gate refresh triggered")
    from signals.aggregator import run_all
    try:
        result = await asyncio.to_thread(run_all, True)
        _cache["result"] = result
        _cache["ts"] = time.time()
        L.ok(f"MACRO COMPLETE — score={result['deployment_score']:.1f} regime={result['regime']} ({result['elapsed_s']}s)")
        return result
    except Exception as exc:
        L.err(f"Macro gate error: {exc}")
        raise


@router.get("/latest")
async def latest_macro():
    if _cache["result"] and (time.time() - _cache["ts"]) < _CACHE_TTL:
        return _cache["result"]
    return await run_macro()


def cached_deployment_score() -> float | None:
    """
    Return the most recent macro Deployment Score (0–100) if one is cached,
    else None. Used by the scanner to apply a regime-aware conviction
    adjustment without forcing a fresh (slow) macro run.
    """
    res = _cache.get("result")
    if res and isinstance(res, dict):
        return res.get("deployment_score")
    return None
