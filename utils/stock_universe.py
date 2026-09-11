"""
Stock Universe Fetcher
Provides broad, institutional-scale stock universes for the scanner.

The default scanner watchlist is ~90 hand-picked large-caps. Institutional
scanners screen the full index. `get_stock_universe("sp500")` pulls the live
S&P 500 constituents (504 names) from a maintained public dataset, cached for
24h, with a hardcoded fallback if the source is unreachable.

Symbols are normalised to yfinance format (class shares: BRK.B → BRK-B).
"""
from __future__ import annotations
import io
import csv
import time
import requests
from utils.logger import get_logger

log = get_logger(__name__)

_SP500_CSV = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
_TTL = 86400  # 24-hour cache — index membership changes rarely
_cache: dict[str, tuple[float, list[str]]] = {}


def _to_yf(sym: str) -> str:
    """Normalise an index symbol to yfinance format (BRK.B → BRK-B)."""
    return sym.strip().upper().replace(".", "-")


def get_sp500() -> list[str]:
    """Return the live S&P 500 constituents (yfinance-formatted), cached 24h."""
    now = time.time()
    if "sp500" in _cache and now - _cache["sp500"][0] < _TTL:
        return _cache["sp500"][1]

    try:
        resp = requests.get(_SP500_CSV, timeout=12)
        resp.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        tickers = [_to_yf(r["Symbol"]) for r in rows if r.get("Symbol")]
        tickers = sorted(set(tickers))
        if len(tickers) >= 400:                       # sanity gate
            _cache["sp500"] = (now, tickers)
            log.info("stock_universe: fetched %d S&P 500 constituents", len(tickers))
            return tickers
        log.warning("stock_universe: S&P 500 fetch returned only %d — using fallback", len(tickers))
    except Exception as exc:
        log.warning("stock_universe: S&P 500 fetch failed (%s) — using fallback", exc)

    from skills.scanner import DEFAULT_STOCK_WATCHLIST
    return DEFAULT_STOCK_WATCHLIST


# ── Curated thematic universes ────────────────────────────────────────────────
# Hand-maintained leader lists. Kept tight (liquid, well-covered names) so a
# themed scan surfaces the highest-quality setups in that theme.

_TOP_AI = [
    # Semis & AI infrastructure
    "NVDA", "AMD", "AVGO", "MU", "ARM", "SMCI", "TSM", "MRVL", "ASML", "ANET",
    "VRT", "DELL", "LRCX", "AMAT", "KLAC",
    # Hyperscalers & AI platforms
    "MSFT", "GOOGL", "GOOG", "META", "AMZN", "ORCL", "IBM", "NOW", "PLTR",
    # AI software / data
    "SNOW", "CRWD", "PANW", "NET", "DDOG", "MDB", "AI", "CRM", "ADBE",
]

_TOP_TECH = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "META", "AMZN", "AVGO", "ORCL",
    "CRM", "AMD", "ADBE", "CSCO", "ACN", "INTC", "QCOM", "TXN", "IBM", "NOW",
    "INTU", "AMAT", "MU", "ADI", "LRCX", "KLAC", "PANW", "SNPS", "CDNS",
    "ANET", "PLTR", "CRWD", "FTNT", "MRVL", "APH", "MSI", "ROP",
]

_TOP_MEGACAP = [
    # Largest, most liquid leaders across all sectors ("top in general")
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "BRK-B", "LLY", "AVGO",
    "TSLA", "JPM", "V", "UNH", "XOM", "MA", "JNJ", "PG", "HD", "COST", "ORCL",
    "ABBV", "WMT", "KO", "BAC", "CVX", "MRK", "PEP", "ADBE", "CRM", "MCD",
    "NFLX", "AMD", "TMO", "ACN", "LIN", "ABT", "WFC", "DIS", "GE", "CAT",
]

_THEMES = {
    "top_ai":   _TOP_AI,
    "top_tech": _TOP_TECH,
    "top":      _TOP_MEGACAP,
}


def get_stock_universe(name: str = "default") -> list[str]:
    """
    Resolve a named stock universe to a ticker list.
      "default"  → the curated ~90-name large-cap watchlist
      "sp500"    → live S&P 500 constituents (~503 names)
      "top_ai"   → AI infrastructure + platform leaders
      "top_tech" → broad technology leaders
      "top"      → top megacap leaders across all sectors
    """
    name = (name or "default").lower().replace("-", "_").replace(" ", "_")
    if name in ("sp500", "s&p500", "sp", "spx"):
        return get_sp500()
    if name in _THEMES:
        return list(dict.fromkeys(_THEMES[name]))   # dedupe, preserve order
    from skills.scanner import DEFAULT_STOCK_WATCHLIST
    return DEFAULT_STOCK_WATCHLIST
