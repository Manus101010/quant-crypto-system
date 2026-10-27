"""
Shared plumbing for the feature clients: one requests session, a per-host
polite rate limiter, a small in-process TTL cache and a JSON GET that never
raises (returns None on any failure).

Read-only public GETs only. No keys are logged; header values are never echoed.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import requests

from utils.logger import get_logger

log = get_logger(__name__)

_session = requests.Session()
_session.headers.update({"User-Agent": "quant-crypto-system/features (read-only)"})

# ── TTL cache ───────────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def cache_get(key: str, ttl: float) -> Any:
    with _cache_lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    return None


def cache_put(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)
        if len(_cache) > 5000:                      # crude bound, drop oldest half
            for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[:2500]:
                _cache.pop(k, None)


def cache_clear() -> None:
    with _cache_lock:
        _cache.clear()


# ── Rate limiter: minimum spacing between calls per bucket ──────────────────
class RateLimiter:
    """Spacing limiter: at most `calls` per `per` seconds, evenly spaced.
    Thread-safe; callers block (sleep) until their slot."""

    def __init__(self, calls: int, per: float):
        self.gap = per / max(calls, 1)
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.gap
        delay = slot - time.monotonic()
        if delay > 0:
            time.sleep(delay)


_limiters: dict[str, RateLimiter] = {}


def limiter(bucket: str, calls: int, per: float) -> RateLimiter:
    lim = _limiters.get(bucket)
    if lim is None:
        lim = _limiters[bucket] = RateLimiter(calls, per)
    return lim


# ── Geo / outage memory: skip a host for a while after a hard block ─────────
_blocked: dict[str, float] = {}
BLOCK_TTL = 3600.0


def is_blocked(host: str) -> bool:
    t = _blocked.get(host)
    return bool(t and time.time() - t < BLOCK_TTL)


def mark_blocked(host: str) -> None:
    _blocked[host] = time.time()


def get_json(url: str, params: dict | None = None, *, headers: dict | None = None,
             bucket: str | None = None, rate: tuple[int, float] | None = None,
             timeout: float = 6.0, host: str | None = None) -> Any:
    """GET -> parsed JSON, or None on any error. A 403/451 marks `host` blocked
    for BLOCK_TTL so later calls skip it instantly (Bybit from US hosts)."""
    if host and is_blocked(host):
        return None
    if bucket and rate:
        limiter(bucket, *rate).wait()
    try:
        r = _session.get(url, params=params, headers=headers, timeout=timeout)
    except Exception as exc:                        # noqa: BLE001
        log.debug("features http %s failed: %s", url, type(exc).__name__)
        return None
    if r.status_code in (403, 451) and host:
        mark_blocked(host)
        log.debug("features http %s -> %s, host marked blocked", url, r.status_code)
        return None
    if r.status_code != 200:
        log.debug("features http %s -> %s", url, r.status_code)
        return None
    try:
        return r.json()
    except ValueError:
        return None


def fnum(x: Any) -> float | None:
    """float or None (handles strings, None, NaN)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def pct_rank(value: float | None, history: list[float]) -> float | None:
    """Percentile (0-100) of value within history (inclusive, ties count half)."""
    hist = [h for h in history if h is not None]
    if value is None or len(hist) < 5:
        return None
    below = sum(1 for h in hist if h < value)
    equal = sum(1 for h in hist if h == value)
    return round(100.0 * (below + 0.5 * equal) / len(hist), 1)


def split_symbol(symbol: str) -> tuple[str, str]:
    """'1000PEPE-USD' -> ('1000PEPE', 'PEPE'); 'SOLUSDT' -> ('SOL', 'SOL').
    Returns (venue base as Bybit lists it, core coin without multiplier prefix)."""
    s = symbol.strip().upper()
    for suf in ("-USDT-SWAP", "-USD", "/USDT", "_USDT", "USDT", "-USDT", ":USDT"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    core = s
    for p in ("1000000", "10000", "1000"):
        if s.startswith(p) and len(s) > len(p) and not s[len(p)].isdigit():
            core = s[len(p):]
            break
    return s, core
