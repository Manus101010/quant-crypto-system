"""
Read-only crypto exchange data layer (ccxt).

STRICTLY read-only, public market data only — OHLC candles and funding rates.
No API keys, no auth, no order/account endpoints are ever touched. This module
is the canonical price source for the crypto refocus; it supersedes the
requests-based utils/bybit.py (kept only as a legacy fallback).

Exchanges are tried in a fallback chain so a geo-block or outage on one
degrades gracefully to the next. All clients set enableRateLimit=True so ccxt
paces requests within each venue's public limits.
"""
from __future__ import annotations
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.logger import get_logger

log = get_logger(__name__)

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:                       # keep import-safe if ccxt missing
    CCXT_AVAILABLE = False

# Spot exchanges for OHLC, tried in order. All serve public candles keyless.
_SPOT_CHAIN = ["binance", "bybit", "okx", "kraken", "coinbase"]
# Perp/swap venues for funding rates (linear USDT perps).
_PERP_CHAIN = ["binance", "bybit", "okx"]
_MAX_WORKERS = 8

_clients: dict[str, "ccxt.Exchange"] = {}   # name -> client (spot)


def _client(name: str, *, swap: bool = False) -> "ccxt.Exchange | None":
    key = f"{name}:{'swap' if swap else 'spot'}"
    if key in _clients:
        return _clients[key]
    if not CCXT_AVAILABLE:
        return None
    try:
        opts = {"enableRateLimit": True, "timeout": 10000}
        if swap:
            opts["options"] = {"defaultType": "swap"}
        ex = getattr(ccxt, name)(opts)
        _clients[key] = ex
        return ex
    except Exception as exc:               # noqa: BLE001
        log.warning("exchange: could not init %s (%s)", key, exc)
        return None


def to_ccxt_symbol(sym: str) -> str:
    """
    Normalise a ticker to ccxt spot format 'BASE/QUOTE'.
      BTC-USD → BTC/USDT, BTCUSDT → BTC/USDT, BTC → BTC/USDT, BTC/USDT → unchanged
    """
    s = sym.strip().upper()
    if "/" in s:
        return s
    if s.endswith("-USD"):
        return f"{s[:-4]}/USDT"
    if s.endswith("USDT"):
        return f"{s[:-4]}/USDT"
    if s.endswith("USD"):
        return f"{s[:-3]}/USDT"
    return f"{s}/USDT"


def get_ohlcv(symbol: str, timeframe: str = "1d", limit: int = 400,
              exchange: str | None = None) -> pd.DataFrame:
    """
    Return a DataFrame [open, high, low, close, volume] indexed by UTC datetime.
    Tries the spot fallback chain (or a single `exchange` if given). Empty
    DataFrame if every venue fails / lacks the pair.
    """
    ccxt_sym = to_ccxt_symbol(symbol)
    chain = [exchange] if exchange else _SPOT_CHAIN
    for name in chain:
        ex = _client(name)
        if ex is None:
            continue
        try:
            rows = ex.fetch_ohlcv(ccxt_sym, timeframe=timeframe, limit=limit)
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_localize(None)
            df = df.set_index("ts")
            for c in ("open", "high", "low", "close", "volume"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.dropna(subset=["close"])
        except Exception as exc:           # noqa: BLE001
            log.debug("exchange: %s ohlcv %s failed — %s", name, ccxt_sym, exc)
            continue
    log.warning("exchange: no OHLC for %s on any venue", symbol)
    return pd.DataFrame()


def get_ohlcv_batch(symbols: list[str], timeframe: str = "1d", limit: int = 400,
                    exchange: str | None = None) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLC for many symbols in parallel (bounded workers; ccxt still paces
    each client via enableRateLimit). Symbols with no data are omitted.
    """
    out: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futs = {pool.submit(get_ohlcv, s, timeframe, limit, exchange): s for s in symbols}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                df = fut.result()
                if not df.empty:
                    out[s] = df
            except Exception as exc:       # noqa: BLE001
                log.debug("exchange: batch %s failed — %s", s, exc)
    log.info("exchange: OHLC for %d/%d symbols", len(out), len(symbols))
    return out


def get_last_prices(symbols: list[str]) -> dict[str, float]:
    """
    Batched latest spot price → {symbol: last_price}. One fetch_tickers call
    covers the whole list on a venue; falls back to per-symbol 1m candles.
    Used by the monitor to evaluate price-level triggers with live prices.
    """
    if not symbols:
        return {}
    ccxt_syms = [to_ccxt_symbol(s) for s in symbols]
    for name in _SPOT_CHAIN:
        ex = _client(name)
        if ex is None:
            continue
        try:
            tickers = ex.fetch_tickers(ccxt_syms)
            out = {}
            for orig, cs in zip(symbols, ccxt_syms):
                t = tickers.get(cs)
                if t and t.get("last") is not None:
                    out[orig] = float(t["last"])
            if out:
                return out
        except Exception as exc:           # noqa: BLE001
            log.debug("exchange: %s fetch_tickers failed — %s", name, exc)
            continue
    # Per-symbol fallback
    out = {}
    for s in symbols:
        df = get_ohlcv(s, "1m", limit=1)
        if not df.empty:
            out[s] = float(df["close"].iloc[-1])
    return out


def get_funding_rate(symbol: str, exchange: str | None = None) -> dict | None:
    """
    Latest funding rate for a USDT perp. Returns {symbol, rate, exchange} or None.
    Positive = longs pay shorts (crowded longs); negative = shorts pay longs.
    """
    ccxt_sym = to_ccxt_symbol(symbol).replace("/USDT", "/USDT:USDT")  # linear perp
    chain = [exchange] if exchange else _PERP_CHAIN
    for name in chain:
        ex = _client(name, swap=True)
        if ex is None:
            continue
        try:
            fr = ex.fetch_funding_rate(ccxt_sym)
            rate = fr.get("fundingRate")
            if rate is not None:
                return {"symbol": symbol, "rate": float(rate), "exchange": name}
        except Exception as exc:           # noqa: BLE001
            log.debug("exchange: %s funding %s failed — %s", name, ccxt_sym, exc)
            continue
    return None


def get_funding_rates(symbols: list[str]) -> dict[str, float]:
    """Batch funding rates → {symbol: rate}. Symbols without a perp are omitted."""
    out: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futs = {pool.submit(get_funding_rate, s): s for s in symbols}
        for fut in as_completed(futs):
            try:
                r = fut.result()
                if r:
                    out[r["symbol"]] = r["rate"]
            except Exception:              # noqa: BLE001
                pass
    return out
