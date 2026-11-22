#!/usr/bin/env python3
"""
After school trade message (22 Nov 2026).

Research alerts (Distribution Short, Downtrend Bounce Fade) fire at the daily close,
00:00 UTC = 11am Sydney, while he is teaching. He found the instant alerts too hard
to follow (wide stops, a trailing stop to move by hand for 60 days, a 0.3% "skip if"
window, a second AI message). research/ds_practical/run.py tested the version he can
actually trade: enter about 6h after the close and set stop + take profit once.
Distribution Short, held back data (Pionex coins, taker costs): PF 1.46, +0.23R,
t 2.67 (random entries PF 0.96). In sample PF 2.07, t 5.76.

So: alerts fire silently, and at 5pm Sydney this sends ONE message with every trade
still worth placing, levels worked out from the price right now:
  Distribution Short: stop = the signal's stop, capped at 15% above price;
                      take profit = 2x that risk below; close after 30 days.
  Downtrend Bounce Fade: its own stop and target (skipped if price is outside them).
The plan is saved (app_state "plan:<id>") and the outcome tracker grades the trade
on it, so the track record matches what he would have done.
Signal only: nothing here places an order.
"""
from __future__ import annotations

import datetime as dt
import json

from triggers import db as tdb
from utils.logger import get_logger

log = get_logger("trade_digest")

STOP_CAP = 0.15          # research/ds_practical: SET15
TP_R = 2.0
MAX_DAYS = 30
DIGEST_SETUPS = ("Distribution Short", "Downtrend Bounce Fade")


def _p(x: float) -> str:
    from desk.botplan import _p as fmt
    return fmt(float(x))


def plan_for(t: dict, price: float) -> dict | None:
    """The set and forget plan from the price now, or None if not worth placing."""
    if not price or price <= 0 or t.get("direction") != "short":
        return None
    stop = t.get("stop")
    if not stop or stop <= price:
        return None                              # already through its stop
    if t.get("setup_label") == "Distribution Short":
        stop = min(stop, price * (1 + STOP_CAP))
        target = price - TP_R * (stop - price)
        days = MAX_DAYS
    else:
        target = t.get("target") or t.get("tp")
        days = 10
        if not target or target >= price:
            return None                          # already at or past its target
    if target <= 0:
        return None
    return {"entry": price, "stop": stop, "target": target, "max_hold": days}


def _live_price(symbol: str) -> float | None:
    from config import CANDLE_VENUE
    from utils.exchange import get_ohlcv
    try:
        df = get_ohlcv(symbol, "1h", 3, exchange=CANDLE_VENUE)
        return float(df["close"].iloc[-1]) if df is not None and len(df) else None
    except Exception as exc:                     # noqa: BLE001
        log.warning("digest: no price for %s (%s)", symbol, exc)
        return None


def pending(now: dt.datetime | None = None) -> list[dict]:
    """Research alerts from the last 24h that have not been in a digest yet."""
    now = now or dt.datetime.utcnow()
    cutoff = (now - dt.timedelta(hours=24)).isoformat()
    from triggers.outcomes import is_basket_capped
    out = []
    for t in tdb.get_triggers_since(cutoff, statuses=("fired",)):
        if (t.get("setup_label") in DIGEST_SETUPS and t.get("outcome") is None
                and not is_basket_capped(t) and not tdb.get_state(f"plan:{t['id']}")
                and not tdb.get_state(f"digest_skip:{t['id']}")):
            out.append(t)
    return out


def build(now: dt.datetime | None = None, *, prices: dict | None = None, save: bool = True) -> str:
    rows = pending(now)
    if not rows:
        return ""
    try:
        from triggers.outcomes import planned_position
    except Exception:                            # noqa: BLE001
        planned_position = None
    cards, skipped = [], []
    for t in rows:
        coin = t["symbol"].replace("-USD", "")
        px = (prices or {}).get(t["symbol"]) if prices is not None else _live_price(t["symbol"])
        plan = plan_for(t, px) if px else None
        if not plan:
            skipped.append(coin)
            if save:
                tdb.set_state(f"digest_skip:{t['id']}", "1")
            continue
        pos = planned_position(plan["entry"], plan["stop"]) if planned_position else None
        size = f"${pos['margin']:.0f} margin at {pos['leverage']}x" if pos else "your normal size"
        cards.append(
            f"🔴 <b>Short {coin}</b>\n"
            f"Entry {_p(plan['entry'])} · Stop {_p(plan['stop'])} · Take profit {_p(plan['target'])}\n"
            f"{size}, Isolated. Close after {plan['max_hold']} days if neither hits.")
        if save:
            tdb.set_state(f"plan:{t['id']}", json.dumps(
                {**plan, "at": (now or dt.datetime.utcnow()).isoformat()}))
    if not cards and not skipped:
        return ""
    head = [f"📋 <b>Today's trades</b> ({len(cards)})"]
    if cards:
        head.append("Place each once on Pionex Futures: Sell / Short, Limit at the entry, tick "
                    "TP/SL and enter both. Then leave it.")
    body = "\n\n".join(cards)
    tail = []
    if skipped:
        tail.append("Skipped (price already through the stop or target since 11am): "
                    + ", ".join(skipped))
    tail.append("Took one? Send /took COIN.")
    return "\n\n".join(x for x in ["\n".join(head), body, "\n".join(tail)] if x)


def with_plan(t: dict) -> dict:
    """Overlay a saved 5pm plan so the tracker grades what he would have done."""
    try:
        raw = tdb.get_state(f"plan:{t['id']}")
        if not raw:
            return t
        plan = json.loads(raw)
        cond = {}
        try:
            cond = json.loads(t.get("condition_json") or "{}") or {}
        except (TypeError, ValueError):
            cond = {}
        cond["max_hold"] = plan.get("max_hold", MAX_DAYS)
        return {**t, "fired_price": plan["entry"], "stop": plan["stop"],
                "target": plan["target"], "condition_json": json.dumps(cond)}
    except Exception as exc:                     # noqa: BLE001
        log.debug("with_plan %s: %s", t.get("id"), exc)
        return t


if __name__ == "__main__":
    print(build(save=False) or "(nothing pending)")
