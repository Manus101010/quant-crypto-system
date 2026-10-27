"""
DEX Screener (free, no key): on-chain spot activity for coins that also list as
Bybit perps. Used for small-cap hype detection: is DEX volume expanding, are
on-chain buyers outnumbering sellers, is the token being paid-boosted?

Routes (docs.dexscreener.com):
  GET /latest/dex/search?q=SYM            up to 30 pairs, 300 req/min
  GET /token-boosts/latest/v1             latest paid boosts, 60 req/min
  GET /token-boosts/top/v1                most boosted tokens, 60 req/min
  GET /token-profiles/latest/v1           latest token profiles, 60 req/min

Symbol search is full of impostor tokens (a meme called "BTC" on Solana, ten
fake PEPEs). A pair only counts when its base symbol matches exactly AND its USD
price is within PRICE_TOL of the perp's reference price (the caller passes the
OKX/MEXC price of the core coin). Without a reference price only pairs with
>= $50k liquidity are used and `dex_price_checked` is 0.

`get(symbol, ref_price)` returns flat floats (None when no matching pair) and
never raises.
"""
from __future__ import annotations

import time
from typing import Any

from features._http import cache_get, cache_put, fnum, get_json, split_symbol
from utils.logger import get_logger

log = get_logger(__name__)

BASE = "https://api.dexscreener.com"
CACHE_TTL = 300.0
BOOST_TTL = 600.0
PRICE_TOL = 0.15
MIN_LIQ_UNCHECKED = 50_000.0
_SEARCH_RATE = ("dex_search", (250, 60.0))
_BOOST_RATE = ("dex_boost", (50, 60.0))

FIELDS = ("dex_pairs", "dex_liq_usd", "dex_vol_h1", "dex_vol_h6", "dex_vol_h24",
          "dex_vol_exp_1h", "dex_vol_exp_6h", "dex_buys_h1", "dex_sells_h1",
          "dex_buy_ratio_h1", "dex_buy_ratio_h6", "dex_buy_ratio_h24",
          "dex_chg_h1", "dex_chg_h24", "dex_age_days", "dex_boosted",
          "dex_price_checked")


def _boosted_addresses() -> set[str]:
    """Token addresses (lower-case) currently in the latest/top boost lists."""
    hit = cache_get("dex:boosts", BOOST_TTL)
    if hit is not None:
        return hit
    addrs: set[str] = set()
    for path in ("/token-boosts/latest/v1", "/token-boosts/top/v1"):
        js = get_json(f"{BASE}{path}", bucket=_BOOST_RATE[0], rate=_BOOST_RATE[1])
        if isinstance(js, list):
            addrs |= {str(d.get("tokenAddress", "")).lower() for d in js if d.get("tokenAddress")}
    cache_put("dex:boosts", addrs)
    return addrs


def latest_boosts(limit: int = 30) -> list[dict]:
    """Latest boosted tokens (chain, address, amount) for a hype watch list."""
    js = get_json(f"{BASE}/token-boosts/latest/v1", bucket=_BOOST_RATE[0], rate=_BOOST_RATE[1])
    if not isinstance(js, list):
        return []
    return [{"chain": d.get("chainId"), "address": d.get("tokenAddress"),
             "amount": fnum(d.get("amount")), "total": fnum(d.get("totalAmount")),
             "url": d.get("url")} for d in js[:limit]]


def latest_profiles(limit: int = 30) -> list[dict]:
    js = get_json(f"{BASE}/token-profiles/latest/v1", bucket=_BOOST_RATE[0], rate=_BOOST_RATE[1])
    if not isinstance(js, list):
        return []
    return [{"chain": d.get("chainId"), "address": d.get("tokenAddress"), "url": d.get("url")}
            for d in js[:limit]]


def search_pairs(query: str) -> list[dict]:
    hit = cache_get(f"dex:search:{query}", CACHE_TTL)
    if hit is not None:
        return hit
    js = get_json(f"{BASE}/latest/dex/search", {"q": query},
                  bucket=_SEARCH_RATE[0], rate=_SEARCH_RATE[1])
    pairs = (js or {}).get("pairs") or []
    cache_put(f"dex:search:{query}", pairs)
    return pairs


