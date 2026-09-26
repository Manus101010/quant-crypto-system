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
from utils import exchange as _xch
from utils.logger import get_logger

log = get_logger(__name__)

_MR_BOOST = 1.0           # NEUTRAL — setup types compete on measured edge, not a thumb on the scale
_RSI2_RECLAIM = 12.0      # RSI(2) level a MR long must turn back up through to confirm
_RSI2_FADE = 88.0         # RSI(2) level a MR short must turn back down through to confirm
_MIN_DEPLOY_TO_ARM = 45.0 # macro Deployment Score below this = risk-off → don't arm
_MAX_CANDIDATES = 60      # how many ranked setups to SHOW (we still only arm top_n)

# Funding-crowding extremes, per 8h funding interval. Baseline is ~+0.01%;
# ±0.05% (≈ ±55% annualised) is the level funding analysers treat as crowded.
_FUNDING_LONG_CROWDED = 0.0005    # longs paying this much → don't arm a new long
_FUNDING_SHORT_CROWDED = -0.0005  # shorts paying this much → don't arm a new short


def _crowded(direction: str, rate: float) -> bool:
    """True only at an extreme on the trade's own side; neutral funding → False."""
    if direction == "long":
        return rate >= _FUNDING_LONG_CROWDED
    return rate <= _FUNDING_SHORT_CROWDED


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


def _setup_key(r: dict) -> tuple:
    """Cap key = setup type AND direction (a long and short of the same setup are
    different types for capping — matters once shorts are added)."""
    return (r.get("setup_label"), r.get("direction") or "long")


