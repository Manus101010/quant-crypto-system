"""
Whale Alert: large on-chain transfers to / from exchanges for one coin.

Disabled (returns {} and makes no request) unless env WHALE_ALERT_API_KEY is set.

API state, checked against developer.whale-alert.io on 2026-10-27:
  * The old REST v1 (api.whale-alert.io/v1/transactions) is gone (404).
  * REST now lives at https://leviathan.whale-alert.io (key as ?api_key=):
      GET /status                                   chains + symbols, no key
      GET /{blockchain}/height_at_time/{unix_ts}    block height at a time
      GET /{blockchain}/transactions?start_height=&symbol=&limit=&order=
    Those REST endpoints need the Enterprise plan ($699/mo, 90 days history).
  * The personal plan is the Alerts API (WebSocket wss://.../ws?api_key=,
    $29.95/mo at time of writing, min alert value $100k, 100 alerts/h). It is
    a stream, not a query: it would need a long-running listener that appends
    alerts to the DB. `summarise_alerts()` below takes that alert schema so a
    listener (or the free alert archive at whale-alert.io/whale-alerts-archive.json.gzip)
    can feed the same features.

Features (USD over the last `hours`):
  whale_to_exch_usd    sum sent INTO exchanges (potential sell supply)
  whale_from_exch_usd  sum withdrawn FROM exchanges
  whale_netflow_usd    to - from (positive = net inflow to exchanges = bearish lean)
  whale_n              number of qualifying transfers
"""
from __future__ import annotations

import os
import time
from typing import Any, Iterable

from features._http import cache_get, cache_put, fnum, get_json, split_symbol
from utils.logger import get_logger

log = get_logger(__name__)

BASE = "https://leviathan.whale-alert.io"
CACHE_TTL = 600.0
MIN_USD = 500_000.0
_RATE = ("whale", (20, 60.0))
FIELDS = ("whale_to_exch_usd", "whale_from_exch_usd", "whale_netflow_usd", "whale_n")

# Owner names that are exchanges when only the alert's from/to string is known.
KNOWN_EXCHANGES = {
    "binance", "coinbase", "kraken", "okx", "okex", "bybit", "bitfinex", "huobi", "htx",
    "kucoin", "gate.io", "gate", "bitstamp", "gemini", "mexc", "bitget", "crypto.com",
    "upbit", "bithumb", "poloniex", "bittrex", "deribit", "robinhood", "bitmex",
}

# Where to look for a symbol's transfers (native chain first, then ERC-20).
_CHAIN_FOR = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple",
              "DOGE": "dogecoin", "TRX": "tron", "LTC": "litecoin", "BCH": "bitcoin_cash",
              "ADA": "cardano", "ALGO": "algorand", "HYPE": "hyperliquid", "POL": "polygon",
              "MATIC": "polygon"}


def api_key() -> str:
    return os.environ.get("WHALE_ALERT_API_KEY", "").strip()


def enabled() -> bool:
    return bool(api_key())


def supported() -> dict[str, set[str]]:
    """{blockchain: {SYMBOL,...}} from the keyless /status route (cached 6h)."""
    hit = cache_get("whale:status", 6 * 3600)
    if hit is not None:
        return hit
    js = get_json(f"{BASE}/status", bucket=_RATE[0], rate=_RATE[1])
    out = {c["name"]: {s.upper() for s in c.get("symbols", [])}
           for c in (js or []) if isinstance(c, dict) and c.get("name")}
    if out:
        cache_put("whale:status", out)
    return out


def _is_exchange(owner: str | None, owner_type: str | None = None) -> bool:
    if owner_type:
        return owner_type.lower() == "exchange"
    return bool(owner) and owner.lower().split(" ")[0] in KNOWN_EXCHANGES


