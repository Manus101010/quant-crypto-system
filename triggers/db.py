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

-- Per-setup edge-decay time series, appended by the scheduled revalidation job
-- (revalidate.py). One row per setup per run — makes decay visible over time.
CREATE TABLE IF NOT EXISTS setup_edge_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT NOT NULL,        -- ISO UTC of the revalidation run
    setup_label TEXT NOT NULL,
    direction   TEXT,                 -- long | short
    pf          REAL,                 -- profit factor this run (net of cost)
    n           INTEGER,              -- trade count this run
    win_rate    REAL,
    band        TEXT,                 -- established | provisional | below_floor
    action      TEXT                  -- kept | warned | deactivated | review_newly_passing
);
CREATE INDEX IF NOT EXISTS idx_edge_hist_setup ON setup_edge_history(setup_label, run_at);

-- Auto-deactivation overlay: setups the revalidation job disabled on decay. The
-- scanner's edge gate subtracts these from the validated set, so they stop
-- arming NEW triggers. Removed only by an explicit manual reactivate.
CREATE TABLE IF NOT EXISTS setup_deactivations (
    setup_label    TEXT PRIMARY KEY,
    deactivated_at TEXT NOT NULL,
    pf_at          REAL,
    n_at           INTEGER,
    reason         TEXT
);

-- Personal watchlist driving the scheduled Morning Brief. Signal-only; a coin
-- here is just something you want a daily read on, nothing is armed from it.
CREATE TABLE IF NOT EXISTS watchlist (
    symbol     TEXT PRIMARY KEY,        -- e.g. SOL-USD
    added_at   TEXT NOT NULL,
    note       TEXT
);
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


# ── Edge-revalidation history + deactivation overlay ──────────────────────────

def add_edge_history(rows: list[dict]) -> None:
    """Append per-setup revalidation results (one dict per setup)."""
    if not rows:
        return
    with _conn() as con:
        con.executemany(
            """INSERT INTO setup_edge_history
               (run_at, setup_label, direction, pf, n, win_rate, band, action)
               VALUES (:run_at, :setup_label, :direction, :pf, :n, :win_rate, :band, :action)""",
            rows,
        )


def get_edge_history(setup_label: str | None = None, limit: int = 500) -> list[dict]:
    where = "WHERE setup_label=?" if setup_label else ""
    params = (setup_label,) if setup_label else ()
    with _conn() as con:
        rows = con.execute(
            f"SELECT * FROM setup_edge_history {where} ORDER BY run_at DESC, id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def last_edge_action(setup_label: str) -> str | None:
    """Most recent recorded action for a setup (for the 2-consecutive-run rule)."""
    with _conn() as con:
        r = con.execute(
            "SELECT action FROM setup_edge_history WHERE setup_label=? "
            "ORDER BY run_at DESC, id DESC LIMIT 1",
            (setup_label,),
        ).fetchone()
    return r["action"] if r else None


def deactivate_setup(setup_label: str, pf: float | None, n: int | None,
                     reason: str = "edge decayed") -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO setup_deactivations (setup_label, deactivated_at, pf_at, n_at, reason) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(setup_label) DO UPDATE SET deactivated_at=excluded.deactivated_at, "
            "pf_at=excluded.pf_at, n_at=excluded.n_at, reason=excluded.reason",
            (setup_label, datetime.utcnow().isoformat(), pf, n, reason),
        )


def reactivate_setup(setup_label: str) -> None:
    """Manual re-arm: remove a setup from the deactivation overlay."""
    with _conn() as con:
        con.execute("DELETE FROM setup_deactivations WHERE setup_label=?", (setup_label,))


def get_deactivated() -> set[str]:
    with _conn() as con:
        rows = con.execute("SELECT setup_label FROM setup_deactivations").fetchall()
    return {r["setup_label"] for r in rows}


def get_deactivations() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM setup_deactivations ORDER BY deactivated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Personal watchlist (drives the Morning Brief) ─────────────────────────────

def add_watch(symbol: str, note: str | None = None) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO watchlist (symbol, added_at, note) VALUES (?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET note=COALESCE(excluded.note, note)",
            (symbol.upper(), datetime.utcnow().isoformat(), note),
        )


def remove_watch(symbol: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM watchlist WHERE symbol=?", (symbol.upper(),))


def get_watchlist() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM watchlist ORDER BY added_at").fetchall()
    return [dict(r) for r in rows]


def get_triggers_since(iso_cutoff: str, statuses=("fired", "invalidated", "expired")) -> list[dict]:
    """Triggers that changed to one of `statuses` since `iso_cutoff` (for the brief)."""
    qmarks = ",".join("?" * len(statuses))
    with _conn() as con:
        rows = con.execute(
            f"SELECT * FROM triggers WHERE status IN ({qmarks}) "
            f"AND COALESCE(fired_at, created_at) >= ? ORDER BY COALESCE(fired_at, created_at) DESC",
            (*statuses, iso_cutoff),
        ).fetchall()
    return [dict(r) for r in rows]
