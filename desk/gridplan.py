"""
MEXC futures grid-bot plan that lives INSIDE a signal's trade plan.

The grid trades the oscillations between the signal's stop and its target; the
bot's stop-loss price is the signal's stop. Leverage is the highest (≤ cap) that
keeps the estimated liquidation price GRID_LIQ_BUFFER beyond that stop, so the
stop always triggers before liquidation. Investment is sized so the WORST case —
every grid rung filled on the way to the stop, then stopped — loses about the
normal per-trade risk. Leverage therefore only reduces the margin you tie up;
it never increases the $ you can lose.

MEXC grid bots have no automatic %-stop, so the stop price must be typed into
the bot, and the monitor also sends a "stop your bot" alert when it's hit.
"""
from __future__ import annotations
import math
from config import GRID_MAX_LEVERAGE, GRID_LIQ_BUFFER, GRID_MMR, GRID_FEE_PCT


def grid_for_signal(direction: str, price: float, stop: float, target: float | None,
                    atr: float | None, risk_usd: float) -> dict:
    out = {"ok": False}
    if not price or not stop or stop <= 0:
        return {**out, "note": "no usable stop"}
    short = direction == "short"
    if (not short and stop >= price) or (short and stop <= price):
        return {**out, "note": "stop is on the wrong side of price"}
    atr = atr or abs(price - stop) / 3.0

    # Range: just inside the stop → the target (or ~3 daily moves if trailing).
    edge = 0.25 * atr
    if short:
        upper = stop - edge
        lower = target if target and target < price else price - 3 * atr
    else:
        lower = stop + edge
        upper = target if target and target > price else price + 3 * atr
    if upper <= lower or lower <= 0:
        return {**out, "note": "range too narrow for a grid"}

    # Rungs about half a daily move apart, but never so tight that fees eat them.
    step = max(0.5 * atr, price * (4 * GRID_FEE_PCT) / 100)
    count = int(min(60, max(6, round((upper - lower) / step))))
    step = (upper - lower) / count
    step_pct = step / price * 100
    net_per_grid = step_pct - 2 * GRID_FEE_PCT

    # Fully-filled position (worst case): rungs on the far side of price are
    # opened at the start (at price), the rest at their own level.
    levels = [lower + step * (i + 0.5) for i in range(count)]
    costs = [max(l, price) for l in levels] if short else [min(l, price) for l in levels]

    def loss_frac(px: float) -> float:          # loss per $1 of notional at price px
        return (sum(px / c - 1 for c in costs) if short
                else sum(1 - px / c for c in costs)) / count

    lf_stop = loss_frac(stop)
    if lf_stop <= 0:
        return {**out, "note": "cannot size"}
    notional = risk_usd / lf_stop              # stop-out with every rung filled ≈ risk_usd
    qty = sum((notional / count) / c for c in costs)

    # Leverage: the highest (≤ cap) where the FULLY-FILLED position still has
    # margin left GRID_LIQ_BUFFER beyond the stop — so the stop always hits first.
    probe = stop * (1 + GRID_LIQ_BUFFER) if short else stop * (1 - GRID_LIQ_BUFFER)

    def survives(L: int) -> bool:
        equity = notional / L - notional * loss_frac(probe)
        return equity > GRID_MMR * qty * probe

    lev = next((L for L in range(GRID_MAX_LEVERAGE, 0, -1) if survives(L)), 0)
    if not lev:
        return {**out, "note": "too volatile for a leveraged grid — use spot or skip"}
    margin = notional / lev

    # Estimated liquidation of the fully-filled position (bisection on price).
    lo_p, hi_p = (probe, price * 3) if short else (0.0, probe)
    for _ in range(60):
        mid = (lo_p + hi_p) / 2
        alive = margin - notional * loss_frac(mid) > GRID_MMR * qty * mid
        if short:
            lo_p, hi_p = (mid, hi_p) if alive else (lo_p, mid)
        else:
            lo_p, hi_p = (lo_p, mid) if alive else (mid, hi_p)
    liq = (lo_p + hi_p) / 2
    lev_max = lev

    return {"ok": True, "mode": "Short" if short else "Long", "lower": lower, "upper": upper,
            "grids": count, "step_pct": step_pct, "net_per_grid_pct": net_per_grid,
            "leverage": lev, "lev_max": lev_max, "liq_est": liq, "stop_loss": stop,
            "take_profit": (target if target else None), "margin": margin,
            "notional": notional, "worst_loss": risk_usd}
