"""
Free crypto macro data sources for the deployment-gate signals.

  - CoinGecko  /global      → BTC dominance %, total crypto market cap
  - CoinGecko  /global/market_cap_chart → total market-cap history (trend + sparkline)
  - DeFiLlama  /v2/historicalChainTvl   → total DeFi TVL (level + history)
  - alternative.me /fng     → Fear & Greed index (0-100) + history

All keyless, free, read-only. Each fetch is cached in-memory (TTL) and returns
None / [] gracefully on failure so signals degrade to neutral rather than crash.
"""
from __future__ import annotations
import time
import requests
from utils.logger import get_logger

log = get_logger(__name__)

_TTL = 900  # 15-minute cache — these are slow-moving macro series
_cache: dict[str, tuple[float, object]] = {}
_TIMEOUT = 12


def _cached(key: str):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    return None


def _store(key: str, val):
    _cache[key] = (time.time(), val)
    return val


# ── CoinGecko globals: BTC dominance + total market cap ───────────────────────
def global_snapshot() -> dict:
    """{'btc_dominance': %, 'total_mcap_usd': float} — or empty dict on failure."""
    c = _cached("global")
    if c is not None:
        return c
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=_TIMEOUT)
        r.raise_for_status()
        d = r.json()["data"]
        out = {
            "btc_dominance":  float(d["market_cap_percentage"]["btc"]),
            "eth_dominance":  float(d["market_cap_percentage"].get("eth", 0.0)),
            "total_mcap_usd": float(d["total_market_cap"]["usd"]),
        }
        return _store("global", out)
    except Exception as exc:               # noqa: BLE001
        log.warning("crypto_macro: CoinGecko /global failed — %s", exc)
        return {}


def _coin_mcap_history(coin_id: str, days: int) -> list[float]:
    """Free per-coin market-cap history (USD) via CoinGecko /market_chart."""
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": days, "interval": "daily"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        caps = r.json().get("market_caps", [])
        return [float(p[1]) for p in caps if p and p[1] is not None]
    except Exception as exc:               # noqa: BLE001
        log.warning("crypto_macro: coin mcap %s failed — %s", coin_id, exc)
        return []


def total_mcap_history(days: int = 365) -> list[float]:
    """
    Total crypto market-cap daily history (USD), reconstructed from the free
    per-coin endpoints (CoinGecko's global chart is Pro-gated). We sum BTC+ETH
    market-cap history and gross up by their *current* combined dominance so the
    series tracks the whole market (incl. alts), not just BTC price. Anchored to
    the live /global total so the level is right; the shape drives the trend.
    """
    key = f"mcap_hist_{days}"
    c = _cached(key)
    if c is not None:
        return c
    btc = _coin_mcap_history("bitcoin", days)
    eth = _coin_mcap_history("ethereum", days)
    if not btc:
        return _store(key, [])
    g = global_snapshot()
    share = (g.get("btc_dominance", 55.0) + g.get("eth_dominance", 15.0)) / 100.0
    share = max(share, 0.30)               # guard against a bad dominance read
    n = min(len(btc), len(eth)) if eth else len(btc)
    combined = [(btc[i] + (eth[i] if eth else 0)) / share for i in range(n)]
    return _store(key, combined)


# ── DeFiLlama: total DeFi TVL ─────────────────────────────────────────────────
def defi_tvl_history() -> list[float]:
    """Total DeFi TVL (USD) daily history. Last value = current TVL."""
    c = _cached("tvl")
    if c is not None:
        return c
    try:
        r = requests.get("https://api.llama.fi/v2/historicalChainTvl", timeout=_TIMEOUT)
        r.raise_for_status()
        series = [float(p["tvl"]) for p in r.json() if p.get("tvl") is not None]
        return _store("tvl", series)
    except Exception as exc:               # noqa: BLE001
        log.warning("crypto_macro: DeFiLlama TVL failed — %s", exc)
        return []


# ── alternative.me: Fear & Greed index ───────────────────────────────────────
def fear_greed(limit: int = 365) -> list[int]:
    """
    Fear & Greed index history (0=extreme fear, 100=extreme greed), newest last.
    """
    key = f"fng_{limit}"
    c = _cached(key)
    if c is not None:
        return c
    try:
        r = requests.get("https://api.alternative.me/fng/",
                         params={"limit": limit, "format": "json"}, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json().get("data", [])
        # API returns newest-first; reverse to chronological for sparklines.
        series = [int(x["value"]) for x in reversed(data) if x.get("value") is not None]
        return _store(key, series)
    except Exception as exc:               # noqa: BLE001
        log.warning("crypto_macro: alternative.me F&G failed — %s", exc)
        return []
