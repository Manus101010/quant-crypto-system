"""Journal database — SQLite-backed trade and idea log."""
from __future__ import annotations
import sqlite3
from datetime import datetime
from config import DB_PATH

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS journal (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type   TEXT NOT NULL,          -- trade | idea | note | review
    ticker       TEXT,
    direction    TEXT,                   -- long | short | flat
    entry_price  REAL,
    exit_price   REAL,
    size_pct     REAL,
    pnl_pct      REAL,
    tags         TEXT,                   -- comma-separated
    deploy_score REAL,
    regime       TEXT,
    rationale    TEXT,
    outcome      TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT
);
"""


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.execute(_CREATE_SQL)
    return con


_COLS = [
    "id", "entry_type", "ticker", "direction", "entry_price", "exit_price",
    "size_pct", "pnl_pct", "tags", "deploy_score", "regime",
    "rationale", "outcome", "created_at", "updated_at",
]


def add_entry(
    entry_type: str,
    ticker: str | None = None,
    direction: str | None = None,
    entry_price: float | None = None,
    exit_price: float | None = None,
    size_pct: float | None = None,
    pnl_pct: float | None = None,
    tags: str | None = None,
    deploy_score: float | None = None,
    regime: str | None = None,
    rationale: str | None = None,
    outcome: str | None = None,
) -> int:
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO journal (entry_type, ticker, direction, entry_price,
               exit_price, size_pct, pnl_pct, tags, deploy_score, regime,
               rationale, outcome, created_at) VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (entry_type, ticker, direction, entry_price, exit_price,
             size_pct, pnl_pct, tags, deploy_score, regime, rationale, outcome, now),
        )
        return cur.lastrowid


def get_entries(
    entry_type: str | None = None,
    ticker: str | None = None,
    limit: int = 100,
) -> list[dict]:
    clauses, params = [], []
    if entry_type:
        clauses.append("entry_type=?")
        params.append(entry_type)
    if ticker:
        clauses.append("ticker=?")
        params.append(ticker.upper())
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _conn() as con:
        rows = con.execute(
            f"SELECT * FROM journal {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [dict(zip(_COLS, r)) for r in rows]


def update_entry(entry_id: int, **kwargs) -> None:
    kwargs["updated_at"] = datetime.utcnow().isoformat()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [entry_id]
    with _conn() as con:
        con.execute(f"UPDATE journal SET {sets} WHERE id=?", vals)


def delete_entry(entry_id: int) -> None:
    with _conn() as con:
        con.execute("DELETE FROM journal WHERE id=?", (entry_id,))
