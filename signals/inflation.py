"""
Signal 10: Inflation Regime (FRED T10YIE — 10-Year Breakeven Inflation)
The breakeven inflation rate is the market's real-time expectation for average
inflation over the next decade, derived from TIPS (inflation-linked bonds) vs.
nominal Treasuries. Used by Bridgewater's All Weather framework as the
inflation-axis of the growth/inflation quadrant.

"Goldilocks" range 2.0–2.5%: equities can absorb moderate inflation → HIGH score.
Below 1.5%: deflation risk — earnings and valuations both suffer → LOW score.
Above 3.5%: Fed forced to tighten harder, multiples compress → LOW score.
"""
from __future__ import annotations
import numpy as np
from utils.fred import fetch_fred
from utils.logger import get_logger

log = get_logger(__name__)

_OPTIMAL = 2.3   # centre of the Goldilocks band (%)
_PENALTY = 40.0  # score reduction per % squared deviation from optimal


def compute() -> dict:
    try:
        be = fetch_fred("T10YIE")          # daily, real-time
        current = float(be.iloc[-1])
        prev_1m = float(be.iloc[-22]) if len(be) >= 22 else current

        # Quadratic penalty centred on _OPTIMAL — falls quickly at extremes
        score = float(np.clip(90 - ((current - _OPTIMAL) ** 2) * _PENALTY, 0, 100))

        trend  = current - prev_1m
        regime = (
            "Deflation risk"    if current < 1.5  else
            "Below-target"      if current < 2.0  else
            "Goldilocks zone"   if current < 2.8  else
            "Elevated"          if current < 3.5  else
            "High inflation"
        )

        return {
            "name":   "Inflation Expectations",
            "score":  round(score, 1),
            "value":  round(current, 2),
            "unit":   "% breakeven",
            "detail": (
                f"10Y TIPS breakeven = {current:.2f}% | "
                f"Regime: {regime} | "
                f"1-month trend: {trend:+.2f}%"
            ),
            "raw": be.tail(60).tolist(),
        }

    except Exception as exc:
        log.warning("inflation FRED failed (%s) — trying yfinance TIP/IEF proxy", exc)
        return _yfinance_fallback(str(exc))


def _yfinance_fallback(orig_err: str) -> dict:
    """
    Approximate 10Y breakeven from TIP (inflation-linked) vs IEF (nominal 7-10Y).
    TIP/IEF ratio tracks breakeven inflation directionally well enough to score.
    """
    try:
        import yfinance as yf
        import numpy as np
        raw = yf.download(["TIP", "IEF"], period="6mo", interval="1d",
                          progress=False, auto_adjust=True)["Close"]
        ratio = (raw["TIP"] / raw["IEF"]).dropna()
        if len(ratio) < 20:
            raise ValueError("insufficient data")

        # Scale ratio to approximate breakeven %:
        # Historically TIP/IEF ~1.17 ≈ 2.3% breakeven; we normalise around that
        current_ratio = float(ratio.iloc[-1])
        baseline      = float(ratio.iloc[-120:].mean()) if len(ratio) >= 120 else float(ratio.mean())
        # Map ratio deviation to estimated breakeven change from baseline (2.3%)
        current = 2.3 + (current_ratio - baseline) / baseline * 10

        score = float(np.clip(90 - ((current - _OPTIMAL) ** 2) * _PENALTY, 0, 100))
        regime = (
            "Deflation risk" if current < 1.5 else
            "Below-target"   if current < 2.0 else
            "Goldilocks zone" if current < 2.8 else
            "Elevated"       if current < 3.5 else
            "High inflation"
        )
        return {
            "name":   "Inflation Expectations",
            "score":  round(score, 1),
            "value":  round(current, 2),
            "unit":   "% breakeven (proxy)",
            "detail": f"TIP/IEF proxy ≈{current:.2f}% | {regime} | FRED unavailable",
            "raw":    ratio.tail(60).tolist(),
        }
    except Exception as exc2:
        log.warning("inflation yfinance fallback also failed: %s", exc2)
        return {
            "name": "Inflation Expectations", "score": 50.0, "value": None,
            "unit": "% breakeven", "detail": f"FRED unavailable: {orig_err}", "raw": [],
        }
