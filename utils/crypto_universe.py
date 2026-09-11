"""
Crypto Universe Fetcher
Pulls live top-N coins by market cap from CoinGecko's free public API.
Filters out stablecoins, wrapped tokens, and assets with no meaningful
price discovery so the scanner only sees tradeable cryptocurrencies.

No API key required. Rate limit: ~30 calls/min on the free tier.
Results are cached in-memory for 1 hour to avoid repeated calls.
"""
from __future__ import annotations
import time
import requests
from utils.logger import get_logger

log = get_logger(__name__)

_BASE     = "https://api.coingecko.com/api/v3/coins/markets"
_PER_PAGE = 250          # CoinGecko free-tier max per page → top-500 = 2 requests, not 5
_PAGE_PAUSE_S = 2.5      # spacing between pages to respect ~30 calls/min free limit
_MAX_RETRIES  = 3        # retries on HTTP 429 (rate limit) before giving up on a page
_PARAMS = {
    "vs_currency": "usd",
    "order":       "market_cap_desc",
    "sparkline":   "false",
    "locale":      "en",
}

# Known stablecoins, wrapped tokens, and non-tradeable assets to skip.
# CoinGecko returns these highly ranked by "market cap" but they have no
# directional price movement worth scanning.
_BLOCKLIST = {
    # Fiat-pegged stablecoins (USD)
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "GUSD", "LUSD",
    "SUSD", "USDN", "USDD", "FDUSD", "PYUSD", "CRVUSD", "FRAX",
    "OUSD", "USDS", "USD0", "USD1", "M0", "USDX", "USDE", "USDF", "RLUSD", "USDB",
    # Fiat-pegged stablecoins (EUR / other)
    "EURC", "EURS", "EURT", "AGEUR", "XSGD", "XIDR",
    # Yield-bearing / RWA stablecoins
    "OUSG", "YLDS", "TBILL", "BUIDL",
    # Wrapped / synthetic versions of other assets
    "WBTC", "WETH", "WBNB", "WMATIC", "WAVAX", "WSOL", "WTRX",
    "RENBTC", "HBTC", "BTCB",
    # Liquid staking tokens (track underlying price, not independent)
    "STETH", "RETH", "CBETH", "FRXETH", "SFRXETH", "WSTETH",
    "ANKRBNB", "RBNB", "BSOL", "METH", "EETH",
    # Exchange / platform tokens with very limited yfinance coverage
    "OKB", "LEO",
    # Misc tokens that appear in CoinGecko top 200 but lack clean yfinance data
    "FIGR_HELOC", "A7A5", "RAIN",
}

_cache: dict[int, tuple[float, list[str]]] = {}   # {n: (timestamp, tickers)}
_TTL = 3600  # 1-hour cache


def _fetch_page(page: int) -> list[dict] | None:
    """
    Fetch one CoinGecko markets page (250 coins). Retries on HTTP 429 with
    exponential backoff (honouring Retry-After when present). Returns the JSON
    list, an empty list for end-of-data, or None if the page ultimately failed.
    """
    params = {**_PARAMS, "page": page, "per_page": _PER_PAGE}
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(_BASE, params=params, timeout=12)
            if resp.status_code == 429:
                wait = float(resp.headers.get("retry-after", 0)) or (2.0 * (attempt + 1) + _PAGE_PAUSE_S)
                log.warning("crypto_universe: page %d rate-limited (429) — retry in %.0fs (%d/%d)",
                            page, wait, attempt + 1, _MAX_RETRIES)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            log.warning("crypto_universe: page %d attempt %d failed — %s", page, attempt + 1, exc)
            time.sleep(2.0 * (attempt + 1))
    return None


def get_top_crypto(n: int = 100) -> list[str]:
    """
    Return up to n yfinance-formatted crypto tickers (e.g. ["BTC-USD", ...])
    sorted by market cap, with stablecoins and wrapped tokens removed.

    Args:
        n: Number of coins to fetch (50–500). Clamped to 500.
    """
    n = min(max(n, 10), 500)
    now = time.time()

    if n in _cache and now - _cache[n][0] < _TTL:
        log.debug("crypto_universe: cache hit for top-%d", n)
        return _cache[n][1]

    tickers: list[str] = []
    # Over-fetch a bit (blocklist removes ~5-10%) so we still reach n tradeable coins.
    target_rows = int(n * 1.15)
    pages = (target_rows // _PER_PAGE) + (1 if target_rows % _PER_PAGE else 0)

    for page in range(1, pages + 1):
        coins = _fetch_page(page)
        if coins is None:        # page failed after retries — keep what we have
            log.warning("crypto_universe: stopping at page %d (got %d tickers so far)",
                        page, len(tickers))
            break
        if not coins:            # empty page — end of list
            break
        for coin in coins:
            sym = coin.get("symbol", "").upper()
            if sym and sym not in _BLOCKLIST:
                tickers.append(f"{sym}-USD")
            if len(tickers) >= n:
                break
        if len(tickers) >= n:
            break
        if page < pages:
            time.sleep(_PAGE_PAUSE_S)   # space out requests to avoid 429

    if tickers:
        _cache[n] = (now, tickers)
        log.info("crypto_universe: fetched %d tickers (requested %d)", len(tickers), n)
    else:
        # Fallback to a hardcoded top-30 if CoinGecko is unreachable
        log.warning("crypto_universe: CoinGecko unavailable — using hardcoded fallback list")
        tickers = [
            "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
            "ADA-USD", "AVAX-USD", "DOT-USD", "MATIC-USD", "LINK-USD",
            "UNI-USD", "ATOM-USD", "LTC-USD", "BCH-USD", "DOGE-USD",
            "SHIB-USD", "FTM-USD", "NEAR-USD", "ALGO-USD", "XLM-USD",
            "VET-USD", "MANA-USD", "SAND-USD", "CRO-USD", "HBAR-USD",
            "ICP-USD", "XTZ-USD", "APE-USD", "AXS-USD", "EGLD-USD",
        ]

    return tickers
