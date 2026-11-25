#!/usr/bin/env python3
"""
After school trade message (22 Nov 2026).

Research alerts (Distribution Short, Downtrend Bounce Fade) fire at the daily close,
00:00 UTC = 11am Sydney, while he is teaching, and the instant alerts were too hard to
follow. research/ds_practical/run.py (pre-registered, 9 variants) tested entering
about 6h after the close. He trades on Bybit, which holds a trailing stop natively,
so the whole trade is placed ONCE: entry, stop, take profit and trailing distance.
Distribution Short, 6h delay, live rules (DS stop, 3.5 ATR trail, TP 2R, 60 days):
held back data PF 2.06, +0.30R, t 4.10 (random PF 1.16); in sample PF 2.18, t 5.54.

At 7am (inside the morning brief), 3:30pm and 7pm Sydney this sends every NEW trade
still worth placing (each trade once, in the first slot after it fires), levels
from the price right now:
  Distribution Short: stop = the signal's stop; take profit = 2x that risk below;
                      trailing stop distance = 3.5 x the signal ATR; close after 60 days.
  Downtrend Bounce Fade: its own stop and target, 10 days (kept only with 1R of room;
                      not re-tested at the 6h delay).
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

MIN_STOP, MAX_STOP = 0.01, 0.60   # research kept stops between 1% and 60% (run.py)
TP_R = 2.0
TRAIL_ATR = 3.5          # config.BYBIT_TRAIL["Distribution Short"]
MAX_DAYS = 60
MAX_AGE_H = 30           # a fire older than this is stale: skipped, not offered
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
    trail = None
    if t.get("setup_label") == "Distribution Short":
        target = price - TP_R * (stop - price)
        days = MAX_DAYS
        atr = _cond(t).get("atr")
        try:
            trail = TRAIL_ATR * float(atr) if atr else None
        except (TypeError, ValueError):
            trail = None
        if not trail:
            return None                          # cannot give a trailing distance
    else:
        target = t.get("target") or t.get("tp")
        days = 10
        if not target or target >= price:
            return None                          # already at or past its target
        # Downtrend Bounce Fade was NOT re-tested at a 6h delay (DS was): keep it
        # only while at least 1R of room is left to its own target.
        if price - target < (stop - price):
            return None
    if target <= 0 or not (MIN_STOP <= (stop - price) / price <= MAX_STOP):
        return None
    return {"entry": price, "stop": stop, "target": target, "max_hold": days, "trail": trail}


def _cond(t: dict) -> dict:
    try:
        return json.loads(t.get("condition_json") or "{}") or {}
    except (TypeError, ValueError):
        return {}


def _quiet(t: dict) -> bool:
    return bool(_cond(t).get("quiet"))


def awaiting_digest(t: dict, now: dt.datetime | None = None) -> bool:
    """A quiet research fire that has not been through a trade message yet. Only rows the
    monitor tagged quiet at fire count, never basket capped or taken ones, and never
    for more than 48h (after that the tracker grades it on its original rules)."""
    if (not _quiet(t) or t.get("outcome") is not None or t.get("taken")
            or tdb.get_state(f"plan:{t['id']}")):
        return False
    from triggers.outcomes import is_basket_capped
    if is_basket_capped(t):
        return False
    try:
        age = ((now or dt.datetime.utcnow()) - dt.datetime.fromisoformat(str(t.get("fired_at"))[:19]))
        return age.total_seconds() < 48 * 3600
    except (TypeError, ValueError):
        return False


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
    cutoff = (now - dt.timedelta(hours=48)).isoformat()     # survives one missed slot
    from triggers.outcomes import is_basket_capped
    out = []
    for t in tdb.get_triggers_since(cutoff, statuses=("fired",)):
        if (t.get("setup_label") in DIGEST_SETUPS and _quiet(t) and t.get("outcome") is None
                and not is_basket_capped(t) and not t.get("taken")
                and not tdb.get_state(f"plan:{t['id']}")
                and not tdb.get_state(f"digest_skip:{t['id']}")):
            out.append(t)
    return out


def build(now: dt.datetime | None = None, *, prices: dict | None = None, save: bool = True) -> str:
    msg, recs = prepare(now, prices=prices)
    if save:
        commit(recs)
    return msg


def commit(recs: list[tuple]) -> None:
    """Save plans and skips. Call only AFTER the message was delivered."""
    for kind, tid, payload in recs:
        if kind == "plan":
            tdb.set_state(f"plan:{tid}", payload)
        else:
            tdb.set_state(f"digest_skip:{tid}", "1")
            try:        # never offered: out of the track record and every open list
                tdb.set_outcome(tid, {"outcome": "skipped"})
            except Exception as exc:              # noqa: BLE001
                log.warning("digest: could not mark #%s skipped (%s)", tid, exc)


def prepare(now: dt.datetime | None = None, *, prices: dict | None = None,
            header: str = "Today's trades") -> tuple[str, list]:
    now = now or dt.datetime.utcnow()
    rows = pending(now)
    recs: list[tuple] = []
    if not rows:
        return "", recs
    try:
        from triggers.outcomes import planned_position
    except Exception:                            # noqa: BLE001
        planned_position = None
    cards, skipped = [], []
    for t in rows:
        coin = t["symbol"].replace("-USD", "")
        px = (prices or {}).get(t["symbol"]) if prices is not None else _live_price(t["symbol"])
        try:
            age_h = (now - dt.datetime.fromisoformat(str(t.get("fired_at"))[:19])).total_seconds() / 3600
        except (TypeError, ValueError):
            age_h = 0.0
        plan = plan_for(t, px) if px and age_h <= MAX_AGE_H else None
        if not plan:
            skipped.append(coin)
            recs.append(("skip", t["id"], None))
            continue
        pos = planned_position(plan["entry"], plan["stop"]) if planned_position else None
        size = f"${pos['margin']:.0f} margin at {pos['leverage']}x" if pos else "your normal size"
        trail = f" · Trailing stop {_p(plan['trail'])}" if plan.get("trail") else ""
        cards.append(
            f"🔴 <b>Short {coin}</b>\n"
            f"Entry {_p(plan['entry'])} · Stop {_p(plan['stop'])} · Take profit {_p(plan['target'])}{trail}\n"
            f"{size}, Isolated. Close after {plan['max_hold']} days if still open.")
        recs.append(("plan", t["id"], json.dumps({**plan, "at": now.isoformat()})))
    if not cards and not skipped:
        return "", recs
    head = [f"📋 <b>{header}</b> ({len(cards)})"]
    if cards:
        head.append("Place each once on Bybit: Derivatives, USDT perpetual, Sell / Short, Limit at "
                    "the entry, tick TP/SL and enter both. Once filled, open the position's TP/SL, "
                    "Trailing Stop tab, and enter the trailing distance. Then leave it.")
    body = "\n\n".join(cards)
    tail = []
    if skipped:
        tail.append("Skipped (price already through the stop or target since 11am): "
                    + ", ".join(skipped))
    tail.append("Took one? Send /took COIN.")
    return "\n\n".join(x for x in ["\n".join(head), body, "\n".join(tail)] if x), recs


def with_plan(t: dict) -> dict:
    """Overlay a saved trade message plan so the tracker grades what he would have done."""
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
        cond["tp"] = plan["target"]          # the old fire time 2R must not close it
        at = str(plan.get("at") or t.get("fired_at"))[:13] + ":00:00"   # floored to the hour
        out = {**t, "fired_price": plan["entry"], "stop": plan["stop"], "tp": plan["target"],
               "fired_at": at}
        if plan.get("trail"):
            # Trailing plan: no fixed "target" (that would switch trailing off); the take
            # profit rides in tp, and Bybit holds the trail (no "move your stop" nudges).
            cond["native_trail"] = True
            out["target"] = None
        else:
            out["target"] = plan["target"]
        out["condition_json"] = json.dumps(cond)
        return out
    except Exception as exc:                     # noqa: BLE001
        log.debug("with_plan %s: %s", t.get("id"), exc)
        return t


if __name__ == "__main__":
    print(prepare()[0] or "(nothing pending)")
