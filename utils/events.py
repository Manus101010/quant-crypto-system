"""
Event-risk calendar: token unlocks + macro releases, for WARNINGS (never blocks).

Sources (all free):
  • DefiLlama public dataset `emissionsIndex` — scheduled cliff unlocks per token
    (the /emissions API is paid; the public bucket isn't). Coverage is incomplete
    (e.g. it misses ENA's Oct-2026 investor unlock), hence:
  • data/events_manual.json — hand-added unlocks / macro / catalysts.
  • FRED release calendar — jobs, CPI, PCE, GDP, PPI (needs a valid FRED key;
    silently skipped otherwise).
  • FOMC decision days (published 2026 schedule).

Warnings only: unlock/macro effects aren't backtested in this system, so they
inform the alert rather than gate it.
"""
from __future__ import annotations
import datetime as _dt
import json
import threading
import time
from pathlib import Path

import requests

from config import FRED_API_KEY, ROOT_DIR
from utils.logger import get_logger

log = get_logger(__name__)

_UNLOCK_URL = "https://defillama-datasets.llama.fi/emissionsIndex"
_MANUAL = ROOT_DIR / "data" / "events_manual.json"
_TTL = 12 * 3600
_cache: dict = {}
_lock = threading.Lock()

UNLOCK_WARN_PCT = 1.0      # warn if ≥1% of circulating supply unlocks in the window
UNLOCK_BIG_PCT = 5.0       # "big" unlock

# FOMC rate-decision days (2nd day of each meeting), Federal Reserve 2026 calendar.
_FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
              "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]
# FRED release ids → plain names (the big crypto movers).
_FRED_RELEASES = {50: "US jobs report", 10: "US CPI inflation", 54: "US PCE inflation",
                  53: "US GDP", 46: "US PPI inflation"}


def _cached(key: str, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]
        try:
            val = fn()
        except Exception as exc:                  # noqa: BLE001 — events are best-effort
            log.warning("events: %s failed — %s", key, exc)
            val = hit[1] if hit else None
        _cache[key] = (time.time(), val)
        return val


def _manual() -> list[dict]:
    try:
        return json.loads(_MANUAL.read_text()).get("events", [])
    except Exception:                             # noqa: BLE001
        return []


def _today() -> _dt.date:
    return _dt.datetime.utcnow().date()


# ── Token unlocks ─────────────────────────────────────────────────────────────
def _load_unlocks() -> dict[str, list[dict]]:
    """{SYMBOL: [{date, pct, usd, name}]} for cliff unlocks in the next 30 days."""
    data = requests.get(_UNLOCK_URL, timeout=60).json().get("data", [])
    now = time.time()
    horizon = now + 30 * 86400
    best: dict[str, dict] = {}                    # symbol → token entry with largest mcap
    for x in data:
        sym = ((x.get("tokenPrice") or [{}])[0] or {}).get("symbol")
        if not sym or not x.get("circSupply"):
            continue
        sym = sym.upper()
        if sym not in best or (x.get("mcap") or 0) > (best[sym].get("mcap") or 0):
            best[sym] = x
    out: dict[str, list[dict]] = {}
    for sym, x in best.items():
        price = ((x.get("tokenPrice") or [{}])[0] or {}).get("price") or 0
        for ev in x.get("events") or []:
            ts = ev.get("timestamp") or 0
            if not (now <= ts <= horizon) or ev.get("unlockType") != "cliff":
                continue
            n = sum(v for v in (ev.get("noOfTokens") or []) if isinstance(v, (int, float)))
            if n <= 0:
                continue
            out.setdefault(sym, []).append({
                "date": _dt.datetime.utcfromtimestamp(ts).date().isoformat(),
                "pct": n / x["circSupply"] * 100, "usd": n * price,
                "name": f"{x.get('name', sym)} token unlock"})
    return out


