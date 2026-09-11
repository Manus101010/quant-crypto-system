"""
Signal Aggregator
Runs the crypto macro signals, blends them into a weighted deployment score,
and returns a structured result with regime classification.

The framework (parallel fetch, weighted blend, regime classification) is
unchanged from the equity version — only the signal set was swapped for the
crypto refocus. Equity signal modules remain in git history / on disk but are
no longer wired in here.
"""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import SIGNAL_WEIGHTS, DEPLOY_THRESHOLDS
from utils.logger import get_logger
import signals.crypto_momentum as crypto_momentum
import signals.crypto_breadth as crypto_breadth
import signals.total_mcap as total_mcap
import signals.m2_growth as m2_growth
import signals.funding_regime as funding_regime
import signals.fear_greed as fear_greed
import signals.btc_dominance as btc_dominance
import signals.dxy as dxy

log = get_logger(__name__)

_SIGNAL_MAP = {
    "crypto_momentum": crypto_momentum.compute,
    "crypto_breadth":  crypto_breadth.compute,
    "total_mcap":      total_mcap.compute,
    "m2_growth":       m2_growth.compute,
    "funding_regime":  funding_regime.compute,
    "fear_greed":      fear_greed.compute,
    "btc_dominance":   btc_dominance.compute,
    "dxy":             dxy.compute,
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
