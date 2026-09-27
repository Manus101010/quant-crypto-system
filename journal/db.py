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


# ── Supabase backend ──────────────────────────────────────────────────────────
# Same switch as triggers/db.py: with SUPABASE_URL+KEY set, the journal lives in
# Supabase so entries logged from the phone (Streamlit Cloud, whose local disk is
# wiped on every restart) and the laptop are shared and permanent.
from config import SUPABASE_URL as _SU, SUPABASE_KEY as _SK

if _SU and _SK:
    def _tbl():
        from triggers.supastore import _c
        return _c().table("journal")

    def add_entry(entry_type, ticker=None, direction=None, entry_price=None,
                  exit_price=None, size_pct=None, pnl_pct=None, tags=None,
                  deploy_score=None, regime=None, rationale=None, outcome=None) -> int:
        row = {"entry_type": entry_type, "ticker": ticker, "direction": direction,
               "entry_price": entry_price, "exit_price": exit_price,
               "size_pct": size_pct, "pnl_pct": pnl_pct, "tags": tags,
               "deploy_score": deploy_score, "regime": regime,
               "rationale": rationale, "outcome": outcome,
               "created_at": datetime.utcnow().isoformat()}
        res = _tbl().insert(row).execute()
        return res.data[0]["id"] if res.data else -1

    def get_entries(entry_type=None, ticker=None, limit=100) -> list[dict]:
        q = _tbl().select("*")
        if entry_type:
            q = q.eq("entry_type", entry_type)
        if ticker:
            q = q.eq("ticker", ticker.upper())
        return q.order("created_at", desc=True).limit(limit).execute().data or []

    def update_entry(entry_id, **kwargs) -> None:
        kwargs["updated_at"] = datetime.utcnow().isoformat()
        _tbl().update(kwargs).eq("id", entry_id).execute()

    def delete_entry(entry_id) -> None:
        _tbl().delete().eq("id", entry_id).execute()
