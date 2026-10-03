"""
Altcoin breadth: share of a fixed universe closing above its own 50-day SMA.

Used as a gate for new LONGS together with BTC above its 200d and 50d
(config.ALT_BREADTH_MIN). The universe and threshold are the ones validated in
research/breadth_long.py (2020-2026, 27k trades): adding breadth50 > 60% to the
BTC filter cut max drawdown -2233R -> -1430R and raised total R 2567 -> 2802.
Cached 6h; returns None if too few coins load (callers fail OPEN, BTC gate stays).
"""
from __future__ import annotations
import json
import threading
import time

from config import ROOT_DIR
from utils.exchange import get_ohlcv_batch
from utils.logger import get_logger

log = get_logger(__name__)
_TTL = 6 * 3600
_MIN_COINS = 60
_cache: dict = {}
_lock = threading.Lock()


def _universe() -> list[str]:
    return json.loads((ROOT_DIR / "data" / "breadth_universe.json").read_text())["symbols"]


def _compute() -> dict | None:
    data = get_ohlcv_batch(_universe(), "1d", limit=60)
    above = counted = 0
    for df in data.values():
        if df is None or len(df) < 50:
            continue
        counted += 1
        above += float(df["close"].iloc[-1]) > float(df["close"].iloc[-50:].mean())
    if counted < _MIN_COINS:
        log.warning("breadth: only %d coins loaded — unavailable", counted)
        return None
    return {"pct": above / counted * 100, "above": above, "counted": counted}


def alt_breadth(force: bool = False) -> dict | None:
    hit = _cache.get("b")
    if hit and not force and time.time() - hit[0] < _TTL:
        return hit[1]
    with _lock:
        hit = _cache.get("b")
        if hit and not force and time.time() - hit[0] < _TTL:
            return hit[1]
        try:
            val = _compute()
        except Exception as exc:                   # noqa: BLE001
            log.warning("breadth: compute failed — %s", exc)
            val = None
        _cache["b"] = (time.time(), val)
        return val


def long_gate() -> tuple[bool, str]:
    """(longs allowed?, reason). BTC above 200d AND 50d, and alt breadth above the
    threshold. Missing data fails OPEN for breadth (logged), never for BTC data
    that loaded and says no."""
    from config import ALT_BREADTH_MIN, BTC_200D_LONG_GATE
    if not BTC_200D_LONG_GATE:
        return True, ""
    from utils import btc_regime
    r = btc_regime.get_btc_regime()
    daily = r.get("daily") or {}
    if r.get("ok"):
        if not daily.get("close_gt_200d", True):
            return False, "Bitcoin below its 200-day average"
        if daily.get("close_gt_50d") is False:
            return False, "Bitcoin below its 50-day average"
    b = alt_breadth()
    if b is not None and b["pct"] < ALT_BREADTH_MIN:
        return False, f"only {b['pct']:.0f}% of altcoins above their 50-day (need {ALT_BREADTH_MIN:.0f}%)"
    return True, ""
