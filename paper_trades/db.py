"""
Paper Trades — SQLite persistence layer.

Tracks every trade suggested by the scanner so the system can measure
how accurate its setups, conviction scores, and R:R predictions are.
"""
from __future__ import annotations
import sqlite3
import os
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


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker           TEXT    NOT NULL,
            setup_label      TEXT    NOT NULL,
            setup_category   TEXT    NOT NULL,
            action           TEXT    NOT NULL,   -- BUY | SELL/EXIT | WAIT
            entry_price      REAL    NOT NULL,
            target_price     REAL    NOT NULL,
            stop_price       REAL    NOT NULL,
            predicted_rr     REAL,               -- numeric e.g. 2.3
            conviction       REAL    NOT NULL,
            macro_score      REAL,
            trade_note       TEXT,
            entry_date       TEXT    NOT NULL,
            status           TEXT    DEFAULT 'open',
            -- open | target_hit | stop_hit | manual_close | expired
            exit_price       REAL,
            exit_date        TEXT,
            actual_pnl_pct   REAL,       -- NET of transaction costs (learning loop trains on this)
            gross_pnl_pct    REAL,       -- frictionless gross P&L, for transparency
            cost_pct         REAL,       -- round-trip transaction cost applied
            actual_rr        REAL,
            bars_held        INTEGER,
            created_at       TEXT    DEFAULT (datetime('now'))
        )""")
        # ALTER-safe migration for pre-existing DBs created before cost columns.
        for col in ("gross_pnl_pct", "cost_pct"):
            try:
                con.execute(f"ALTER TABLE paper_trades ADD COLUMN {col} REAL")
            except sqlite3.OperationalError:
                pass  # column already exists
    log.info("paper_trades: db initialised at %s", DB_PATH)


def open_trade(
    ticker: str,
    setup_label: str,
    setup_category: str,
    action: str,
    entry_price: float,
    target_price: float,
    stop_price: float,
    predicted_rr: float | None,
    conviction: float,
    macro_score: float | None,
    trade_note: str,
    entry_date: str,
) -> int:
    with _conn() as con:
        cur = con.execute("""
            INSERT INTO paper_trades
              (ticker, setup_label, setup_category, action, entry_price, target_price,
               stop_price, predicted_rr, conviction, macro_score, trade_note, entry_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (ticker, setup_label, setup_category, action, entry_price, target_price,
              stop_price, predicted_rr, conviction, macro_score, trade_note, entry_date))
        return cur.lastrowid


def close_trade(
    trade_id: int,
    exit_price: float,
    exit_date: str,
    status: str,          # target_hit | stop_hit | manual_close | expired
    bars_held: int | None = None,
) -> bool:
    with _conn() as con:
        row = con.execute(
            "SELECT ticker, action, entry_price, target_price, stop_price, predicted_rr FROM paper_trades WHERE id=?",
            (trade_id,)
        ).fetchone()
        if not row:
            return False

        ticker = row["ticker"]
        entry  = row["entry_price"]
        target = row["target_price"]
        stop   = row["stop_price"]
        action = row["action"]

        # For BUY trades: pnl = (exit - entry) / entry
        # For SELL/EXIT (short-side MR): pnl = (entry - exit) / entry
        if action == "SELL/EXIT":
            pnl_pct  = (entry - exit_price) / entry * 100
            risk      = abs(entry - stop)
            reward    = exit_price - entry  # negative if good (price fell)
        else:
            pnl_pct  = (exit_price - entry) / entry * 100
            risk      = abs(entry - stop)
            reward    = exit_price - entry

        # Deduct realistic round-trip transaction costs so the learning loop
        # trains on NET returns (see paper_trades/costs.py + roadmap §4).
        from paper_trades.costs import round_trip_cost_pct  # lazy import
        gross_pnl_pct = pnl_pct
        cost_pct = round_trip_cost_pct(ticker, entry)
        net_pnl_pct = gross_pnl_pct - cost_pct

        # actual_rr is computed on the gross move (price-based R), but flip its
        # sign on the NET result so a cost-eroded breakeven reads as a loss.
        actual_rr = (abs(reward) / risk) if risk > 0 else None
        if actual_rr and net_pnl_pct < 0:
            actual_rr = -actual_rr   # negative R means a loss

        con.execute("""
            UPDATE paper_trades
            SET status=?, exit_price=?, exit_date=?, actual_pnl_pct=?,
                gross_pnl_pct=?, cost_pct=?, actual_rr=?, bars_held=?
            WHERE id=?
        """, (status, exit_price, exit_date, round(net_pnl_pct, 3),
              round(gross_pnl_pct, 3), round(cost_pct, 4),
              round(actual_rr, 2) if actual_rr is not None else None,
              bars_held, trade_id))
        return True


