"""
SQLite-backed cache for analyst results.
Keyed by (ticker, quarter_end).
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from config import CACHE_PATH
from utils.logger import get_logger

log = get_logger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS analyst_cache (
    ticker       TEXT NOT NULL,
    quarter_end  TEXT NOT NULL,
    data_json    TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (ticker, quarter_end)
);
CREATE TABLE IF NOT EXISTS fundamentals_cache (
    ticker       TEXT PRIMARY KEY,
    data_json    TEXT NOT NULL,
    fetched_at   TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(CACHE_PATH))
    con.executescript(_CREATE_SQL)
    return con


def get_analyst(ticker: str, quarter_end: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT data_json FROM analyst_cache WHERE ticker=? AND quarter_end=?",
            (ticker.upper(), quarter_end),
        ).fetchone()
    return json.loads(row[0]) if row else None


def set_analyst(ticker: str, quarter_end: str, data: dict) -> None:
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO analyst_cache VALUES (?,?,?,?)",
            (ticker.upper(), quarter_end, json.dumps(data),
             datetime.utcnow().isoformat()),
        )


def get_fundamentals(ticker: str, max_age_hours: int = 6) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT data_json, fetched_at FROM fundamentals_cache WHERE ticker=?",
            (ticker.upper(),),
        ).fetchone()
    if not row:
        return None
    fetched = datetime.fromisoformat(row[1])
    age_h = (datetime.utcnow() - fetched).total_seconds() / 3600
    if age_h > max_age_hours:
        return None
    return json.loads(row[0])


def set_fundamentals(ticker: str, data: dict) -> None:
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO fundamentals_cache VALUES (?,?,?)",
            (ticker.upper(), json.dumps(data), datetime.utcnow().isoformat()),
        )


def list_cached_tickers() -> list[str]:
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT ticker FROM analyst_cache ORDER BY ticker"
        ).fetchall()
    return [r[0] for r in rows]
