"""
Guard ledger: daily P&L state, issued trade registry, and the revenge detector.

Storage: the existing app_state key/value table via triggers.db.get_state/set_state
(SQLite locally, Supabase when SUPABASE_URL/KEY are set; db.py rebinds both). Values
are JSON strings. No new tables. Keys:

  guard:issued          list of issued plans (most recent last, pruned to 200)
  guard:day:YYYY-MM-DD  Sydney day record {realised, realised_issued, realised_unissued,
                        stopouts, cap_hit, closed_ids}
  guard:lock_1r         {"since": iso, "reason": str} set after a stop out; the next
                        issued setup is sized to 1R and consumes the lock
  guard:unissued        {key: {"first_seen": iso, ...}} positions/bots the guard never issued
  guard:grid_bots       {bot_id: {"symbol": "DOODUSDT" | null, "added_at": iso}} registry of
                        futures grid bot ids to watch. Bybit has NO grid list endpoint, so ids
                        are registered by hand (/addbot <id> [SYMBOL]) or via BYBIT_GRID_BOT_IDS.

Design (Manus's rules): no cooldown. After a stop out the guard keeps serving
edge gated setups but locks the next one to 1R ($12.50), never larger. Anything live
on Bybit that does not match an issued plan within tolerance is tagged "unissued"
(revenge) and its P&L is reported separately.
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from utils.logger import get_logger

log = get_logger(__name__)
SYD = ZoneInfo("Australia/Sydney")

try:
    from config import RISK_PER_TRADE_USD as ONE_R
except Exception:                                   # noqa: BLE001
    ONE_R = 12.5

ISSUED_TTL_H = 72          # an issued plan can be matched for this long
ENTRY_TOL_PCT = 2.0        # plain entry within 2% of the issued entry
EDGE_TOL_PCT = 1.0         # grid lo/hi within 1%
MARGIN_TOL_PCT = 60.0      # margin/investment within +/-60% (partial fills, fees)


def sydney_day(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(SYD).strftime("%Y-%m-%d")


def sydney_day_start_ms(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(SYD)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)


def _pct(a: float, b: float) -> float:
    return abs(a - b) / abs(b) * 100 if b else float("inf")


def norm_symbol(sym: str) -> str:
    """'DOOD-USD', 'dood', 'DOODUSDT' -> 'DOODUSDT'."""
    s = sym.upper().replace("-USD", "").replace("/USDT:USDT", "").replace("/", "").replace("-", "")
    return s if s.endswith("USDT") else s + "USDT"


class Ledger:
    """`get`/`set` default to triggers.db.get_state/set_state; inject dict backed ones in tests."""

    def __init__(self, get: Callable[[str], str | None] | None = None,
                 set_: Callable[[str, str], None] | None = None) -> None:
        if get is None or set_ is None:
            from triggers import db
            get, set_ = db.get_state, db.set_state
        self._get, self._set = get, set_

    # ── storage ──────────────────────────────────────────────────────────────
    def _load(self, key: str, default):
        raw = self._get(key)
        if not raw:
            return default
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return default

    def _save(self, key: str, value) -> None:
        self._set(key, json.dumps(value, separators=(",", ":"), default=str))

    # ── issued registry ─────────────────────────────────────────────────────
    def issued(self, now: datetime | None = None, active_only: bool = True) -> list[dict]:
        rows = self._load("guard:issued", [])
        if not active_only:
            return rows
        now = now or datetime.now(timezone.utc)
        cut = (now - timedelta(hours=ISSUED_TTL_H)).isoformat()
        return [r for r in rows if r.get("issued_at", "") >= cut or r.get("live")]

    def issue(self, plan: dict, now: datetime | None = None, consume_lock: bool = True) -> dict:
        """Register a guard issued plan. Applies the 1R lock and, when
        `consume_lock`, uses it up. Pass consume_lock=False for alerts merely
        sent (he may skip them); /took and /guard ... issue consume it.
        plan: {symbol, type: plain|grid, direction|mode, entry, stop, leverage,
               margin|investment, lo, hi, grids}."""
        now = now or datetime.now(timezone.utc)
        rec = dict(plan)
        rec["symbol"] = norm_symbol(rec["symbol"])
        rec.setdefault("id", uuid.uuid4().hex[:10])
        rec["issued_at"] = now.isoformat()
        lock = self.lock()
        if lock and not consume_lock:
            rec["size_locked"] = True
            rec["max_loss_usd"] = ONE_R
        elif lock:
            rec["size_locked"] = True
            rec["max_loss_usd"] = ONE_R
            self._set("guard:lock_1r", "")
        rows = self._load("guard:issued", [])
        rows.append(rec)
        self._save("guard:issued", rows[-200:])
        return rec

    def max_loss_for_next(self) -> float | None:
        """$ cap for the next issued setup: 1R while locked, else None (25% rule only)."""
        return ONE_R if self.lock() else None

    # ── grid bot registry ───────────────────────────────────────────────────
    def grid_bots(self) -> dict:
        return self._load("guard:grid_bots", {})

    def add_grid_bot(self, bot_id: str, symbol: str | None = None,
                     now: datetime | None = None) -> dict:
        bots = self.grid_bots()
        bots[str(bot_id)] = {"symbol": norm_symbol(symbol) if symbol else None,
                             "added_at": (now or datetime.now(timezone.utc)).isoformat()}
        self._save("guard:grid_bots", bots)
        return bots

    def remove_grid_bot(self, bot_id: str) -> bool:
        bots = self.grid_bots()
        gone = bots.pop(str(bot_id), None) is not None
        self._save("guard:grid_bots", bots)
        return gone

    def grid_bot_ids(self, env_ids: list[str] | None = None) -> list[str]:
        """Registry ids plus env ids, de-duplicated, registry order first."""
        ids = list(self.grid_bots())
        for i in env_ids or []:
            if i and i not in ids:
                ids.append(i)
        return ids

    # ── 1R lock ─────────────────────────────────────────────────────────────
    def lock(self) -> dict | None:
        v = self._load("guard:lock_1r", None)
        return v or None

    def record_stopout(self, symbol: str, pnl: float, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._save("guard:lock_1r", {"since": now.isoformat(),
                                     "reason": f"stop out {norm_symbol(symbol)} {pnl:+.2f}"})

    # ── daily P&L ───────────────────────────────────────────────────────────
    def day(self, now: datetime | None = None) -> dict:
        d = sydney_day(now)
        return self._load(f"guard:day:{d}", {"day": d, "realised": 0.0, "realised_issued": 0.0,
                                             "realised_unissued": 0.0, "stopouts": 0,
                                             "cap_hit": False, "closed_ids": []})

    def apply_closed(self, closed: list[dict], now: datetime | None = None,
                     stop_loss_threshold: float = 0.0) -> dict:
        """Fold Bybit closed P&L rows (closedPnl, symbol, orderId, updatedTime/createdTime)
        for today into the day record; each row counted once. A losing close of an
        issued trade counts as a stop out and arms the 1R lock."""
        now = now or datetime.now(timezone.utc)
        rec = self.day(now)
        start = sydney_day_start_ms(now)
        seen = set(rec["closed_ids"])
        unissued = self._load("guard:unissued", {})
        unissued_syms = {k.split(":")[1] for k in unissued if ":" in k}
        for row in closed:
            ts = int(row.get("updatedTime") or row.get("createdTime") or 0)
            if ts and ts < start:
                continue
            rid = str(row.get("orderId") or row.get("execId") or f"{row.get('symbol')}:{ts}")
            if rid in seen:
                continue
            seen.add(rid)
            pnl = float(row.get("closedPnl") or 0)
            sym = norm_symbol(row.get("symbol", ""))
            rec["realised"] += pnl
            if sym in unissued_syms:
                rec["realised_unissued"] += pnl
            else:
                rec["realised_issued"] += pnl
                if pnl < stop_loss_threshold:
                    rec["stopouts"] += 1
                    self.record_stopout(sym, pnl, now)
        rec["closed_ids"] = sorted(seen)[-500:]
        rec["realised"] = round(rec["realised"], 4)
        rec["realised_issued"] = round(rec["realised_issued"], 4)
        rec["realised_unissued"] = round(rec["realised_unissued"], 4)
        self._save(f"guard:day:{rec['day']}", rec)
        return rec

    def mark_cap_hit(self, now: datetime | None = None) -> bool:
        """Returns True the first time today (so the alert is sent once)."""
        rec = self.day(now)
        if rec.get("cap_hit"):
            return False
        rec["cap_hit"] = True
        self._save(f"guard:day:{rec['day']}", rec)
        return True

    # ── revenge detector ────────────────────────────────────────────────────
    def match(self, live: dict, now: datetime | None = None) -> dict | None:
        """Issued plan matching a live position/bot within tolerance, else None.
        live (normalised by the watcher): {kind: position|grid, symbol, side: long|short,
        entry, margin, lo, hi, grids, leverage}."""
        sym = norm_symbol(live["symbol"])
        for p in reversed(self.issued(now)):
            if p["symbol"] != sym:
                continue
            side = (p.get("direction") or p.get("mode") or "").lower()
            if side and side != live.get("side"):
                continue
            if live.get("kind") == "grid":
                if p.get("type") != "grid":
                    continue
                if (_pct(live["lo"], p["lo"]) > EDGE_TOL_PCT or _pct(live["hi"], p["hi"]) > EDGE_TOL_PCT
                        or int(live.get("grids") or 0) != int(p.get("grids") or 0)):
                    continue
                inv = p.get("investment")
                if inv and live.get("margin") and _pct(live["margin"], inv) > MARGIN_TOL_PCT:
                    continue
                return p
            # plain position (a grid bot's own position also shows up here: accept it)
            if p.get("type") == "grid":
                if p["lo"] * 0.99 <= live.get("entry", 0) <= p["hi"] * 1.01:
                    return p
                continue
            if p.get("entry") and live.get("entry") and _pct(live["entry"], p["entry"]) > ENTRY_TOL_PCT:
                continue
            if p.get("margin") and live.get("margin") and _pct(live["margin"], p["margin"]) > MARGIN_TOL_PCT:
                continue
            return p
        return None

    def tag_unissued(self, live_items: list[dict], now: datetime | None = None) -> list[dict]:
        """Returns the NEW unissued items (first sighting) and records them; also drops
        tags for items that are gone."""
        now = now or datetime.now(timezone.utc)
        tags = self._load("guard:unissued", {})
        current, new = {}, []
        for it in live_items:
            key = f"{it.get('kind', 'position')}:{norm_symbol(it['symbol'])}:{it.get('side', '')}"
            if self.match(it, now):
                continue
            if key in tags:
                current[key] = tags[key]
            else:
                current[key] = {"first_seen": now.isoformat(), "entry": it.get("entry"),
                                "margin": it.get("margin")}
                new.append({**it, "tag": "unissued"})
        # keep symbols of closed unissued positions for today's P&L split
        for k, v in tags.items():
            if k not in current and v.get("first_seen", "")[:10] >= (now - timedelta(days=2)).isoformat()[:10]:
                current[k] = {**v, "closed": True}
        self._save("guard:unissued", current)
        return new

    def unissued(self) -> dict:
        return self._load("guard:unissued", {})
