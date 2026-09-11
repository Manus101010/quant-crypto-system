"""
Signal Aggregator
Runs all 7 signals, blends them into a weighted deployment score,
and returns a structured result with regime classification.
"""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import SIGNAL_WEIGHTS, DEPLOY_THRESHOLDS
from utils.logger import get_logger
import signals.vix_level as vix_level
import signals.vix_term_structure as vix_ts
import signals.breadth as breadth
import signals.credit_spreads as credit_spreads
import signals.put_call as put_call
import signals.yield_curve as yield_curve
import signals.momentum as momentum
import signals.nfci as nfci
import signals.m2_growth as m2_growth
import signals.inflation as inflation

log = get_logger(__name__)

_SIGNAL_MAP = {
    # Original 7
    "vix_level":          vix_level.compute,
    "vix_term_structure": vix_ts.compute,
    "breadth":            breadth.compute,
    "credit_spreads":     credit_spreads.compute,
    "put_call":           put_call.compute,
    "yield_curve":        yield_curve.compute,
    "momentum":           momentum.compute,
    # New institutional signals
    "nfci":               nfci.compute,
    "m2_growth":          m2_growth.compute,
    "inflation":          inflation.compute,
}


def run_all(parallel: bool = True) -> dict:
    """Fetch all signals and return blended deployment score."""
    results: dict[str, dict] = {}
    t0 = time.time()

    if parallel:
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(fn): key for key, fn in _SIGNAL_MAP.items()}
            for fut in as_completed(futures):
                key = futures[fut]
                try:
                    results[key] = fut.result()
                except Exception as exc:
                    log.error("Signal %s raised: %s", key, exc)
                    results[key] = {
                        "name": key, "score": 50.0, "value": None,
                        "unit": "", "detail": str(exc), "raw": [],
                    }
    else:
        for key, fn in _SIGNAL_MAP.items():
            results[key] = fn()

    elapsed = time.time() - t0

    # Weighted blend
    total_weight = sum(SIGNAL_WEIGHTS[k] for k in results)
    deployment_score = sum(
        results[k]["score"] * SIGNAL_WEIGHTS[k] / total_weight
        for k in results
    )
    deployment_score = round(deployment_score, 1)

    # Regime classification
    regime = _classify(deployment_score)

    return {
        "deployment_score": deployment_score,
        "regime": regime,
        "signals": results,
        "elapsed_s": round(elapsed, 1),
    }


def _classify(score: float) -> str:
    if score >= DEPLOY_THRESHOLDS["aggressive"]:
        return "Aggressive Deploy"
    if score >= DEPLOY_THRESHOLDS["moderate"]:
        return "Moderate Deploy"
    if score >= DEPLOY_THRESHOLDS["cautious"]:
        return "Cautious Deploy"
    return "Avoid / Reduce"
