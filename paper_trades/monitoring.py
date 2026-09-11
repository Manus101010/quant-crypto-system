"""
Monitoring & Attribution (roadmap item #5 — see docs/INSTITUTIONAL_ROADMAP.md §monitoring)

Institutional desks continuously attribute P&L by setup / conviction bucket and
alarm when a previously-working signal decays. This module reads the closed
paper-trade history (net of transaction costs) and produces:

  - attribution(): P&L broken down by setup_label and by conviction bucket,
    including cost drag and profit factor, plus an overall summary.
  - detect_decay(): per-setup comparison of recent vs. baseline edge.
  - run_decay_alerts(): pushes newly-decayed setups to the webhook layer.

All functions degrade gracefully (empty / zeroed) on little or no history.
"""
from __future__ import annotations
from paper_trades import db as pdb
from utils.logger import get_logger

log = get_logger(__name__)

_RECENT_N        = 10     # trades considered "recent"
_MIN_BASELINE_N  = 12     # need at least this many to judge decay
_WIN_DROP_PP     = 15.0   # win-rate drop (percentage points) that flags decay


def _pf(rows: list[dict]) -> float:
    """Profit factor = gross wins / gross losses (net-of-cost returns)."""
    wins = sum(r["actual_pnl_pct"] for r in rows if (r.get("actual_pnl_pct") or 0) > 0)
    loss = -sum(r["actual_pnl_pct"] for r in rows if (r.get("actual_pnl_pct") or 0) <= 0)
    if loss == 0:
        return float("inf") if wins > 0 else 0.0
    return round(wins / loss, 2)


def _win_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    w = sum(1 for r in rows if (r.get("actual_pnl_pct") or 0) > 0)
    return round(w / len(rows) * 100, 1)


def _bucket(conv) -> str:
    c = conv or 0
    if c >= 80:
        return "80-100 (high)"
    if c >= 65:
        return "65-79 (good)"
    return "<65 (low)"


def _agg(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "win_rate": 0.0, "total_net_pnl": 0.0, "avg_net_pnl": 0.0,
                "cost_drag": 0.0, "profit_factor": 0.0}
    net  = [r.get("actual_pnl_pct") or 0 for r in rows]
    cost = [r.get("cost_pct") or 0 for r in rows]
    return {
        "n":             len(rows),
        "win_rate":      _win_rate(rows),
        "total_net_pnl": round(sum(net), 2),
        "avg_net_pnl":   round(sum(net) / len(rows), 3),
        "cost_drag":     round(sum(cost), 3),
        "profit_factor": _pf(rows),
    }


def attribution() -> dict:
    """P&L attribution by setup and by conviction bucket, plus overall summary."""
    closed = pdb.get_trades(status="closed")
    by_setup: dict[str, list[dict]] = {}
    by_bucket: dict[str, list[dict]] = {}
    for r in closed:
        by_setup.setdefault(r.get("setup_label", "?"), []).append(r)
        by_bucket.setdefault(_bucket(r.get("conviction")), []).append(r)

    return {
        "overall":   _agg(closed),
        "by_setup":  {k: _agg(v) for k, v in sorted(by_setup.items())},
        "by_bucket": {k: _agg(v) for k, v in sorted(by_bucket.items())},
        "n_closed":  len(closed),
    }


def detect_decay() -> list[dict]:
    """
    Per-setup recent-vs-baseline edge comparison. Flags decay when the recent
    win rate drops > _WIN_DROP_PP vs baseline, or profit factor falls below 1.0
    after the baseline was above it.
    """
    closed = pdb.get_trades(status="closed")
    by_setup: dict[str, list[dict]] = {}
    for r in closed:
        by_setup.setdefault(r.get("setup_label", "?"), []).append(r)

    out = []
    for label, rows in by_setup.items():
        # rows are newest-first (created_at DESC); recent = first N
        if len(rows) < _MIN_BASELINE_N:
            continue
        recent   = rows[:_RECENT_N]
        baseline = rows                      # full history as baseline
        bw, rw   = _win_rate(baseline), _win_rate(recent)
        bpf, rpf = _pf(baseline), _pf(recent)
        decayed  = (bw - rw) > _WIN_DROP_PP or (bpf >= 1.0 and rpf < 1.0)
        severity = ("high" if (bw - rw) > 2 * _WIN_DROP_PP or rpf < 0.7
                    else "warn") if decayed else "ok"
        out.append({
            "setup_label":  label,
            "baseline_win": bw, "recent_win": rw,
            "baseline_pf":  bpf, "recent_pf": rpf,
            "recent_n":     len(recent), "baseline_n": len(baseline),
            "decayed":      decayed, "severity": severity,
        })
    return out


def run_decay_alerts() -> dict:
    """Detect decay and push webhook alerts for newly-decayed setups. Best-effort."""
    detected = detect_decay()
    alerted = []
    for d in detected:
        if not d.get("decayed"):
            continue
        try:
            from utils import webhooks
            if webhooks.send_decay_alert(d["setup_label"], d):
                alerted.append(d["setup_label"])
        except Exception as exc:                       # noqa: BLE001
            log.warning("decay alert failed for %s: %s", d.get("setup_label"), exc)
    return {"detected": detected, "alerted": alerted}