def match_pairs(pairs: list[dict], core: str, ref_price: float | None) -> tuple[list[dict], bool]:
    """Pairs whose base token IS this coin. Returns (pairs, price_checked)."""
    want = {core.upper(), f"W{core.upper()}"}            # WETH-style wrappers count
    out = []
    for p in pairs:
        sym = str((p.get("baseToken") or {}).get("symbol", "")).upper()
        if sym not in want:
            continue
        px = fnum(p.get("priceUsd"))
        liq = fnum((p.get("liquidity") or {}).get("usd")) or 0.0
        if ref_price:
            if not px or abs(px / ref_price - 1) > PRICE_TOL:
                continue
        elif liq < MIN_LIQ_UNCHECKED:
            continue
        out.append(p)
    return out, bool(ref_price)


def _ratio(b: float, s: float) -> float | None:
    return round(b / (b + s), 4) if (b + s) > 0 else None


def features_from_pairs(pairs: list[dict], price_checked: bool,
                        boosted: set[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {k: None for k in FIELDS}
    out["dex_pairs"] = float(len(pairs))
    out["dex_price_checked"] = 1.0 if price_checked else 0.0
    if not pairs:
        return out

    def vol(p, k):
        return fnum((p.get("volume") or {}).get(k)) or 0.0

    def tx(p, k, side):
        return fnum(((p.get("txns") or {}).get(k) or {}).get(side)) or 0.0

    v1 = sum(vol(p, "h1") for p in pairs)
    v6 = sum(vol(p, "h6") for p in pairs)
    v24 = sum(vol(p, "h24") for p in pairs)
    out["dex_liq_usd"] = sum(fnum((p.get("liquidity") or {}).get("usd")) or 0.0 for p in pairs)
    out["dex_vol_h1"], out["dex_vol_h6"], out["dex_vol_h24"] = v1, v6, v24
    # Expansion: last hour vs the 24h hourly average (1.0 = normal pace).
    out["dex_vol_exp_1h"] = round(v1 / (v24 / 24), 3) if v24 > 0 else None
    out["dex_vol_exp_6h"] = round((v6 / 6) / (v24 / 24), 3) if v24 > 0 else None
    for k in ("h1", "h6", "h24"):
        b = sum(tx(p, k, "buys") for p in pairs)
        s = sum(tx(p, k, "sells") for p in pairs)
        out[f"dex_buy_ratio_{k}"] = _ratio(b, s)
        if k == "h1":
            out["dex_buys_h1"], out["dex_sells_h1"] = b, s
    top = max(pairs, key=lambda p: fnum((p.get("liquidity") or {}).get("usd")) or 0.0)
    pc = top.get("priceChange") or {}
    out["dex_chg_h1"], out["dex_chg_h24"] = fnum(pc.get("h1")), fnum(pc.get("h24"))
    created = [fnum(p.get("pairCreatedAt")) for p in pairs if fnum(p.get("pairCreatedAt"))]
    if created:
        out["dex_age_days"] = round((time.time() * 1000 - min(created)) / 86_400_000, 1)
    active_boost = any(fnum((p.get("boosts") or {}).get("active")) for p in pairs)
    if boosted:
        active_boost = active_boost or any(
            str((p.get("baseToken") or {}).get("address", "")).lower() in boosted for p in pairs)
    out["dex_boosted"] = 1.0 if active_boost else 0.0
    return out


def get(symbol: str, ref_price: float | None = None, *, check_boosts: bool = True) -> dict:
    """DEX features for a perp symbol. ref_price = USD price of ONE core coin
    (for 1000PEPE pass the PEPE price, not the 1000PEPE contract price)."""
    try:
        _, core = split_symbol(symbol)
        key = f"dex:{core}:{round(ref_price, 12) if ref_price else None}"
        hit = cache_get(key, CACHE_TTL)
        if hit is not None:
            return dict(hit)
        pairs, checked = match_pairs(search_pairs(core), core, ref_price)
        boosted = _boosted_addresses() if (check_boosts and pairs) else None
        out = features_from_pairs(pairs, checked, boosted)
        cache_put(key, dict(out))
        return out
    except Exception as exc:                        # noqa: BLE001
        log.debug("dex %s failed: %s", symbol, exc)
        return {k: None for k in FIELDS}
