"""
Bybit Spot OHLCV Fetcher
Pulls daily candlestick data from Bybit's public REST API (no auth required).
Used as a replacement for yfinance for the crypto scanner — faster, no rate limits,
and covers 500+ coins cleanly via USDT pairs.

Symbol format: yfinance-style "BTC-USD" is converted to Bybit "BTCUSDT" internally.
"""
from __future__ import annotations
import time
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.logger import get_logger

log = get_logger(__name__)

_BASE     = "https://api.bybit.com/v5/market/kline"
_INSTR    = "https://api.bybit.com/v5/market/instruments-info"
_TTL      = 3600   # 1-hour cache for available symbols list
_MAX_WORKERS = 20  # parallel requests

_symbol_cache: tuple[float, set[str]] | None = None   # (timestamp, {BTCUSDT, ...})


def _to_bybit(ticker: str) -> str:
    """Convert yfinance-style ticker to Bybit symbol. BTC-USD → BTCUSDT."""
    return ticker.replace("-USD", "USDT").replace("-", "").upper()


def _available_symbols() -> set[str]:
    """Return the set of active Bybit spot USDT symbols, cached for 1 hour."""
    global _symbol_cache
    now = time.time()
    if _symbol_cache and now - _symbol_cache[0] < _TTL:
        return _symbol_cache[1]

    syms: set[str] = set()
    cursor = ""
    while True:
        try:
            params = {"category": "spot", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            r = requests.get(_INSTR, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            for item in data["result"]["list"]:
                if item.get("quoteCoin") == "USDT" and item.get("status") == "Trading":
                    syms.add(item["symbol"])
            cursor = data["result"].get("nextPageCursor", "")
            if not cursor:
                break
        except Exception as exc:
            log.warning("bybit: failed to fetch instruments — %s", exc)
            break

    if syms:
        _symbol_cache = (now, syms)
        log.info("bybit: %d active USDT spot symbols", len(syms))
    return syms


def _fetch_one(symbol: str, days: int = 365) -> pd.DataFrame | None:
    """Fetch daily OHLCV for one Bybit symbol. Returns DataFrame or None on failure."""
    try:
        params = {
            "category": "spot",
            "symbol":   symbol,
            "interval": "D",
            "limit":    min(days, 1000),
        }
        r = requests.get(_BASE, params=params, timeout=10)
        r.raise_for_status()
        rows = r.json()["result"]["list"]
        if not rows:
            return None

        # Bybit returns newest-first: [timestamp_ms, open, high, low, close, volume, turnover]
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "turnover"])
        df["ts"] = pd.to_datetime(df["ts"].astype(float), unit="ms", utc=True).dt.tz_localize(None)
        # Bybit returns all OHLCV fields as strings — cast every numeric column,
        # not just close/volume, or downstream math (e.g. ATR high-low) breaks.
        for col in ("open", "high", "low", "close", "volume", "turnover"):
            df[col] = df[col].astype(float)
        df = df.sort_values("ts").set_index("ts")
        return df
    except Exception as exc:
        log.debug("bybit: %s failed — %s", symbol, exc)
        return None


def fetch_ohlcv(tickers: list[str], days: int = 365) -> dict[str, pd.DataFrame]:
    """
    Fetch daily OHLCV for a list of yfinance-style crypto tickers in parallel.

    Args:
        tickers: e.g. ["BTC-USD", "ETH-USD", ...]
        days:    how many daily bars to fetch (max 1000)

    Returns:
        dict mapping original ticker → DataFrame(close, volume, turnover)
        Tickers not found on Bybit are silently omitted.
    """
    available = _available_symbols()

    # Map original ticker → Bybit symbol, filtering to what's actually listed
    mapping: dict[str, str] = {}
    for t in tickers:
        sym = _to_bybit(t)
        if sym in available:
            mapping[t] = sym
        else:
            log.debug("bybit: %s (%s) not on Bybit spot — skipping", t, sym)

    log.info("bybit: fetching %d/%d tickers in parallel", len(mapping), len(tickers))

    results: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, sym, days): ticker for ticker, sym in mapping.items()}
        for fut in as_completed(futures):
            ticker = futures[fut]
            df = fut.result()
            if df is not None and not df.empty:
                results[ticker] = df

    log.info("bybit: got data for %d tickers", len(results))
    return results