def _diversify(rows: list[dict], n: int, max_per_setup: int | None) -> list[dict]:
    """
    Build the armed set (rows already sorted best-first) with three rules:

      1. DEDUPE BY SYMBOL — one trigger per coin, keep its highest-composite setup.
      2. PER-SETUP CAP — round-robin across setup types (best of each first), no
         type exceeds `max_per_setup`, so the set is a spread not 20 copies.
      3. HARD 50% CEILING — no single setup type may ever exceed half of `n`, even
         via backfill. When only one type is firing we LEAVE SLOTS EMPTY rather
         than fake diversity — that is deliberate, not a bug.
    """
    from collections import defaultdict

    # 1) Dedupe by symbol (rows are best-first, so first seen = highest composite).
    seen_sym, deduped = set(), []
    for r in rows:
        sym = r.get("ticker") or r.get("symbol")
        if sym in seen_sym:
            continue
        seen_sym.add(sym)
        deduped.append(r)
    rows = deduped

    if not max_per_setup or max_per_setup <= 0:
        return rows[:n]

    ceiling = max(1, n // 2)                 # hard: no type past 50% of slots
    cap = min(max_per_setup, ceiling)

    buckets: dict[tuple, list] = defaultdict(list)
    for r in rows:
        buckets[_setup_key(r)].append(r)

    picked, used = [], defaultdict(int)
    # Round-robin passes, best-of-each-type first, up to the per-setup cap.
    for _pass in range(cap):
        for key, bucket in buckets.items():
            if _pass < len(bucket):
                picked.append(bucket[_pass])
                used[key] += 1
    picked.sort(key=lambda r: -r.get("_composite", 0))
    picked = picked[:n]

    # Backfill toward n, but NEVER push a type past the 50% ceiling. If we run out
    # of eligible rows, the remaining slots stay EMPTY (no faked variety).
    if len(picked) < n:
        chosen = {id(r) for r in picked}
        for r in rows:
            if len(picked) >= n:
                break
            if id(r) in chosen:
                continue
            key = _setup_key(r)
            if used[key] >= ceiling:
                continue
            picked.append(r)
            used[key] += 1
    return picked


def run_scan_and_arm(universe_size: int = 100, top_n: int = 10,
                     regime_score: float | None = None,
                     expiry_hours: int = 48,
                     min_vol_usd_m: float = 1.0,
                     source: str = "top_mcap",
                     max_per_setup: int | None = 4,
                     max_stop_pct: float | None = 40.0) -> dict:
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

    # BUY = long entry, SELL = short entry (MEXC futures/perp). SELL/EXIT is a
    # take-profit flag on an open long, not an entry — excluded.
    rows = []
    for r in df.to_dict("records"):
        action = (r.get("trade") or {}).get("action")
        if action == "BUY":
            r["direction"] = "long"
            rows.append(r)
        elif action == "SELL":
            r["direction"] = "short"
            rows.append(r)

    # ── Edge gate: only arm setups with a measured positive edge on crypto ─────
    # If a backtest validation exists, drop setups that failed it (PF ≤ 1). This
    # is the institutional discipline: don't trade a setup with no proven edge.
    from backtesting.crypto_validation import validated_labels
    valid = validated_labels()
    gated_out = []
    if valid is not None:
        # Subtract setups auto-deactivated by the revalidation job (edge decayed).
        # They stop arming NEW triggers; existing armed triggers are left alone.
        deactivated = tdb.get_deactivated()
        valid = valid - deactivated
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
    wide_stop_excluded = []
    crowded_excluded = []
    # Perp funding for just the coins we might arm (off the monitor hot path).
    # Coins without a perp return nothing → never vetoed.
    try:
        funding = _xch.get_funding_rates([r["ticker"] for r in top])
    except Exception as exc:                       # noqa: BLE001 — filter is advisory
        log.warning("scan_and_arm: funding fetch failed — %s", exc)
        funding = {}
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

        # ── Crowding filter (extremes only): funding is the price of holding the
        # crowded side. Normal funding blocks nothing — both longs and shorts stay
        # live. Only an extreme on the SAME side as the trade vetoes it.
        fr = funding.get(r["ticker"])
        if fr is not None and _crowded(direction, fr):
            crowded_excluded.append(f"{r['ticker']} {direction} (funding {fr*100:+.3f}%)")
            continue

        # ── Nonsense-stop guard (always on, even with the max-stop gate off): a
        # 3.5×ATR stop on a hyper-vol coin can land below zero — no real level.
        if direction == "long" and stop is not None and stop <= 0:
            wide_stop_excluded.append(f"{r['ticker']} (stop ≤ 0)")
            continue

        # ── Max-stop risk gate: a stop this far from entry is a huge single-trade
        # loss on a full-size position (hyper-vol microcaps). Don't arm it.
        if max_stop_pct and base_px and stop:
            stop_pct = abs(base_px - stop) / base_px * 100
            if stop_pct > max_stop_pct:
                wide_stop_excluded.append(f"{r['ticker']} (−{stop_pct:.0f}%)")
                continue

        if cat == "mean_reversion" and direction == "long":
            # Multi-factor bounce confirmation (evaluated live by the monitor):
            # RSI(2) turns up through the level + green bar + still below the mean
            # + above the stop. Auto-invalidates if the stop is hit first.
            ctype, cval = "mr_reversal_long", _RSI2_RECLAIM
            cond = {"kind": "mr_reversal", "rsi2_level": _RSI2_RECLAIM,
                    "mean": mean20, "stop": stop}
            desc = f"RSI2↑{_RSI2_RECLAIM:.0f} + green bar + price<mean({mean20:.4g}) + >stop"
        elif cat == "mean_reversion" and direction == "short":
            # Overbought bounce rolls over: RSI(2) turns back DOWN through the
            # level + red bar + still above the mean + below the stop.
            ctype, cval = "mr_reversal_short", _RSI2_FADE
            cond = {"kind": "mr_reversal_short", "rsi2_level": _RSI2_FADE,
                    "mean": mean20, "stop": stop}
            desc = f"RSI2↓{_RSI2_FADE:.0f} + red bar + price>mean({mean20:.4g}) + <stop"
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
            "wide_stop_excluded": wide_stop_excluded,
            "crowded_excluded": crowded_excluded,
            "management": "Exits are set per setup (breakouts trail and let winners "
                          "run; mean-reversion & momentum take a fixed target) — the "
                          "backtested edge for each. See each trigger's plan."}
