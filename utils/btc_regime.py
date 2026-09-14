"""
BTC higher-timeframe regime read — the market-structure gate.

Pure ccxt, read-only BTC OHLC (weekly + daily). Rolls a handful of structural
reads into one label: RISK-ON / NEUTRAL / RISK-OFF. Used as a WARNING stamp on
alerts (never a veto in v1) and as the banner at the top of the scanner.

Direction-aware by design (shorts are coming): the SAME label means opposite
things for longs vs shorts —
  • longs : RISK-OFF is the caution, RISK-ON is confirmation.
  • shorts: RISK-ON  is the caution, RISK-OFF is confirmation.
Use stamp_for(label, direction) to get the right ⚠️/✓ stamp.

Cached in-memory (TTL 6h) so the monitor's per-poll hot path never refetches on
a normal cadence — weekly/daily structure moves far slower than that. This keeps
the guardrail: the hot path touches only ccxt, and even that is cached slowly.
"""
from __future__ import annotations
import time
import threading
import pandas as pd
from utils.exchange import get_ohlcv
from utils.logger import get_logger

log = get_logger(__name__)

_TTL = 6 * 3600            # 6-hour cache — HTF structure is slow-moving
_cache: dict[str, tuple[float, object]] = {}
_LOCK = threading.Lock()

RISK_ON, NEUTRAL, RISK_OFF = "RISK-ON", "NEUTRAL", "RISK-OFF"


def _sma(s: pd.Series, n: int) -> float | None:
    if len(s) < n:
        return None
    return float(s.iloc[-n:].mean())


def _engulfing(o: pd.Series, c: pd.Series) -> str | None:
    """Two-candle engulfing on the last CLOSED bar vs the prior bar."""
    if len(c) < 2:
        return None
    o1, c1 = float(o.iloc[-2]), float(c.iloc[-2])
    o2, c2 = float(o.iloc[-1]), float(c.iloc[-1])
    body1_lo, body1_hi = min(o1, c1), max(o1, c1)
    # Bullish: prior down, current up, current body engulfs prior body.
    if c2 > o2 and c1 < o1 and c2 >= body1_hi and o2 <= body1_lo:
        return "bullish_engulfing"
    # Bearish: prior up, current down, current body engulfs prior body.
    if c2 < o2 and c1 > o1 and o2 >= body1_hi and c2 <= body1_lo:
        return "bearish_engulfing"
    return None


def _compute() -> dict:
    """Fetch BTC weekly+daily OHLC and roll structure into a regime label."""
    wk = get_ohlcv("BTC-USD", "1w", limit=120)
    dl = get_ohlcv("BTC-USD", "1d", limit=400)
    if wk.empty or dl.empty or len(wk) < 51 or len(dl) < 205:
        return {"label": NEUTRAL, "detail": "insufficient BTC history",
                "weekly": {}, "daily": {}, "ok": False}

    wclose = wk["close"]
    w_price = float(wclose.iloc[-1])
    w_prev = float(wclose.iloc[-2])
    sma20w = _sma(wclose, 20)
    sma50w = _sma(wclose, 50)
    engulf = _engulfing(wk["open"], wk["close"])

    dclose = dl["close"]
    d_price = float(dclose.iloc[-1])
    sma200d = _sma(dclose, 200)
    sma20d_now = _sma(dclose, 20)
    sma20d_prev = float(dclose.iloc[-25:-5].mean()) if len(dclose) >= 25 else sma20d_now
    slope_up = sma20d_now is not None and sma20d_prev is not None and sma20d_now > sma20d_prev

    weekly = {
        "close_gt_prev": w_price > w_prev,
        "close_gt_20w": sma20w is not None and w_price > sma20w,
        "close_gt_50w": sma50w is not None and w_price > sma50w,
        "engulfing": engulf,
    }
    daily = {
        "close_gt_200d": sma200d is not None and d_price > sma200d,
        "sma20_slope_up": bool(slope_up),
    }

    # ── Label rules ───────────────────────────────────────────────────────────
    bearish_engulf = engulf == "bearish_engulfing"
    below_both_w = (sma20w is not None and sma50w is not None
                    and w_price < sma20w and w_price < sma50w)
    below_200d = sma200d is not None and d_price < sma200d

    if bearish_engulf or below_both_w or below_200d:
        label = RISK_OFF
    elif (daily["close_gt_200d"] and weekly["close_gt_20w"]
          and (weekly["close_gt_prev"] or engulf == "bullish_engulfing")
          and daily["sma20_slope_up"]):
        label = RISK_ON
    else:
        label = NEUTRAL

    bits = []
    if engulf:
        bits.append("weekly " + engulf.replace("_", " "))
    bits.append(f"{'>' if weekly['close_gt_20w'] else '<'}20W")
    bits.append(f"{'>' if weekly['close_gt_50w'] else '<'}50W")
    bits.append(f"{'>' if daily['close_gt_200d'] else '<'}200D")
    bits.append("20D " + ("rising" if slope_up else "falling"))
    detail = "BTC " + ", ".join(bits)

    return {"label": label, "detail": detail, "weekly": weekly, "daily": daily,
            "ok": True, "price": d_price}


def get_btc_regime(force: bool = False) -> dict:
    """Cached regime read (TTL 6h). Safe to call every poll — refetches slowly."""
    hit = _cache.get("regime")
    if hit and not force and time.time() - hit[0] < _TTL:
        return hit[1]
    with _LOCK:
        hit = _cache.get("regime")
        if hit and not force and time.time() - hit[0] < _TTL:
            return hit[1]
        try:
            res = _compute()
        except Exception as exc:                 # noqa: BLE001 — never break the caller
            log.warning("btc_regime: compute failed — %s", exc)
            res = {"label": NEUTRAL, "detail": f"unavailable: {exc}",
                   "weekly": {}, "daily": {}, "ok": False}
        _cache["regime"] = (time.time(), res)
        return res


def btc_return(days: int = 30, force: bool = False) -> float | None:
    """BTC N-day % return from cached daily closes (for relative-strength calc)."""
    key = "daily_close"
    hit = _cache.get(key)
    if not hit or force or time.time() - hit[0] >= _TTL:
        with _LOCK:
            try:
                dl = get_ohlcv("BTC-USD", "1d", limit=400)
                _cache[key] = (time.time(), dl["close"] if not dl.empty else None)
            except Exception as exc:              # noqa: BLE001
                log.warning("btc_regime: btc_return fetch failed — %s", exc)
                _cache[key] = (time.time(), None)
        hit = _cache.get(key)
    close = hit[1]
    if close is None or len(close) <= days:
        return None
    return float((close.iloc[-1] / close.iloc[-1 - days] - 1) * 100)


def stamp_for(label: str, direction: str) -> str:
    """
    Direction-aware alert stamp. For longs RISK-OFF is caution; for shorts
    RISK-ON is caution and RISK-OFF is confirmation.
    """
    caution = "⚠️ CAUTION"
    confirm = "✓ with trend"
    if direction == "short":
        if label == RISK_ON:
            return caution
        if label == RISK_OFF:
            return confirm
        return "· neutral tape"
    # long (default)
    if label == RISK_OFF:
        return caution
    if label == RISK_ON:
        return confirm
    return "· neutral tape"
