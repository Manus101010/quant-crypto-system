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
import json
import datetime
from triggers import db as tdb
from skills.scanner import run_crypto_scan, ScanCriteria
from utils.crypto_universe import get_top_crypto
from utils.logger import get_logger

log = get_logger(__name__)

_MR_BOOST = 1.15          # mean-reversion setups get a 15% composite edge
_RSI2_RECLAIM = 12.0      # RSI(2) level a MR long must turn back up through to confirm
_MIN_DEPLOY_TO_ARM = 45.0 # macro Deployment Score below this = risk-off → don't arm
_MAX_CANDIDATES = 60      # how many ranked setups to SHOW (we still only arm top_n)


def _management_params(setup_label: str | None = None) -> dict | None:
    """
    The validated trade-management config for a setup (stop_mult, target_r,
    trailing, max_hold). Prefers the per-setup map saved by validate_per_setup;
    falls back to the global management, then to the code default for the label.
    """
    try:
        from backtesting.crypto_validation import load_validation
        v = load_validation() or {}
        if setup_label:
            per = (v.get("management_by_setup") or {}).get(setup_label)
            if per:
                return per
        glob = (v.get("meta", {}).get("params", {}) or {}).get("management")
        if glob and not v.get("management_by_setup"):
            return glob
    except Exception:
        pass
    if setup_label:
        try:
            from backtesting.crypto_optimize import management_for
            return management_for(setup_label)
        except Exception:
            return None
    return None


def _management_note(setup_label: str | None = None) -> str:
    """The trade management the backtested edge requires (from the saved validation)."""
    m = _management_params(setup_label)
    if m:
        if m.get("trailing"):
            return (f"Manage: trail a {m['stop_mult']}×ATR stop, hold up to "
                    f"{m['max_hold']} days, let winners run.")
        return (f"Manage: {m['stop_mult']}×ATR stop, take profit at {m['target_r']}R, "
                f"hold up to {m['max_hold']} days.")
    return "Manage per the Validation page."


def _num(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"[-+]?\d[\d,]*\.?\d*", str(s).replace("$", ""))
    return float(m.group().replace(",", "")) if m else None


def _diversify(rows: list[dict], n: int, max_per_setup: int | None) -> list[dict]:
    """
    Pick the top-`n` rows (already sorted best-first) while capping how many of any
    single setup can be included, so the result is a SPREAD across setup types
    rather than 10 of whatever setup is most common today. Fills round-robin: the
    best of each setup first, then the next-best of each, etc. If the cap can't
    fill n (few setup types today), the remaining slots fall back to best-first.
    """
    if not max_per_setup or max_per_setup <= 0:
        return rows[:n]
    from collections import defaultdict
    buckets: dict[str, list] = defaultdict(list)
    for r in rows:
        buckets[r.get("setup_label")].append(r)
    picked, used = [], defaultdict(int)
    # Round-robin passes across setup buckets (each already best-first).
    for _pass in range(max_per_setup):
        for label, bucket in buckets.items():
            if used[label] < len(bucket) and _pass < max_per_setup:
                picked.append(bucket[_pass])
                used[label] += 1
    picked.sort(key=lambda r: -r.get("_composite", 0))
    picked = picked[:n]
    # Backfill if the cap left us short of n (not enough distinct setups).
    if len(picked) < n:
        chosen = {id(r) for r in picked}
        for r in rows:
            if id(r) not in chosen:
                picked.append(r)
                if len(picked) >= n:
                    break
    return picked


