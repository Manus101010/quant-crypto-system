"""
Alert system — price, score threshold, and regime change alerts.
Stored in SQLite; surfaced in the dashboard.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from config import DB_PATH
from utils.logger import get_logger

log = get_logger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type  TEXT    NOT NULL,
    ticker      TEXT,
    condition   TEXT    NOT NULL,
    threshold   REAL,
    triggered   INTEGER DEFAULT 0,
    created_at  TEXT    NOT NULL,
    triggered_at TEXT,
    message     TEXT
);
"""


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.execute(_CREATE_SQL)
    return con


def add_alert(
    alert_type: str,
    condition: str,
    threshold: float | None = None,
    ticker: str | None = None,
) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO alerts (alert_type, ticker, condition, threshold, created_at) VALUES (?,?,?,?,?)",
            (alert_type, ticker, condition, threshold, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_active_alerts() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM alerts WHERE triggered=0 ORDER BY created_at DESC"
        ).fetchall()
    cols = ["id", "alert_type", "ticker", "condition", "threshold",
            "triggered", "created_at", "triggered_at", "message"]
    return [dict(zip(cols, r)) for r in rows]


def trigger_alert(alert_id: int, message: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE alerts SET triggered=1, triggered_at=?, message=? WHERE id=?",
            (datetime.utcnow().isoformat(), message, alert_id),
        )


def check_deployment_alerts(deployment_score: float) -> list[str]:
    """Returns list of triggered messages for current deployment score."""
    triggered = []
    alerts = get_active_alerts()
    for a in alerts:
        if a["alert_type"] == "deployment_score" and a["threshold"] is not None:
            if "below" in a["condition"] and deployment_score < a["threshold"]:
                msg = f"Deployment score {deployment_score:.1f} fell below {a['threshold']}"
                trigger_alert(a["id"], msg)
                triggered.append(msg)
            elif "above" in a["condition"] and deployment_score > a["threshold"]:
                msg = f"Deployment score {deployment_score:.1f} rose above {a['threshold']}"
                trigger_alert(a["id"], msg)
                triggered.append(msg)
    return triggered