def summarise_alerts(alerts: Iterable[dict], symbol: str, hours: float = 24,
                     now: float | None = None, min_usd: float = MIN_USD) -> dict[str, Any]:
    """Features from Alerts-API / archive records ({timestamp, from, to, amounts:[{symbol,value_usd}]})."""
    _, core = split_symbol(symbol)
    now = now or time.time()
    to_x = from_x = 0.0
    n = 0
    for a in alerts:
        if now - (fnum(a.get("timestamp")) or 0) > hours * 3600:
            continue
        usd = sum(fnum(m.get("value_usd")) or 0 for m in a.get("amounts") or []
                  if str(m.get("symbol", "")).upper() == core)
        if usd < min_usd:
            continue
        src_x, dst_x = _is_exchange(a.get("from")), _is_exchange(a.get("to"))
        if dst_x and not src_x:
            to_x += usd; n += 1
        elif src_x and not dst_x:
            from_x += usd; n += 1
    return {"whale_to_exch_usd": to_x, "whale_from_exch_usd": from_x,
            "whale_netflow_usd": to_x - from_x, "whale_n": float(n)}


def summarise_transactions(txs: Iterable[dict], symbol: str, min_usd: float = MIN_USD) -> dict:
    """Features from Enterprise REST transaction records (sub_transactions with
    inputs/outputs carrying owner and owner_type)."""
    _, core = split_symbol(symbol)
    to_x = from_x = 0.0
    n = 0
    for tx in txs:
        for st in tx.get("sub_transactions") or []:
            if str(st.get("symbol", "")).upper() != core:
                continue
            px = fnum(st.get("unit_price_usd")) or 0.0
            ins, outs = st.get("inputs") or [], st.get("outputs") or []
            src_x = any(_is_exchange(a.get("owner"), a.get("owner_type")) for a in ins)
            dst = [a for a in outs if _is_exchange(a.get("owner"), a.get("owner_type"))]
            non = [a for a in outs if not _is_exchange(a.get("owner"), a.get("owner_type"))]
            if dst and not src_x:
                usd = sum(abs(fnum(a.get("amount")) or 0) for a in dst) * px
                if usd >= min_usd:
                    to_x += usd; n += 1
            elif src_x and non:
                usd = sum(abs(fnum(a.get("amount")) or 0) for a in non) * px
                if usd >= min_usd:
                    from_x += usd; n += 1
    return {"whale_to_exch_usd": to_x, "whale_from_exch_usd": from_x,
            "whale_netflow_usd": to_x - from_x, "whale_n": float(n)}


def get(symbol: str, hours: float = 24, min_usd: float = MIN_USD, max_pages: int = 5) -> dict:
    """Exchange flow features via the Enterprise REST API. {} when no key;
    None-filled when the key lacks REST access (e.g. an Alerts-only plan)."""
    if not enabled():
        return {}
    _, core = split_symbol(symbol)
    key = f"whale:{core}:{hours}:{min_usd}"
    hit = cache_get(key, CACHE_TTL)
    if hit is not None:
        return dict(hit)
    out: dict[str, Any] = {k: None for k in FIELDS}
    try:
        sup = supported()
        chain = _CHAIN_FOR.get(core)
        if not chain or core not in sup.get(chain, set()):
            chain = "ethereum" if core in sup.get("ethereum", set()) else None
        if not chain:
            cache_put(key, dict(out))
            return out
        k = api_key()
        h = get_json(f"{BASE}/{chain}/height_at_time/{int(time.time() - hours * 3600)}",
                     {"api_key": k}, bucket=_RATE[0], rate=_RATE[1])
        start = (h or {}).get("height")
        if not start:
            cache_put(key, dict(out))
            return out
        txs: list[dict] = []
        url, params = f"{BASE}/{chain}/transactions", {"api_key": k, "start_height": start,
                                                        "symbol": core.lower(), "limit": 256}
        for _ in range(max_pages):
            js = get_json(url, params, bucket=_RATE[0], rate=_RATE[1], timeout=10)
            if not js:
                break
            batch = js.get("transactions") if isinstance(js, dict) else js
            txs += batch or []
            nxt = js.get("next") if isinstance(js, dict) else None
            if not nxt or not batch:
                break
            url, params = nxt, ({"api_key": k} if "api_key=" not in nxt else None)
        if txs:
            out = summarise_transactions(txs, symbol, min_usd)
    except Exception as exc:                        # noqa: BLE001
        log.debug("whales %s failed: %s", symbol, exc)
    cache_put(key, dict(out))
    return out