def run_scan_and_arm(universe_size: int = 100, top_n: int = 10,
                     regime_score: float | None = None,
                     expiry_hours: int = 48,
                     min_vol_usd_m: float = 1.0,
                     source: str = "top_mcap",
                     max_per_setup: int | None = 4) -> dict:
    """
    Scan, rank (MR-weighted), and arm the top-N triggers. Replaces any previously
    active triggers (a fresh scan supersedes the last). Returns:
        {"candidates": [...ranked rows...], "armed": [...trigger summaries...]}

    `source`: "top_mcap" (CoinGecko top-N by market cap, default) or "mexc"
    (every tradeable MEXC USDT spot pair — thousands of coins, candles pinned to
    MEXC). A volume floor (`min_vol_usd_m`) keeps the MEXC universe tradeable.
    `max_per_setup`: cap how many of any one setup can be armed, so the armed set
    is diverse (None/0 = no cap).
    """
    if source == "mexc":
        from utils.exchange import list_spot_symbols
        tickers = list_spot_symbols("mexc")
        exchange = "mexc"
    else:
        tickers = get_top_crypto(universe_size)
        exchange = None
    df = run_crypto_scan(
        tickers=tickers,
        criteria=ScanCriteria(min_price=0.0, above_sma200=False,
                              above_sma50=False, min_volume_usd_m=min_vol_usd_m),
        regime_score=regime_score,
        exchange=exchange,
    )
    if df.empty:
        return {"candidates": [], "armed": []}

    rows = [r for r in df.to_dict("records")
            if (r.get("trade") or {}).get("action") in ("BUY", "SELL/EXIT")]

    # ── Edge gate: only arm setups with a measured positive edge on crypto ─────
    # If a backtest validation exists, drop setups that failed it (PF ≤ 1). This
    # is the institutional discipline: don't trade a setup with no proven edge.
    from backtesting.crypto_validation import validated_labels
    valid = validated_labels()
    gated_out = []
    if valid is not None:
        kept = [r for r in rows if r.get("setup_label") in valid]
        gated_out = sorted({r.get("setup_label") for r in rows
                            if r.get("setup_label") not in valid})
        rows = kept

    # Mean-reversion-weighted composite ranking.
    for r in rows:
        conv = r.get("conviction") or 0
        boost = _MR_BOOST if r.get("setup_category") == "mean_reversion" else 1.0
        r["_composite"] = round(conv * boost, 1)
    rows.sort(key=lambda r: -r["_composite"])
    # Diversify: cap any single setup so the armed set is a spread across setup
    # types, not 10 of whatever setup is most common in today's market.
    top = _diversify(rows, top_n, max_per_setup)     # armed as live triggers
    candidates = rows[:_MAX_CANDIDATES]              # full ranked list shown to the user

    # ── Regime gate: the setups' edge is regime-dependent (strong in trend,
    # weak in chop/bear per the backtest), so only ARM in a risk-on regime.
    # Below the threshold we still show candidates but arm nothing and keep any
    # existing triggers untouched. The macro Deployment Score is the filter.
    if regime_score is not None and regime_score < _MIN_DEPLOY_TO_ARM:
        return {"candidates": candidates, "armed": [], "edge_gated": valid is not None,
                "gated_out_setups": gated_out, "regime_blocked": True,
                "regime_score": regime_score, "actionable": len(rows),
                "management": "Exits are set per setup (breakouts trail; mean-reversion "
                              "& momentum take a fixed target)."}

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
        mgmt = _management_params(r.get("setup_label"))   # per-setup validated exits
        entry, target, stop = _num(trade.get("entry")), _num(trade.get("target")), _num(trade.get("stop"))
        # 20-day mean = Bollinger midline (from the scan's BB bands).
        bb_u, bb_l = r.get("bb_upper"), r.get("bb_lower")
        mean20 = (bb_u + bb_l) / 2 if (bb_u is not None and bb_l is not None) else ref

        # ── Align stop/target to the VALIDATED management (not the equity-tuned
        # trade_suggestion): stop = stop_mult×ATR; if the validated config trails,
        # drop the fixed target, otherwise set target = target_r × risk so the
        # live suggestion matches exactly what was backtested. Without a
        # validation, fall back to the suggestion.
        atr = r.get("atr_14")
        base_px = entry or ref
        if mgmt and atr and base_px:
            sm = mgmt.get("stop_mult", 3.5)
            risk = sm * atr
            if direction == "long":
                stop = round(base_px - risk, 8)
                target = None if mgmt.get("trailing") else \
                    round(base_px + mgmt.get("target_r", 3.0) * risk, 8)
            else:
                stop = round(base_px + risk, 8)
                target = None if mgmt.get("trailing") else \
                    round(base_px - mgmt.get("target_r", 3.0) * risk, 8)

        if cat == "mean_reversion" and direction == "long":
            # Multi-factor bounce confirmation (evaluated live by the monitor):
            # RSI(2) turns up through the level + green bar + still below the mean
            # + above the stop. Auto-invalidates if the stop is hit first.
            ctype, cval = "mr_reversal_long", _RSI2_RECLAIM
            cond = {"kind": "mr_reversal", "rsi2_level": _RSI2_RECLAIM,
                    "mean": mean20, "stop": stop}
            desc = f"RSI2↑{_RSI2_RECLAIM:.0f} + green bar + price<mean({mean20:.4g}) + >stop"
        elif direction == "long":
            level = entry if (entry and ref and entry > ref) else (ref or entry) * 1.005
            ctype, cval = "breakout_long", level
            cond = {"kind": "breakout", "level": level, "stop": stop, "rsi_max": 80}
            desc = f"close>{level:.4g} breakout + RSI14<80 (invalidate<stop)"
        else:
            level = entry if (entry and ref and entry < ref) else (ref or entry) * 0.995
            ctype, cval = "breakdown_short", level
            cond = {"kind": "breakdown", "level": level, "stop": stop, "rsi_min": 20}
            desc = f"close<{level:.4g} breakdown + RSI14>20 (invalidate>stop)"

        tid = tdb.add_trigger(
            symbol=r["ticker"], condition_type=ctype, condition_value=float(cval),
            condition_json=json.dumps(cond),
            setup_label=r.get("setup_label"), setup_category=cat, direction=direction,
            timeframe="1d", ref_price=ref, entry=entry, target=target, stop=stop,
            rr=_num(trade.get("rr")), composite=r["_composite"], expires_at=expires,
            note=trade.get("note"),
        )
        armed.append({
            "id": tid, "symbol": r["ticker"], "setup_label": r.get("setup_label"),
            "category": cat, "direction": direction, "composite": r["_composite"],
            "condition": desc, "management": _management_note(r.get("setup_label")),
        })

    log.info("scan_and_arm: %d candidates, armed top %d (cancelled %d prior)",
             len(rows), len(armed), cancelled)
    return {"candidates": candidates, "armed": armed,
            "edge_gated": valid is not None, "gated_out_setups": gated_out,
            "regime_blocked": False, "actionable": len(rows),
            "management": "Exits are set per setup (breakouts trail and let winners "
                          "run; mean-reversion & momentum take a fixed target) — the "
                          "backtested edge for each. See each trigger's plan."}
