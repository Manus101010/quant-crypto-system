"""
Optional CoinGlass API v4 client: cross-exchange aggregated positioning.

Enabled only when env COINGLASS_API_KEY is set (header CG-API-KEY, base
https://open-api-v4.coinglass.com). Without a key every call returns {} and no
request is made.

Endpoint paths verified against docs.coinglass.com on 2026-10-27:
  /api/futures/funding-rate/oi-weight-history            symbol=BTC, interval, limit
  /api/futures/open-interest/aggregated-history          symbol=BTC, interval, limit, unit
  /api/futures/liquidation/aggregated-history            symbol=BTC, exchange_list, interval
  /api/futures/global-long-short-account-ratio/history   exchange=Binance, symbol=BTCUSDT
  /api/futures/aggregated-taker-buy-sell-volume/history  symbol=BTC, exchange_list, interval

Hobbyist plan ($29/mo): 30 requests/min and history intervals >= 4h only, so
this client asks for 4h bars. Responses are cached CACHE_TTL (30 min) so a scan
of 5 coins costs at most 5 x 5 = 25 calls, then nothing for half an hour.
"""
from __future__ import annotations

import os
from typing import Any

from features._http import cache_get, cache_put, fnum, get_json, pct_rank, split_symbol
from utils.logger import get_logger

log = get_logger(__name__)

BASE = "https://open-api-v4.coinglass.com"
CACHE_TTL = 1800.0
INTERVAL = os.environ.get("COINGLASS_INTERVAL", "4h")    # Hobbyist minimum
_RATE = ("coinglass", (28, 60.0))                         # stay under 30/min
EXCHANGES = "Binance,OKX,Bybit"

FIELDS = ("cg_funding_oiw", "cg_funding_oiw_pct", "cg_oi_usd", "cg_oi_chg_4h",
          "cg_oi_chg_24h", "cg_liq_long_24h", "cg_liq_short_24h", "cg_liq_skew",
          "cg_ls_ratio", "cg_ls_pct", "cg_taker_ratio_24h")


def api_key() -> str:
    return os.environ.get("COINGLASS_API_KEY", "").strip()


def enabled() -> bool:
    return bool(api_key())


def _get(path: str, params: dict) -> list:
    key = api_key()
    if not key:
        return []
    ck = f"cg:{path}:{sorted(params.items())}"
    hit = cache_get(ck, CACHE_TTL)
    if hit is not None:
        return hit
    js = get_json(f"{BASE}{path}", params, headers={"CG-API-KEY": key, "accept": "application/json"},
                  bucket=_RATE[0], rate=_RATE[1], timeout=8)
    if not js or str(js.get("code")) != "0":
        if js:
            log.debug("coinglass %s -> code %s %s", path, js.get("code"), js.get("msg"))
        return []
    data = js.get("data") or []
    cache_put(ck, data)
    return data


def _close_series(rows: list, field: str = "close") -> list[float]:
    """Oldest -> newest values of `field`."""
    rows = sorted(rows, key=lambda r: r.get("time", 0))
    return [v for v in (fnum(r.get(field)) for r in rows) if v is not None]


def get(symbol: str) -> dict[str, Any]:
    """Aggregated features for a coin. {} when disabled; None-filled on errors."""
    if not enabled():
        return {}
    out: dict[str, Any] = {k: None for k in FIELDS}
    try:
        _, core = split_symbol(symbol)
        per_day = max(1, round(24 / _hours(INTERVAL)))

        fr = _close_series(_get("/api/futures/funding-rate/oi-weight-history",
                                {"symbol": core, "interval": INTERVAL, "limit": 180}))
        if fr:
            # CoinGlass returns funding in percent units (0.01 = 0.01%): convert.
            out["cg_funding_oiw"] = fr[-1] / 100.0
            out["cg_funding_oiw_pct"] = pct_rank(fr[-1], fr[-7 * per_day:])

        oi = _close_series(_get("/api/futures/open-interest/aggregated-history",
                                {"symbol": core, "interval": INTERVAL, "limit": 60, "unit": "usd"}))
        if oi:
            out["cg_oi_usd"] = oi[-1]
            if len(oi) > 1 and oi[-2]:
                out["cg_oi_chg_4h"] = round((oi[-1] / oi[-2] - 1) * 100, 3)
            if len(oi) > per_day and oi[-1 - per_day]:
                out["cg_oi_chg_24h"] = round((oi[-1] / oi[-1 - per_day] - 1) * 100, 3)

        lq = _get("/api/futures/liquidation/aggregated-history",
                  {"symbol": core, "exchange_list": EXCHANGES, "interval": INTERVAL,
                   "limit": per_day})
        if lq:
            lg = sum(fnum(r.get("aggregated_long_liquidation_usd")) or 0 for r in lq)
            sh = sum(fnum(r.get("aggregated_short_liquidation_usd")) or 0 for r in lq)
            out["cg_liq_long_24h"], out["cg_liq_short_24h"] = lg, sh
            out["cg_liq_skew"] = round((lg - sh) / (lg + sh), 4) if (lg + sh) else None

        ls = _close_series(_get("/api/futures/global-long-short-account-ratio/history",
                                {"exchange": "Binance", "symbol": f"{core}USDT",
                                 "interval": INTERVAL, "limit": 180}),
                           "global_account_long_short_ratio")
        if ls:
            out["cg_ls_ratio"] = ls[-1]
            out["cg_ls_pct"] = pct_rank(ls[-1], ls)

        tk = _get("/api/futures/aggregated-taker-buy-sell-volume/history",
                  {"symbol": core, "exchange_list": EXCHANGES, "interval": INTERVAL,
                   "limit": per_day})
        if tk:
            b = sum(fnum(r.get("aggregated_buy_volume_usd")) or 0 for r in tk)
            s = sum(fnum(r.get("aggregated_sell_volume_usd")) or 0 for r in tk)
            out["cg_taker_ratio_24h"] = round(b / s, 4) if s else None
    except Exception as exc:                        # noqa: BLE001
        log.debug("coinglass %s failed: %s", symbol, exc)
    return out


def _hours(interval: str) -> float:
    unit, n = interval[-1], float(interval[:-1] or 1)
    return n * {"m": 1 / 60, "h": 1, "d": 24, "w": 168}.get(unit, 1)
