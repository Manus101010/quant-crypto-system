"""
Supabase-backed triggers/watchlist store — the shared brain for cloud + laptop.

Mirrors the public surface of triggers/db.py (SQLite) so the rest of the app is
unchanged. Active when SUPABASE_URL + SUPABASE_KEY are set (see config); db.py
rebinds its functions to these. Timestamps are ISO strings (text columns) to
match the SQLite behaviour exactly, so all the existing string comparisons hold.

Signal-only: this stores notifications/state, never orders.
"""
from __future__ import annotations
from datetime import datetime
from config import SUPABASE_URL, SUPABASE_KEY
from utils.logger import get_logger

log = get_logger(__name__)
_client = None


def _c():
    global _client
    if _client is None:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def init_db() -> None:
    """Tables are created once via the Supabase SQL editor; nothing to do here."""
    return None


# ── Triggers ──────────────────────────────────────────────────────────────────
def add_trigger(symbol, condition_type, condition_value, *, condition_json=None,
                setup_label=None, setup_category=None, direction="long",
                timeframe="1d", ref_price=None, entry=None, target=None, stop=None,
                rr=None, composite=None, expires_at=None, note=None) -> int:
    row = {
        "symbol": symbol, "setup_label": setup_label, "setup_category": setup_category,
        "direction": direction, "condition_type": condition_type,
        "condition_value": condition_value, "condition_json": condition_json,
        "timeframe": timeframe, "ref_price": ref_price, "entry": entry,
        "target": target, "stop": stop, "rr": rr, "composite": composite,
        "status": "active", "created_at": datetime.utcnow().isoformat(),
        "expires_at": expires_at, "note": note,
    }
    res = _c().table("triggers").insert(row).execute()
    return res.data[0]["id"] if res.data else -1


def get_triggers(status="active", limit=500) -> list[dict]:
    q = _c().table("triggers").select("*")
    if status:
        q = q.eq("status", status)
    res = q.order("composite", desc=True).order("created_at", desc=True).limit(limit).execute()
    return res.data or []


def active_symbols() -> list[str]:
    res = _c().table("triggers").select("symbol").eq("status", "active").execute()
    return sorted({r["symbol"] for r in (res.data or [])})


def mark_fired(trigger_id, fired_price, note=None) -> None:
    patch = {"status": "fired", "fired_at": datetime.utcnow().isoformat(),
             "fired_price": fired_price}
    if note is not None:
        patch["note"] = note
    _c().table("triggers").update(patch).eq("id", trigger_id).execute()


def set_status(trigger_id, status) -> None:
    _c().table("triggers").update({"status": status}).eq("id", trigger_id).execute()


def expire_stale(before_iso) -> int:
    res = (_c().table("triggers").update({"status": "expired"})
           .eq("status", "active").lt("expires_at", before_iso).execute())
    return len(res.data or [])


def clear_active() -> int:
    res = (_c().table("triggers").update({"status": "cancelled"})
           .eq("status", "active").execute())
    return len(res.data or [])


def delete_trigger(trigger_id) -> None:
    _c().table("triggers").delete().eq("id", trigger_id).execute()


def get_triggers_since(iso_cutoff, statuses=("fired", "invalidated", "expired")) -> list[dict]:
    res = (_c().table("triggers").select("*")
           .in_("status", list(statuses)).execute())
    rows = [r for r in (res.data or [])
            if (r.get("fired_at") or r.get("created_at") or "") >= iso_cutoff]
    rows.sort(key=lambda r: (r.get("fired_at") or r.get("created_at") or ""), reverse=True)
    return rows


# ── Watchlist ─────────────────────────────────────────────────────────────────
def add_watch(symbol, note=None) -> None:
    _c().table("watchlist").upsert(
        {"symbol": symbol.upper(), "added_at": datetime.utcnow().isoformat(), "note": note}
    ).execute()


def remove_watch(symbol) -> None:
    _c().table("watchlist").delete().eq("symbol", symbol.upper()).execute()


def get_watchlist() -> list[dict]:
    res = _c().table("watchlist").select("*").order("added_at").execute()
    return res.data or []


# ── Edge history + deactivation overlay ───────────────────────────────────────
def add_edge_history(rows: list[dict]) -> None:
    if rows:
        _c().table("setup_edge_history").insert(rows).execute()


def get_edge_history(setup_label=None, limit=500) -> list[dict]:
    q = _c().table("setup_edge_history").select("*")
    if setup_label:
        q = q.eq("setup_label", setup_label)
    res = q.order("run_at", desc=True).limit(limit).execute()
    return res.data or []


def last_edge_action(setup_label) -> str | None:
    res = (_c().table("setup_edge_history").select("action")
           .eq("setup_label", setup_label).order("run_at", desc=True).limit(1).execute())
    return res.data[0]["action"] if res.data else None


def deactivate_setup(setup_label, pf, n, reason="edge decayed") -> None:
    _c().table("setup_deactivations").upsert({
        "setup_label": setup_label, "deactivated_at": datetime.utcnow().isoformat(),
        "pf_at": pf, "n_at": n, "reason": reason,
    }).execute()


def reactivate_setup(setup_label) -> None:
    _c().table("setup_deactivations").delete().eq("setup_label", setup_label).execute()


def get_deactivated() -> set:
    res = _c().table("setup_deactivations").select("setup_label").execute()
    return {r["setup_label"] for r in (res.data or [])}


def get_deactivations() -> list[dict]:
    res = _c().table("setup_deactivations").select("*").order("deactivated_at", desc=True).execute()
    return res.data or []