def get_trades(status: str | None = None) -> list[dict]:
    with _conn() as con:
        if status:
            rows = con.execute(
                "SELECT * FROM paper_trades WHERE status=? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM paper_trades ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_trade(trade_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM paper_trades WHERE id=?", (trade_id,)).fetchone()
        return dict(row) if row else None


def delete_trade(trade_id: int) -> bool:
    with _conn() as con:
        con.execute("DELETE FROM paper_trades WHERE id=?", (trade_id,))
        return True


def log_loop_run(result: dict):
    import json
    from paper_trades import stats as _s
    _s._ensure_stats_table()
    with _conn() as con:
        con.execute(
            "INSERT INTO loop_log (run_at, universe, result_json) VALUES (?,?,?)",
            (result.get("run_at"), result.get("universe"), json.dumps(result))
        )


def get_performance_stats() -> dict:
    """
    Aggregate performance metrics for the learning dashboard.
    Returns win rates, avg pnl, R:R accuracy, and conviction calibration.
    """
    with _conn() as con:
        closed = con.execute("""
            SELECT * FROM paper_trades
            WHERE status IN ('target_hit','stop_hit','manual_close','expired')
        """).fetchall()

        if not closed:
            return {"total_closed": 0}

        closed = [dict(r) for r in closed]
        total  = len(closed)
        wins   = [r for r in closed if (r["actual_pnl_pct"] or 0) > 0]
        losses = [r for r in closed if (r["actual_pnl_pct"] or 0) <= 0]

        win_rate   = len(wins) / total * 100
        avg_pnl    = sum(r["actual_pnl_pct"] or 0 for r in closed) / total
        avg_win    = sum(r["actual_pnl_pct"] or 0 for r in wins)   / len(wins)   if wins   else 0
        avg_loss   = sum(r["actual_pnl_pct"] or 0 for r in losses) / len(losses) if losses else 0

        # Per-setup breakdown
        by_setup: dict[str, dict] = {}
        for r in closed:
            key = r["setup_label"]
            if key not in by_setup:
                by_setup[key] = {"wins": 0, "losses": 0, "total_pnl": 0.0, "predicted_rr": [], "actual_rr": []}
            s = by_setup[key]
            pnl = r["actual_pnl_pct"] or 0
            s["total_pnl"] += pnl
            if pnl > 0:
                s["wins"] += 1
            else:
                s["losses"] += 1
            if r["predicted_rr"]:
                s["predicted_rr"].append(r["predicted_rr"])
            if r["actual_rr"]:
                s["actual_rr"].append(r["actual_rr"])

        setup_stats = []
        for label, s in by_setup.items():
            n = s["wins"] + s["losses"]
            setup_stats.append({
                "setup_label":    label,
                "trades":         n,
                "win_rate":       round(s["wins"] / n * 100, 1),
                "avg_pnl":        round(s["total_pnl"] / n, 2),
                "avg_pred_rr":    round(sum(s["predicted_rr"]) / len(s["predicted_rr"]), 2) if s["predicted_rr"] else None,
                "avg_actual_rr":  round(sum(s["actual_rr"])    / len(s["actual_rr"]),    2) if s["actual_rr"]    else None,
            })
        setup_stats.sort(key=lambda x: -x["win_rate"])

        # Conviction calibration: group by conviction buckets
        buckets = {"50-64": [], "65-79": [], "80-100": []}
        for r in closed:
            c = r["conviction"] or 0
            pnl = r["actual_pnl_pct"] or 0
            if c >= 80:
                buckets["80-100"].append(pnl)
            elif c >= 65:
                buckets["65-79"].append(pnl)
            elif c >= 50:
                buckets["50-64"].append(pnl)

        conviction_calibration = []
        labels = {"50-64": "Moderate (50-64)", "65-79": "Good (65-79)", "80-100": "High (80-100)"}
        for key, pnls in buckets.items():
            if pnls:
                conviction_calibration.append({
                    "bucket":   labels[key],
                    "trades":   len(pnls),
                    "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 1),
                    "avg_pnl":  round(sum(pnls) / len(pnls), 2),
                })

        return {
            "total_closed":          total,
            "win_rate":              round(win_rate, 1),
            "avg_pnl":               round(avg_pnl, 2),
            "avg_win":               round(avg_win, 2),
            "avg_loss":              round(avg_loss, 2),
            "profit_factor":         round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else None,
            "by_setup":              setup_stats,
            "conviction_calibration": conviction_calibration,
        }
