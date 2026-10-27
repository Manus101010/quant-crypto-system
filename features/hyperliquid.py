"""
Hyperliquid public info API (no key, reachable from US hosts): cross-venue
confirmation of funding / OI / premium. One POST returns every perp, so it is
cached for all coins at once.

  POST https://api.hyperliquid.xyz/info {"type": "metaAndAssetCtxs"}
    -> [ {universe:[{name,...}]}, [ {funding, openInterest, markPx, premium,
          dayNtlVlm, prevDayPx, ...}, ... ] ]   (same order)

Hyperliquid funding is paid HOURLY: hl_funding_8h = funding * 8.
Multiplier names use a 'k' prefix (kPEPE = 1000 PEPE).
"""
from __future__ import annotations

from typing import Any

from features._http import _session, cache_get, cache_put, fnum, limiter, split_symbol
from utils.logger import get_logger

log = get_logger(__name__)

URL = "https://api.hyperliquid.xyz/info"
CACHE_TTL = 120.0
FIELDS = ("hl_funding_8h", "hl_oi_usd", "hl_premium", "hl_vol_24h")


def _all() -> dict[str, dict]:
    hit = cache_get("hl:ctx", CACHE_TTL)
    if hit is not None:
        return hit
    out: dict[str, dict] = {}
    try:
        limiter("hyperliquid", 10, 1.0).wait()
        r = _session.post(URL, json={"type": "metaAndAssetCtxs"}, timeout=6)
        if r.status_code == 200:
            meta, ctxs = r.json()
            for a, c in zip(meta.get("universe", []), ctxs):
                if not a.get("isDelisted"):
                    out[a["name"]] = c
    except Exception as exc:                        # noqa: BLE001
        log.debug("hyperliquid failed: %s", exc)
    if out:
        cache_put("hl:ctx", out)
    return out


def get(symbol: str) -> dict[str, Any]:
    out: dict[str, Any] = {k: None for k in FIELDS}
    try:
        _, core = split_symbol(symbol)
        ctx = _all()
        c = ctx.get(core) or ctx.get(f"k{core}")
        if not c:
            return out
        f = fnum(c.get("funding"))
        oi, px = fnum(c.get("openInterest")), fnum(c.get("markPx"))
        out["hl_funding_8h"] = None if f is None else f * 8
        out["hl_oi_usd"] = oi * px if (oi is not None and px is not None) else None
        out["hl_premium"] = fnum(c.get("premium"))
        out["hl_vol_24h"] = fnum(c.get("dayNtlVlm"))
    except Exception as exc:                        # noqa: BLE001
        log.debug("hyperliquid %s failed: %s", symbol, exc)
    return out
