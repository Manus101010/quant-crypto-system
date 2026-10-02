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
    # Prefer a $-prefixed number: text like "Buy the 55-day breakout near $190"
    # must parse as 190, not the 55 in "55-day".
    m = re.search(r"\$\s*([-+]?\d[\d,]*\.?\d*)", str(s))
    if m:
        return float(m.group(1).replace(",", ""))
    m = re.search(r"[-+]?\d[\d,]*\.?\d*", str(s).replace("$", ""))
    return float(m.group().replace(",", "")) if m else None


def _armed_plan(r: dict) -> dict:
    """The exact plan a candidate would be armed with: the VALIDATED management
    for its setup (stop = stop_mult×ATR; trailing setups have no fixed target,
    others target = target_r×risk), not the scanner's generic suggestion. Falls
    back to the suggestion when there's no ATR/management."""
    trade = r.get("trade") or {}
    direction = "long" if trade.get("action") == "BUY" else "short"
    ref = r.get("price")
    entry = _num(trade.get("entry")) or ref
    stop, target = _num(trade.get("stop")), _num(trade.get("target"))
    mgmt = _management_params(r.get("setup_label"))
    trailing = bool(mgmt and mgmt.get("trailing"))
    atr = r.get("atr_14")
    rr = _num(trade.get("rr"))
    if mgmt and atr and entry:
        risk = mgmt.get("stop_mult", 3.5) * atr
        sgn = 1 if direction == "long" else -1
        stop = entry - sgn * risk          # unrounded — sub-cent coins (PEPE) need it
        target = None if trailing else entry + sgn * mgmt.get("target_r", 3.0) * risk
        rr = None if trailing else float(mgmt.get("target_r", 3.0))
    stop_pct = abs(entry - stop) / entry * 100 if (entry and stop is not None) else None
    return {"direction": direction, "entry": entry, "stop": stop, "target": target,
            "trailing": trailing, "stop_pct": stop_pct, "rr": rr}


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
    if valid is None:
        # Fail CLOSED: no validation file (e.g. a fresh cloud host) must never mean
        # "arm everything". Rank for display, arm nothing.
        log.warning("scan_and_arm: no validation file — edge gate unavailable, arming nothing")
        return {"candidates": [], "armed": [], "edge_gated": False,
                "gated_out_setups": ["(no validation file on this host — nothing armed; "
                                     "existing triggers left untouched)"],
                "regime_blocked": False, "actionable": 0}
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

    # ── Every candidate gets the plan it would ACTUALLY be armed with, and a
    # status saying why it is or isn't live. Filters run BEFORE slots are handed
    # out, so a held / too-wide / crowded coin frees its slot for the next one.
    # Any coin with an OPEN trade (paper or taken) is not re-armed: one position per
    # coin. Letting paper-held coins re-arm (Oct 1) produced 29 alerts/day with the
    # same coin firing 3x — duplicate alerts and double-counted stats. When most
    # valid setups are already held, few new arms is the honest answer.
    try:
        open_all = tdb.get_fired_trades(open_only=True)
        held = {t["symbol"] for t in open_all}
    except Exception as exc:                       # noqa: BLE001
        log.warning("scan_and_arm: open-trade lookup failed — %s", exc)
        open_all, held = [], set()
    candidates = rows[:_MAX_CANDIDATES]              # ranked list shown to the user
    try:   # perp funding for the coins we might arm; no perp → never vetoed
        funding = _xch.get_funding_rates([r["ticker"] for r in candidates])
    except Exception as exc:                       # noqa: BLE001 — filter is advisory
        log.warning("scan_and_arm: funding fetch failed — %s", exc)
        funding = {}

    # Longs only while BTC is above its 200-day SMA (see config.BTC_200D_LONG_GATE).
    btc_down = False
    try:
        from config import BTC_200D_LONG_GATE
        if BTC_200D_LONG_GATE:
            from utils import btc_regime
            _r = btc_regime.get_btc_regime()
            btc_down = bool(_r.get("ok")) and not (_r.get("daily") or {}).get("close_gt_200d", True)
    except Exception as exc:                       # noqa: BLE001 — fail open, log
        log.warning("scan_and_arm: BTC 200d gate unavailable — %s", exc)

    wide_stop_excluded, crowded_excluded, eligible = [], [], []
    for r in rows:
        r["_plan"] = plan = _armed_plan(r)
        r["_held"] = r["ticker"] in held
        fr = funding.get(r["ticker"])
        if r["_held"]:
            r["_status"] = "held"
        elif btc_down and plan["direction"] == "long":
            r["_status"] = "btc_downtrend"   # BTC below 200d — no new longs
        elif not plan["stop_pct"] or plan["stop_pct"] < 0.3:
            r["_status"] = "bad_plan"      # zero/too-tight risk → would invalidate instantly
        elif plan["stop"] is not None and plan["direction"] == "long" and plan["stop"] <= 0:
            r["_status"] = "wide_stop"
            wide_stop_excluded.append(f"{r['ticker']} (stop ≤ 0)")
        elif max_stop_pct and plan["stop_pct"] and plan["stop_pct"] > max_stop_pct:
            r["_status"] = "wide_stop"
            wide_stop_excluded.append(f"{r['ticker']} (−{plan['stop_pct']:.0f}%)")
        elif fr is not None and _crowded(plan["direction"], fr):
            r["_status"] = "crowded"
            crowded_excluded.append(f"{r['ticker']} {plan['direction']} (funding {fr*100:+.3f}%)")
        else:
            r["_status"] = "not_selected"
            eligible.append(r)
    held_excluded = sorted({r["ticker"] for r in rows if r["_held"]})
    # Diversify: cap any single setup so the armed set is a spread across types.
    top = _diversify(eligible, top_n, max_per_setup)

    # Verdict per open trade from THIS scan: still in a validated setup (same
    # direction) → hold with confidence; gone → review the position.
    scanned = set(df["ticker"]) if "ticker" in df else set()
    held_status = {}
    for t in open_all:
        sym, d = t["symbol"], t.get("direction") or "long"
        match = next((r for r in rows if r["ticker"] == sym and r.get("direction") == d), None)
        if match:
            held_status[sym] = {"verdict": "valid", "setup": match.get("setup_label"),
                                "score": match.get("_composite")}
        elif sym in scanned:
            held_status[sym] = {"verdict": "gone", "setup": t.get("setup_label")}
        else:
            held_status[sym] = {"verdict": "not_scanned", "setup": t.get("setup_label")}

    common = {"candidates": candidates, "edge_gated": valid is not None,
              "gated_out_setups": gated_out, "actionable": len(rows),
              "wide_stop_excluded": wide_stop_excluded,
              "crowded_excluded": crowded_excluded, "held_excluded": held_excluded,
              "held_status": held_status, "btc_below_200d": btc_down}

    # ── Regime gate: the setups' edge is regime-dependent (strong in trend,
    # weak in chop/bear per the backtest), so only ARM in a risk-on regime.
    # Below the threshold we still show candidates but arm nothing and keep any
    # existing triggers untouched. The macro Deployment Score is the filter.
    if regime_score is not None and regime_score < _MIN_DEPLOY_TO_ARM:
        return {**common, "armed": [], "regime_blocked": True,
                "regime_score": regime_score,
                "management": "Exits are set per setup (breakouts trail; mean-reversion "
                              "& momentum take a fixed target)."}

    # A fresh scan supersedes the previous armed set.
    cancelled = tdb.clear_active()
    now = datetime.datetime.utcnow()
    expires = (now + datetime.timedelta(hours=expiry_hours)).isoformat()

    armed = []
    for r in top:
        trade = r.get("trade") or {}
        plan = r["_plan"]
        direction, cat, ref = plan["direction"], r.get("setup_category"), r.get("price")
        entry, stop, target = plan["entry"], plan["stop"], plan["target"]
        # 20-day mean = Bollinger midline (from the scan's BB bands).
        bb_u, bb_l = r.get("bb_upper"), r.get("bb_lower")
        mean20 = (bb_u + bb_l) / 2 if (bb_u is not None and bb_l is not None) else ref

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
            rr=plan["rr"], composite=r["_composite"], expires_at=expires,
            note=trade.get("note"),
        )
        r["_status"] = "armed"
        r["_trigger_level"] = cval
        armed.append({
            "id": tid, "symbol": r["ticker"], "setup_label": r.get("setup_label"),
            "category": cat, "direction": direction, "composite": r["_composite"],
            "condition": desc, "management": _management_note(r.get("setup_label")),
            "level": cval, "stop_pct": plan["stop_pct"], "trailing": plan["trailing"],
        })

    log.info("scan_and_arm: %d candidates, armed top %d (cancelled %d prior)",
             len(rows), len(armed), cancelled)
    return {**common, "armed": armed, "regime_blocked": False,
            "management": "Exits are set per setup (breakouts trail and let winners "
                          "run; mean-reversion & momentum take a fixed target) — the "
                          "backtested edge for each. See each trigger's plan."}
