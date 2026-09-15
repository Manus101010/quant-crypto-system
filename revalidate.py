#!/usr/bin/env python3
"""
Scheduled edge-revalidation job — watches the armed setups for decay.

A thin edge that validated once (e.g. Breakdown Short at n=30, just over the 25
floor) is trusted forever unless something re-checks it. This job re-runs the
edge-gate backtest on the current MEXC universe, records each setup's PF/n over
time, and AUTO-DEACTIVATES a setup whose edge has decayed — so it stops arming
new triggers — while NEVER auto-arming a setup that newly passes (those are
surfaced for manual review only).

HARD RULE: this is a heavy universe backtest and MUST run off the monitor hot
path. It is a standalone script (cron / systemd timer / manual button), never
called inside monitor.poll_once.

Decisions (locked):
  • Cadence: weekly (scheduler's job — see run_revalidate.sh / cron example).
  • Auto-deactivate when PF < 1.0 (or n < 25). Provisional setups (25 ≤ n < 50)
    deactivate on the FIRST failing run; established (n ≥ 50) only after TWO
    consecutive failing runs.
  • Asymmetric: auto-DEACTIVATE on decay, but a newly-passing setup is only
    flagged for manual review, never auto-armed.

Signal-only, ccxt read-only public OHLC, free data. Uses the corrected capped
short P&L (in _simulate) so decay checks stay honest.

Usage:
    ./venv/bin/python revalidate.py                 # run once (what the timer calls)
    ./venv/bin/python revalidate.py --dry-run       # compute + report, change nothing
"""
from __future__ import annotations
import argparse
import datetime

from backtesting.crypto_optimize import validate_per_setup
from backtesting.crypto_validation import validated_labels, _MIN_EDGE_PF, _MIN_EDGE_N
from triggers import db as tdb
from utils import telegram
from utils.logger import get_logger

log = get_logger("revalidate")

# Match the universe/window the baseline was validated on.
_SOURCE, _DAYS, _MAX_COINS, _COST = "mexc", 600, 400, 0.36
_PROVISIONAL_MAX = 50          # 25 ≤ n < 50 = provisional; n ≥ 50 = established


def _band(n: int) -> str:
    if n < _MIN_EDGE_N:
        return "below_floor"
    if n < _PROVISIONAL_MAX:
        return "provisional"
    return "established"


def _pf_val(s: dict) -> float:
    pf = s.get("profit_factor")
    return 99.0 if pf is None else pf     # None = inf PF (no losers) → strong


def run_revalidation(dry_run: bool = False) -> dict:
    run_at = datetime.datetime.utcnow().isoformat()
    tdb.init_db()

    # Fresh stats WITHOUT overwriting the baseline validation JSON (save=False).
    res = validate_per_setup(days=_DAYS, source=_SOURCE, max_coins=_MAX_COINS,
                             cost_pct=_COST, save=False)
    stats = res["stats"]

    baseline = validated_labels() or set()      # baseline candidate pool
    already_off = tdb.get_deactivated()
    armable = baseline - already_off             # what currently arms

    history_rows, deactivated, review = [], [], []

    # ── Armable setups: check for decay ───────────────────────────────────────
    for setup in sorted(armable):
        s = stats.get(setup)
        n = int(s["n"]) if s else 0
        pf = _pf_val(s) if s else 0.0
        band = _band(n)
        failing = (n < _MIN_EDGE_N) or (pf < _MIN_EDGE_PF)

        if not failing:
            action = "kept"
        elif band == "established":
            # Two consecutive failing runs before killing a proven setup.
            prev_warned = tdb.last_edge_action(setup) == "warned"
            action = "deactivated" if prev_warned else "warned"
        else:
            action = "deactivated"      # provisional / below-floor → first run

        if action == "deactivated" and not dry_run:
            tdb.deactivate_setup(setup, pf, n,
                                 reason=f"PF {pf:.2f} / n {n} on {run_at[:10]}")
        if action == "deactivated":
            deactivated.append({"setup": setup, "pf": pf, "n": n})
        history_rows.append({"run_at": run_at, "setup_label": setup,
                             "direction": "short" if "Short" in setup else "long",
                             "pf": round(pf, 3), "n": n,
                             "win_rate": s.get("win_rate") if s else None,
                             "band": band, "action": action})

    # ── Newly-passing setups (not armable now): review only, never auto-arm ────
    for setup, s in stats.items():
        if setup in armable:
            continue
        n = int(s["n"])
        pf = _pf_val(s)
        if pf > _MIN_EDGE_PF and n >= _MIN_EDGE_N:
            review.append({"setup": setup, "pf": pf, "n": n})
            history_rows.append({"run_at": run_at, "setup_label": setup,
                                 "direction": "short" if "Short" in setup else "long",
                                 "pf": round(pf, 3), "n": n,
                                 "win_rate": s.get("win_rate"), "band": _band(n),
                                 "action": "review_newly_passing"})

    if not dry_run:
        tdb.add_edge_history(history_rows)
        _notify(deactivated, review)

    log.info("revalidation: %d armable checked, %d deactivated, %d newly-passing (review)%s",
             len(armable), len(deactivated), len(review), " [dry-run]" if dry_run else "")
    return {"run_at": run_at, "checked": sorted(armable),
            "deactivated": deactivated, "review": review, "history": history_rows}


def _notify(deactivated: list[dict], review: list[dict]) -> None:
    if not telegram.is_configured():
        return
    if deactivated:
        lines = ["⛔ <b>Setup(s) auto-deactivated — edge decayed</b>",
                 "These stop arming NEW triggers (existing ones untouched):"]
        for d in deactivated:
            lines.append(f"• <b>{d['setup']}</b> — PF {d['pf']:.2f}, n {d['n']}")
        telegram.send_message("\n".join(lines))
    if review:
        lines = ["🔎 <b>Setup(s) newly passing — manual review</b>",
                 "Not armed automatically. Reactivate in the Validation page if you want them:"]
        for r in review:
            lines.append(f"• <b>{r['setup']}</b> — PF {r['pf']:.2f}, n {r['n']}")
        telegram.send_message("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description="Edge-revalidation job (off the hot path)")
    ap.add_argument("--dry-run", action="store_true", help="compute + report, change nothing")
    args = ap.parse_args()
    out = run_revalidation(dry_run=args.dry_run)
    print(f"revalidation {out['run_at']}"
          f" — checked {len(out['checked'])}, deactivated {len(out['deactivated'])},"
          f" review {len(out['review'])}")
    for d in out["deactivated"]:
        print(f"  DEACTIVATED {d['setup']} (PF {d['pf']:.2f}, n {d['n']})")
    for r in out["review"]:
        print(f"  REVIEW (newly passing) {r['setup']} (PF {r['pf']:.2f}, n {r['n']})")


if __name__ == "__main__":
    main()
