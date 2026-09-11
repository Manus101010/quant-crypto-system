"""
Portfolio-level risk control for the QuantCore paper-trading loop.

Roadmap item #3 — see docs/INSTITUTIONAL_ROADMAP.md §3 "Risk Management":
  - Tier 1: portfolio max-drawdown governor — when equity drops X% from its
    high-water mark, cut new-position sizing (and eventually halt) until recovery.
  - Tier 1: wire the macro Deployment Score into a regime-conditional leverage
    scalar (gross ~0.5x in risk-off, ~1.0x neutral, full in confirmed risk-on).

Today the system has ONLY per-trade risk (Kelly + ATR stop, skills/risk_manager.py).
This module adds the missing *portfolio-level* governors:
  1. regime_exposure_scalar  — scale gross exposure by macro regime.
  2. current_drawdown        — peak-to-current drawdown from the closed-trade equity curve.
  3. drawdown_governor       — tiered cut/halt based on drawdown depth.
  4. max_new_trades          — combine both scalars into an allowed new-trade count.
  5. risk_state              — the full combined picture for the dashboard.

Import-clean: db access is imported lazily inside functions so this module can be
imported without side effects.
"""

from __future__ import annotations

# Regime scalar anchor points (Deployment Score → gross-exposure multiplier).
# Deployment Score is 0-100; high = risk-on. Clamped to [0.3, 1.0].
_REGIME_RISK_OFF      = 30.0   # at/below this → 0.3 (de-risked)
_REGIME_NEUTRAL       = 50.0   # ~ this → ~0.6
_REGIME_RISK_ON       = 80.0   # at/above this → 1.0 (full risk-on)
_SCALAR_FLOOR         = 0.3
_SCALAR_CEIL          = 1.0
_SCALAR_NEUTRAL       = 0.6    # used for None / missing macro score

# Drawdown governor tiers (peak-to-current drawdown %, positive = down from peak).
_DD_REDUCE_THRESHOLD  = 8.0    # < 8%  → normal (1.0)
_DD_HALT_THRESHOLD    = 15.0   # 8-15% → reduce (0.5); >= 15% → halt (0.0)


def regime_exposure_scalar(macro_score: float | None) -> float:
    """
    Map the macro Deployment Score to a gross-exposure multiplier in [0.3, 1.0].

    Roadmap §3 Tier 1: regime-conditional leverage scalar. The system already
    computes the Deployment Score to gate *whether* to deploy; here we let it
    also size *how much* of the book to put on.

      ~80+ → 1.0   (full risk-on)
      ~50  → ~0.6  (neutral)
      <=30 → 0.3   (risk-off, minimum gross)
      None → 0.6   (neutral default when macro is unavailable)

    Piecewise-linear and clamped: linear from 0.3 (at score 30) to 0.6 (at 50),
    then linear from 0.6 (at 50) to 1.0 (at 80), flat outside the band.
    """
    if macro_score is None:
        return _SCALAR_NEUTRAL

    s = float(macro_score)

    if s <= _REGIME_RISK_OFF:
        return _SCALAR_FLOOR
    if s >= _REGIME_RISK_ON:
        return _SCALAR_CEIL

    if s <= _REGIME_NEUTRAL:
        # Linear 30→50 mapped to 0.3→0.6
        frac = (s - _REGIME_RISK_OFF) / (_REGIME_NEUTRAL - _REGIME_RISK_OFF)
        scalar = _SCALAR_FLOOR + frac * (_SCALAR_NEUTRAL - _SCALAR_FLOOR)
    else:
        # Linear 50→80 mapped to 0.6→1.0
        frac = (s - _REGIME_NEUTRAL) / (_REGIME_RISK_ON - _REGIME_NEUTRAL)
        scalar = _SCALAR_NEUTRAL + frac * (_SCALAR_CEIL - _SCALAR_NEUTRAL)

    # Clamp defensively.
    return max(_SCALAR_FLOOR, min(_SCALAR_CEIL, round(scalar, 4)))


