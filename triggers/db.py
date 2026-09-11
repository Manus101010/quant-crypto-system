"""
Triggers table — the bridge between the on-demand Scanner and the always-on
Monitor. The scanner writes ranked setups here as *armed conditions*; the
monitor evaluates each active trigger every poll and fires a Telegram alert when
the condition is met. Signal-only: a trigger is a notification, never an order.

Lives in the existing SQLite db (config.DB_PATH — data/trading.db), alongside
the journal.
"""
from __future__ import annotations
import sqlite3
from datetime import datetime
from config import DB_PATH

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS triggers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT    NOT NULL,        -- e.g. BTC-USD
    setup_label    TEXT,                    -- scanner setup name
    setup_category TEXT,                    -- mean_reversion | momentum
    direction      TEXT,                    -- long | short
    -- The armed condition the monitor watches:
    condition_type TEXT    NOT NULL,        -- mr_reversal_long | breakout_long | breakdown_short | (legacy price_*/rsi_*)
    condition_value REAL   NOT NULL,        -- primary numeric (breakout level, or RSI-2 reclaim level) — for display
    condition_json TEXT,                    -- full multi-factor condition {kind, ...levels}
    timeframe      TEXT    DEFAULT '1d',    -- candle timeframe for indicator conditions
    -- Suggested trade (informational; user executes manually):
    ref_price      REAL,                    -- price at scan time
    entry          REAL,
    target         REAL,
    stop           REAL,
    rr             REAL,
    composite      REAL,                    -- scanner composite / conviction score
    -- Lifecycle:
    status         TEXT    DEFAULT 'active',-- active | fired | expired | cancelled
    created_at     TEXT    NOT NULL,
    expires_at     TEXT,
    fired_at       TEXT,
    fired_price    REAL,
    note           TEXT
);
CREATE INDEX IF NOT EXISTS idx_triggers_status ON triggers(status);
"""

_COLS = [
    "id", "symbol", "setup_label", "setup_category", "direction",
    "condition_type", "condition_value", "condition_json", "timeframe", "ref_price",
    "entry", "target", "stop", "rr", "composite", "status",
    "created_at", "expires_at", "fired_at", "fired_price", "note",
]


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row          # column-name access → order-independent reads
    con.executescript(_CREATE_SQL)
    # ALTER-safe migration for DBs created before condition_json existed.
    try:
        con.execute("ALTER TABLE triggers ADD COLUMN condition_json TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    return con


def init_db() -> None:
    with _conn():
        pass


def add_trigger(
    symbol: str,
    condition_type: str,
    condition_value: float,
    *,
    condition_json: str | None = None,
    setup_label: str | None = None,
    setup_category: str | None = None,
    direction: str | None = "long",
    timeframe: str = "1d",
    ref_price: float | None = None,
    entry: float | None = None,
    target: float | None = None,
    stop: float | None = None,
    rr: float | None = None,
    composite: float | None = None,
    expires_at: str | None = None,
    note: str | None = None,
) -> int:
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO triggers
               (symbol, setup_label, setup_category, direction, condition_type,
                condition_value, condition_json, timeframe, ref_price, entry, target,
                stop, rr, composite, status, created_at, expires_at, note)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active',?,?,?)""",
            (symbol, setup_label, setup_category, direction, condition_type,
             condition_value, condition_json, timeframe, ref_price, entry, target,
             stop, rr, composite, now, expires_at, note),
        )
        return cur.lastrowid


def get_triggers(status: str | None = "active", limit: int = 500) -> list[dict]:
    where = "WHERE status=?" if status else ""
    params = (status,) if status else ()
    with _conn() as con:
        rows = con.execute(
            f"SELECT * FROM triggers {where} ORDER BY composite DESC, created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def active_symbols() -> list[str]:
    """Distinct symbols with at least one active trigger (for batched fetches)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT symbol FROM triggers WHERE status='active'"
        ).fetchall()
    return [r[0] for r in rows]


def mark_fired(trigger_id: int, fired_price: float, note: str | None = None) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE triggers SET status='fired', fired_at=?, fired_price=?, "
            "note=COALESCE(?, note) WHERE id=?",
            (datetime.utcnow().isoformat(), fired_price, note, trigger_id),
        )


def set_status(trigger_id: int, status: str) -> None:
    with _conn() as con:
        con.execute("UPDATE triggers SET status=? WHERE id=?", (status, trigger_id))


def expire_stale(before_iso: str) -> int:
    """Mark active triggers with expires_at < before_iso as expired. Returns count."""
    with _conn() as con:
        cur = con.execute(
            "UPDATE triggers SET status='expired' "
            "WHERE status='active' AND expires_at IS NOT NULL AND expires_at < ?",
            (before_iso,),
        )
        return cur.rowcount


def clear_active() -> int:
    """Cancel all active triggers (used before writing a fresh scan). Returns count."""
    with _conn() as con:
        cur = con.execute("UPDATE triggers SET status='cancelled' WHERE status='active'")
        return cur.rowcount


def delete_trigger(trigger_id: int) -> None:
    with _conn() as con:
        con.execute("DELETE FROM triggers WHERE id=?", (trigger_id,))