def unlocks_for(symbol: str, days: int = 7) -> list[dict]:
    """Upcoming unlocks for a coin (e.g. 'ENA-USD') within `days`, ≥ UNLOCK_WARN_PCT,
    merged per day (DefiLlama lists each allocation separately)."""
    sym = symbol.upper().replace("-USD", "").replace("/USDT", "")
    end = (_today() + _dt.timedelta(days=days)).isoformat()
    start = _today().isoformat()
    auto = (_cached("unlocks", _load_unlocks) or {}).get(sym, [])
    man = [{"date": e["date"], "pct": float(e.get("pct") or 0), "usd": None,
            "name": e.get("name", "token unlock"), "manual": True}
           for e in _manual() if e.get("type") == "unlock" and (e.get("symbol") or "").upper() == sym]
    by_day: dict[str, dict] = {}
    for e in auto + man:
        if not (start <= e["date"] <= end):
            continue
        d = by_day.setdefault(e["date"], {"date": e["date"], "pct": 0.0, "usd": 0.0,
                                          "name": e["name"]})
        if e.get("manual"):
            d.update({"pct": max(d["pct"], e["pct"]), "name": e["name"]})
        else:
            d["pct"] += e["pct"]
            d["usd"] += e["usd"] or 0
    return sorted((d for d in by_day.values() if d["pct"] >= UNLOCK_WARN_PCT),
                  key=lambda d: d["date"])


# ── Macro ─────────────────────────────────────────────────────────────────────
def _load_fred() -> list[dict]:
    if not FRED_API_KEY or len(FRED_API_KEY) != 32:
        return []                                  # invalid/missing key → skip quietly
    start = _today().isoformat()
    end = (_today() + _dt.timedelta(days=30)).isoformat()
    r = requests.get("https://api.stlouisfed.org/fred/releases/dates", timeout=20, params={
        "api_key": FRED_API_KEY, "file_type": "json", "realtime_start": start,
        "realtime_end": end, "include_release_dates_with_no_data": "true", "limit": 1000})
    out = []
    for x in r.json().get("release_dates", []):
        name = _FRED_RELEASES.get(x.get("release_id"))
        if name and start <= x["date"] <= end:
            out.append({"date": x["date"], "name": name})
    return out


def macro_events(days: int = 7) -> list[dict]:
    start = _today().isoformat()
    end = (_today() + _dt.timedelta(days=days)).isoformat()
    evs = [{"date": d, "name": "Fed rate decision (FOMC)"} for d in _FOMC_2026]
    evs += _cached("fred", _load_fred) or []
    evs += [{"date": e["date"], "name": e.get("name", "macro event")}
            for e in _manual() if e.get("type") == "macro"]
    seen, out = set(), []
    for e in sorted(evs, key=lambda e: e["date"]):
        k = (e["date"], e["name"].lower()[:12])
        if start <= e["date"] <= end and k not in seen:
            seen.add(k)
            out.append(e)
    return out


def catalysts_for(symbol: str, days: int = 7) -> list[dict]:
    sym = symbol.upper().replace("-USD", "")
    start = _today().isoformat()
    end = (_today() + _dt.timedelta(days=days)).isoformat()
    return [e for e in _manual() if e.get("type") == "catalyst"
            and (e.get("symbol") or "").upper() == sym and start <= e["date"] <= end]


# ── Plain-English lines for alerts / scans / brief ────────────────────────────
def _when(date_iso: str) -> str:
    d = (_dt.date.fromisoformat(date_iso) - _today()).days
    day = _dt.date.fromisoformat(date_iso).strftime("%a %-d %b")
    return "today" if d == 0 else ("tomorrow" if d == 1 else f"{day} (in {d} days)")


def coin_warning(symbol: str, days: int = 7) -> str:
    """One warning line for a coin, or '' if nothing's coming."""
    parts = []
    for u in unlocks_for(symbol, days):
        size = "BIG " if u["pct"] >= UNLOCK_BIG_PCT else ""
        usd = f", ≈ ${u['usd'] / 1e6:,.0f}M" if u.get("usd") else ""
        parts.append(f"🔓 {size}token unlock {_when(u['date'])}: {u['pct']:.1f}% of supply{usd} "
                     "— new supply can push the price down")
    for c in catalysts_for(symbol, days):
        parts.append(f"📌 {c['name']} — {_when(c['date'])}")
    return "\n".join(parts)


def macro_warning(days: int = 3) -> str:
    ev = macro_events(days)
    if not ev:
        return ""
    return "🗓 Market-moving news soon: " + "; ".join(
        f"{e['name']} {_when(e['date'])}" for e in ev) + " — expect bigger swings."