def current_drawdown() -> dict:
    """
    Build a cumulative net-P&L equity curve from CLOSED paper trades (ordered by
    exit_date) and compute peak-to-current drawdown %.

    The equity curve is the running sum of per-trade NET pnl % (actual_pnl_pct,
    already net of transaction costs in db.py). This is a simple additive curve in
    "% return units" — adequate for a drawdown governor where we only need the
    peak-to-trough decline, not compounded dollar equity.

    Returns:
      {equity, peak, drawdown_pct, n_closed}
        equity        — current cumulative net P&L (sum of closed pnl %)
        peak          — high-water mark of that cumulative curve
        drawdown_pct  — peak - current, in percentage points (0 if at/above peak)
        n_closed      — number of closed trades used
    """
    from paper_trades import db as pdb

    closed = [
        r for r in pdb.get_trades(status="closed")
        if r.get("actual_pnl_pct") is not None
    ]
    # Order chronologically by exit_date (fallback to created_at / id for ties).
    closed.sort(key=lambda r: (r.get("exit_date") or "", r.get("created_at") or "", r.get("id") or 0))

    equity = 0.0
    peak = 0.0
    for r in closed:
        equity += float(r.get("actual_pnl_pct") or 0.0)
        if equity > peak:
            peak = equity

    # Drawdown in percentage points below the high-water mark (never negative).
    drawdown_pct = max(0.0, peak - equity)

    return {
        "equity":       round(equity, 3),
        "peak":         round(peak, 3),
        "drawdown_pct": round(drawdown_pct, 3),
        "n_closed":     len(closed),
    }


def drawdown_governor(drawdown_pct: float) -> dict:
    """
    Tiered max-drawdown governor (roadmap §3 Tier 1).

      drawdown < 8%   → "normal"  scalar 1.0  (no de-risking)
      8% <= dd < 15%  → "reduce"  scalar 0.5  (halve new trades)
      dd >= 15%       → "halt"    scalar 0.0  (open no new trades)

    Returns {level, scalar, reason}.
    """
    dd = float(drawdown_pct or 0.0)

    if dd >= _DD_HALT_THRESHOLD:
        return {
            "level":  "halt",
            "scalar": 0.0,
            "reason": f"drawdown {dd:.1f}% >= {_DD_HALT_THRESHOLD:.0f}% — halting new trades",
        }
    if dd >= _DD_REDUCE_THRESHOLD:
        return {
            "level":  "reduce",
            "scalar": 0.5,
            "reason": f"drawdown {dd:.1f}% in [{_DD_REDUCE_THRESHOLD:.0f}%, {_DD_HALT_THRESHOLD:.0f}%) — halving new trades",
        }
    return {
        "level":  "normal",
        "scalar": 1.0,
        "reason": f"drawdown {dd:.1f}% < {_DD_REDUCE_THRESHOLD:.0f}% — normal sizing",
    }


def risk_state(macro_score: float | None) -> dict:
    """
    Full combined portfolio-risk picture for the dashboard / loop summary.

    Combines the regime exposure scalar with the drawdown governor and reports
    the components plus the combined gross-exposure scalar (regime x drawdown).
    """
    regime_scalar = regime_exposure_scalar(macro_score)
    dd = current_drawdown()
    gov = drawdown_governor(dd["drawdown_pct"])
    combined = round(regime_scalar * gov["scalar"], 4)

    return {
        "macro_score":      macro_score,
        "regime_scalar":    regime_scalar,
        "drawdown":         dd,
        "drawdown_gov":     gov,
        "combined_scalar":  combined,
        "halt":             combined == 0.0,
    }


def max_new_trades(base_max: int, macro_score: float | None = None, *, state: dict | None = None) -> int:
    """
    Decide how many new trades may open this run.

    allowed = floor(base_max * regime_scalar * drawdown_scalar), floored at 0.

    A drawdown "halt" (scalar 0.0) forces allowed to 0 regardless of base_max.
    `state` may be passed in to avoid recomputing the equity curve (e.g. when the
    caller already obtained risk_state()); otherwise it is computed here.
    """
    if base_max <= 0:
        return 0

    st = state if state is not None else risk_state(macro_score)
    allowed = int(base_max * st["combined_scalar"])  # int() truncates toward zero
    return max(0, allowed)
