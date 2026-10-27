"""Desk verdict storage, settled decision memory and the desk vs all signals scorecard.

Verdicts live in app_state (no schema change): key desk:<trigger_id>.
"""
from __future__ import annotations
import json
from utils.logger import get_logger

log = get_logger(__name__)
APPROVE = ("TAKE", "TAKE_REDUCED")


def save(trigger_id: int, result: dict) -> None:
    from triggers import db
    keep = {k: result.get(k) for k in ("action", "conviction", "trader_action", "risk_action",
                                       "setup_label", "symbol", "direction", "model",
                                       "prompt_version", "bad_citations", "built_utc", "report")}
    db.set_state(f"desk:{trigger_id}", json.dumps(keep, separators=(",", ":")))


def load(trigger_id: int) -> dict | None:
    from triggers import db
    raw = db.get_state(f"desk:{trigger_id}")
    try:
        return json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _settled(trades: list[dict] | None = None) -> list[dict]:
    """Closed fired trades that have a desk verdict, with their paper R."""
    from triggers import db
    trades = trades if trades is not None else db.get_fired_trades()
    out = []
    for t in trades:
        if t.get("r_multiple") is None or not t.get("outcome"):
            continue
        v = load(t["id"])
        if v:
            out.append({**v, "r": float(t["r_multiple"]), "outcome": t.get("outcome"),
                        "fired_at": t.get("fired_at"), "trigger_id": t["id"]})
    return out


def memory_for(setup_label: str | None, limit: int = 5) -> list[dict]:
    """The desk's last settled calls on this setup: what it said and what happened."""
    rows = [r for r in _settled() if r.get("setup_label") == setup_label]
    rows.sort(key=lambda r: r.get("fired_at") or "", reverse=True)
    return [{"symbol": r.get("symbol"), "desk_action": r.get("action"),
             "conviction": r.get("conviction"), "result_r": round(r["r"], 2),
             "desk_was_right": (r["r"] > 0) == (r.get("action") in APPROVE)}
            for r in rows[:limit]]


def _pf(rs: list[float]) -> float | None:
    win, loss = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return round(win / loss, 2) if loss else None


def _block(rs: list[float]) -> dict:
    return {"n": len(rs), "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
            "total_r": round(sum(rs), 2), "pf": _pf(rs),
            "win_rate": round(sum(r > 0 for r in rs) / len(rs), 3) if rs else None}


def scorecard(trades: list[dict] | None = None) -> dict:
    """Every desk reviewed signal vs the ones it approved vs the ones it vetoed.
    Pass mark (from the plan): approved beats all, PF > 1 in both halves, vetoed loses."""
    rows = sorted(_settled(trades), key=lambda r: r.get("fired_at") or "")
    allr = [r["r"] for r in rows]
    appr = [r["r"] for r in rows if r.get("action") in APPROVE]
    veto = [r["r"] for r in rows if r.get("action") not in APPROVE]
    half = len(rows) // 2
    h1 = [r["r"] for r in rows[:half] if r.get("action") in APPROVE]
    h2 = [r["r"] for r in rows[half:] if r.get("action") in APPROVE]
    a, b = _block(allr), _block(appr)
    passed = (len(rows) >= 60 and a["avg_r"] is not None and b["avg_r"] is not None
              and b["avg_r"] > a["avg_r"] and (_pf(h1) or 0) > 1 and (_pf(h2) or 0) > 1
              and (_block(veto)["avg_r"] or 0) < 0)
    return {"all": a, "approved": b, "vetoed": _block(veto),
            "approved_half1_pf": _pf(h1), "approved_half2_pf": _pf(h2),
            "passes_gate": passed, "needs_n": max(0, 60 - len(rows))}


def scorecard_text(sc: dict | None = None) -> str:
    sc = sc or scorecard()

    def f(b):
        return ("n 0" if not b["n"] else
                f"n {b['n']} · avg {b['avg_r']:+.2f}R · PF {b['pf'] if b['pf'] is not None else 'n/a'}")
    return ("🧠 <b>Desk scorecard</b> (closed signals the desk reviewed)\n"
            f"All: {f(sc['all'])}\nApproved: {f(sc['approved'])}\nVetoed: {f(sc['vetoed'])}\n"
            + ("✅ Passes the edge gate." if sc["passes_gate"] else
               f"Not proven yet ({sc['needs_n']} more closed signals needed for the 60 minimum)."
               if sc["needs_n"] else "❌ Not passing: desk approved trades don't beat taking all."))
