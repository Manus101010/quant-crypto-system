"""
Signal Stats & Learning Engine
================================
After each closed trade, recompute rolling performance metrics per setup.
The conviction multiplier is fed back into the scanner so high-performing
setups get boosted and decaying setups get suppressed.

Metrics tracked (per setup label):
  - win_rate_20      rolling 20-trade win rate
  - profit_factor_20 gross profit / gross loss over last 20 trades
  - win_rate_90      rolling 90-day win rate (regime baseline)
  - edge_decay       True if 20-trade win rate dropped >15pp vs 90-day baseline
  - conviction_mult  multiplier applied to scanner conviction score (0.6–1.4)
"""
from __future__ import annotations
import sqlite3
import os
import time
from contextlib import contextmanager
from utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "paper_trades.db")

@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _ensure_stats_table():
    with _conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS signal_stats (
            setup_label      TEXT PRIMARY KEY,
            trades_total     INTEGER DEFAULT 0,
            win_rate_20      REAL,
            profit_factor_20 REAL,
            win_rate_90      REAL,
            edge_decay       INTEGER DEFAULT 0,  -- boolean
            conviction_mult  REAL DEFAULT 1.0,
            updated_at       TEXT
        )""")
        con.execute("""
        CREATE TABLE IF NOT EXISTS loop_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at     TEXT,
            universe   TEXT,
            result_json TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )""")

_ensure_stats_table()


def recompute_all():
    """Recompute stats for every setup label that has closed trades."""
    with _conn() as con:
        labels = con.execute("""
            SELECT DISTINCT setup_label FROM paper_trades
            WHERE status IN ('target_hit','stop_hit','manual_close','expired')
        """).fetchall()

    for row in labels:
        _recompute_label(row["setup_label"])


def _recompute_label(label: str):
    with _conn() as con:
        # All closed trades for this label, newest first
        rows = con.execute("""
            SELECT actual_pnl_pct, entry_date FROM paper_trades
            WHERE setup_label=? AND status IN ('target_hit','stop_hit','manual_close','expired')
            ORDER BY created_at DESC
        """, (label,)).fetchall()

    if not rows:
        return

    pnls = [r["actual_pnl_pct"] or 0.0 for r in rows]
    total = len(pnls)

    # Rolling 20
    last20 = pnls[:20]
    wins20 = [p for p in last20 if p > 0]
    loss20 = [p for p in last20 if p <= 0]
    win_rate_20 = len(wins20) / len(last20) * 100 if last20 else None
    gross_profit = sum(wins20)
    gross_loss   = abs(sum(loss20))
    pf20 = (gross_profit / gross_loss) if gross_loss > 0 else (2.0 if gross_profit > 0 else 1.0)

    # Rolling 90-day baseline
    import datetime
    cutoff = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
    last90 = [r["actual_pnl_pct"] or 0.0 for r in rows if (r["entry_date"] or "") >= cutoff]
    win_rate_90 = (sum(1 for p in last90 if p > 0) / len(last90) * 100) if last90 else win_rate_20

    # Edge decay: 20-trade win rate dropped >15pp vs 90-day baseline
    edge_decay = (
        win_rate_20 is not None
        and win_rate_90 is not None
        and (win_rate_90 - win_rate_20) > 15
    )

    # Conviction multiplier: scale by profit factor, capped 0.6–1.4
    # PF=1.0 → mult=1.0, PF=2.0 → mult=1.3, PF=0.5 → mult=0.7
    if pf20 >= 1.0:
        mult = min(1.0 + (pf20 - 1.0) * 0.3, 1.4)
    else:
        mult = max(1.0 - (1.0 - pf20) * 0.6, 0.6)

    # If edge decay, apply an extra penalty
    if edge_decay:
        mult = max(mult * 0.8, 0.6)

    now = datetime.datetime.now().isoformat(timespec="seconds")

    with _conn() as con:
        con.execute("""
            INSERT INTO signal_stats
              (setup_label, trades_total, win_rate_20, profit_factor_20, win_rate_90, edge_decay, conviction_mult, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(setup_label) DO UPDATE SET
              trades_total=excluded.trades_total,
              win_rate_20=excluded.win_rate_20,
              profit_factor_20=excluded.profit_factor_20,
              win_rate_90=excluded.win_rate_90,
              edge_decay=excluded.edge_decay,
              conviction_mult=excluded.conviction_mult,
              updated_at=excluded.updated_at
        """, (label, total, win_rate_20, round(pf20, 2),
              win_rate_90, int(edge_decay), round(mult, 3), now))

    log.info("signal_stats: %s  wr20=%.0f%%  pf=%.2f  mult=%.2f  decay=%s",
             label, win_rate_20 or 0, pf20, mult, edge_decay)


_CLOSED_STATUSES = ("target_hit", "stop_hit", "manual_close", "expired")


def _per_setup_returns() -> dict[str, list[float]]:
    """Net per-trade return series ({setup_label: [pnl_pct, ...]}) for closed trades."""
    out: dict[str, list[float]] = {}
    with _conn() as con:
        rows = con.execute(f"""
            SELECT setup_label, actual_pnl_pct FROM paper_trades
            WHERE status IN ({','.join('?' * len(_CLOSED_STATUSES))})
            ORDER BY created_at DESC
        """, _CLOSED_STATUSES).fetchall()
    for r in rows:
        out.setdefault(r["setup_label"], []).append(r["actual_pnl_pct"] or 0.0)
    return out


def get_validation_report() -> dict[str, dict]:
    """
    Full per-setup statistical-validation report for the dashboard/API.

    Returns {setup_label: {multiplier, dsr, p_value, significant, n}} where
    ``multiplier`` is the DSR-GATED conviction multiplier (neutralised to 1.0
    when the setup's edge is not statistically significant out-of-sample, or
    has too few trades). See paper_trades/validation.py for the DSR method.
    """
    from paper_trades.validation import validated_multipliers
    with _conn() as con:
        rows = con.execute("SELECT setup_label, conviction_mult FROM signal_stats").fetchall()
    raw = {r["setup_label"]: r["conviction_mult"] for r in rows}
    return validated_multipliers(raw, _per_setup_returns())


def get_conviction_multipliers() -> dict[str, float]:
    """
    Return {setup_label: multiplier} for all setups with stats.

    GATED: the raw learned multipliers (from profit factor, tuned in-sample)
    are passed through the Deflated Sharpe Ratio gate in
    paper_trades/validation.py, so a setup with too-few or statistically
    insignificant trades collapses to a neutral 1.0 instead of an over-fit
    1.4 or 0.6. Public return shape is unchanged for backward compatibility
    with loop.py (which calls ``multipliers.get(label, 1.0)``).
    """
    report = get_validation_report()
    return {label: info["multiplier"] for label, info in report.items()}


def get_all_stats() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM signal_stats ORDER BY profit_factor_20 DESC NULLS LAST"
        ).fetchall()
    return [dict(r) for r in rows]


def get_summary() -> dict:
    """Compact summary for the loop result log."""
    stats = get_all_stats()
    decaying = [s["setup_label"] for s in stats if s.get("edge_decay")]
    return {
        "setups_tracked": len(stats),
        "decaying":       decaying,
        "top":            stats[:3],
    }


def get_loop_log(limit: int = 20) -> list[dict]:
    import json as _json
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM loop_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["result"] = _json.loads(d.pop("result_json", "{}"))
        except Exception:
            d["result"] = {}
        out.append(d)
    return out
