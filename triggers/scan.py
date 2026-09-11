"""
Scanner → Triggers orchestrator.

Runs the (ccxt-backed) crypto scanner over a liquid universe, ranks setups by a
composite that is deliberately weighted toward MEAN REVERSION (the user's edge),
and arms the top-N as rows in the triggers table for the monitor to watch.

Each armed trigger gets a machine-checkable condition:
  - mean-reversion long → 'rsi_cross_up'  (wait for the bounce to confirm, not
    catch a knife) — the monitor fires when RSI(14) crosses back above the level.
  - momentum long       → 'price_above'   (breakout / entry level).
  - short               → 'price_below'.

Signal-only: arming a trigger sends the user an alert later; it never trades.
"""
from __future__ import annotations
import re
import datetime
from triggers import db as tdb
from skills.scanner import run_crypto_scan, ScanCriteria
from utils.crypto_universe import get_top_crypto
from utils.logger import get_logger

log = get_logger(__name__)

_MR_BOOST = 1.15          # mean-reversion setups get a 15% composite edge
_RSI_CONFIRM = 35.0       # RSI(14) level a MR long must reclaim to confirm


def _num(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"[-+]?\d[\d,]*\.?\d*", str(s).replace("$", ""))
    return float(m.group().replace(",", "")) if m else None


def run_scan_and_arm(universe_size: int = 100, top_n: int = 10,
                     regime_score: float | None = None,
                     expiry_hours: int = 48,
                     min_vol_usd_m: float = 1.0) -> dict:
    """
    Scan, rank (MR-weighted), and arm the top-N triggers. Replaces any previously
    active triggers (a fresh scan supersedes the last). Returns:
        {"candidates": [...ranked rows...], "armed": [...trigger summaries...]}
    """
    tickers = get_top_crypto(universe_size)
    df = run_crypto_scan(
        tickers=tickers,
        criteria=ScanCriteria(min_price=0.0, above_sma200=False,
                              above_sma50=False, min_volume_usd_m=min_vol_usd_m),
        regime_score=regime_score,
    )
    if df.empty:
        return {"candidates": [], "armed": []}

    rows = [r for r in df.to_dict("records")
            if (r.get("trade") or {}).get("action") in ("BUY", "SELL/EXIT")]

    # Mean-reversion-weighted composite ranking.
    for r in rows:
        conv = r.get("conviction") or 0
        boost = _MR_BOOST if r.get("setup_category") == "mean_reversion" else 1.0
        r["_composite"] = round(conv * boost, 1)
    rows.sort(key=lambda r: -r["_composite"])
    top = rows[:top_n]

    # A fresh scan supersedes the previous armed set.
    cancelled = tdb.clear_active()
    now = datetime.datetime.utcnow()
    expires = (now + datetime.timedelta(hours=expiry_hours)).isoformat()

    armed = []
    for r in top:
        trade = r.get("trade") or {}
        action = trade.get("action")
        direction = "long" if action == "BUY" else "short"
        cat = r.get("setup_category")
        ref = r.get("price")
        entry, target, stop = _num(trade.get("entry")), _num(trade.get("target")), _num(trade.get("stop"))

        if cat == "mean_reversion" and direction == "long":
            # Wait for the bounce to confirm (RSI reclaims the level) — don't
            # catch a knife. rsi_cross_up only fires on the actual cross.
            ctype, cval = "rsi_cross_up", _RSI_CONFIRM
        elif direction == "long":
            # Momentum: require a real breakout above the reference so the alert
            # marks upward confirmation, not an instant fire at current price.
            level = entry if (entry and ref and entry > ref) else (ref or entry) * 1.005
            ctype, cval = "price_above", level
        else:
            level = entry if (entry and ref and entry < ref) else (ref or entry) * 0.995
            ctype, cval = "price_below", level

        tid = tdb.add_trigger(
            symbol=r["ticker"], condition_type=ctype, condition_value=float(cval),
            setup_label=r.get("setup_label"), setup_category=cat, direction=direction,
            timeframe="1d", ref_price=ref, entry=entry, target=target, stop=stop,
            rr=_num(trade.get("rr")), composite=r["_composite"], expires_at=expires,
            note=trade.get("note"),
        )
        armed.append({
            "id": tid, "symbol": r["ticker"], "setup_label": r.get("setup_label"),
            "category": cat, "direction": direction, "composite": r["_composite"],
            "condition": f"{ctype} @ {cval}",
        })

    log.info("scan_and_arm: %d candidates, armed top %d (cancelled %d prior)",
             len(rows), len(armed), cancelled)
    return {"candidates": top, "armed": armed}
