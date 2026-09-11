"""
Lightweight FRED data fetcher.
Uses the public FRED CSV endpoint — no API key required.
Falls back to stale cache if FRED is unreachable, so signals degrade
gracefully instead of failing hard.
"""
from __future__ import annotations
import io
import time
import requests
import pandas as pd
from utils.logger import get_logger

log = get_logger(__name__)

_FRED_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_CACHE: dict[str, tuple[float, pd.Series]] = {}
_TTL       = 3600        # fresh data TTL: 1 hour
_STALE_TTL = 86400 * 7   # stale fallback: use cached data up to 7 days old


def fetch_fred(series: str, *, timeout: int = 8) -> pd.Series:
    """
    Fetch a FRED series and return it as a dated pd.Series.

    Cache strategy:
    - Fresh cache (< 1h): return immediately, no network call
    - Stale cache (1h–7d): try network first, fall back to stale on failure
    - No cache: try network, raise on failure
    """
    now = time.time()

    if series in _CACHE:
        ts, cached = _CACHE[series]
        if now - ts < _TTL:
            log.debug("FRED %s: cache hit (%.0fs old)", series, now - ts)
            return cached
        # Stale — try to refresh but keep as fallback
        stale = cached
        stale_age = now - ts
    else:
        stale = None
        stale_age = None

    # Try to fetch fresh data
    url = f"{_FRED_BASE}?id={series}"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()

        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = ["date", "value"]
        df["date"]  = pd.to_datetime(df["date"])
        df          = df.set_index("date")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        s = df["value"].dropna().rename(series)

        _CACHE[series] = (now, s)
        log.debug("FRED %s fetched: %d obs (latest=%s)", series, len(s), s.index[-1].date())
        return s

    except Exception as exc:
        if stale is not None and stale_age is not None and stale_age < _STALE_TTL:
            log.warning("FRED %s unreachable (%s) — using stale cache (%.0fh old)",
                        series, exc, stale_age / 3600)
            return stale
        raise
