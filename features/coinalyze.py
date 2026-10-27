"""
Coinalyze (free, key required): PRIMARY derivatives source for signal features.

Env COINALYZE_API_KEY (free signup at coinalyze.net). Without a key every call
returns {} and no request is made; features/derivs.py (OKX/MEXC/Bybit public)
then supplies the same canonical fields.

API facts, from the OpenAPI spec embedded at https://api.coinalyze.net/v1/doc/
(parsed 2026-10-27):
  base https://api.coinalyze.net/v1, key in header or query `api_key`
  40 calls/min per key; 429 + Retry-After. Each symbol in a multi-symbol call
  (max 20) counts as one call.
  Intraday history (1min..12hour) keeps only 1,500-2,000 points; daily forever.
  All history ascending. from/to are UNIX seconds.
  GET /future-markets               symbol, exchange, symbol_on_exchange, base_asset,
                                    is_perpetual, has_long_short_ratio_data, has_buy_sell_data
  GET /funding-rate?symbols=        [{symbol, value, update}]
  GET /predicted-funding-rate?symbols=
  GET /open-interest-history?symbols=&interval=&from=&to=&convert_to_usd=
                                    [{symbol, history:[{t,o,h,l,c}]}]
  GET /funding-rate-history         same shape (rate OHLC per bar)
  GET /liquidation-history          history:[{t, l (longs), s (shorts)}]
  GET /long-short-ratio-history     history:[{t, r (ratio), l (% long), s (% short)}]
  GET /ohlcv-history                history:[{t,o,h,l,c,v,bv (buy vol),tx,btx}]

Market symbols carry an exchange code suffix (BTCUSDT_PERP.A = Binance). The
codes are resolved at runtime from /future-markets by exchange name, so the
Bybit market for a coin is whatever Coinalyze lists with exchange "Bybit" and
symbol_on_exchange "<BASE>USDT" (1000PEPE stays 1000PEPEUSDT, as on Bybit).

Per snapshot: ~10 calls (Bybit funding, predicted funding, funding history,
L/S history, OHLCV, OI history and liquidations for Bybit + Binance). With the
38/min limiter and a 5 min cache that is 4 fresh coins per minute; a scan arms
at most 5, so fine.
"""
from __future__ import annotations

import os
import time
from typing import Any

from features._http import cache_get, cache_put, fnum, get_json, pct_rank, split_symbol
from utils.logger import get_logger

log = get_logger(__name__)

BASE = "https://api.coinalyze.net/v1"
CACHE_TTL = 300.0
MARKETS_TTL = 24 * 3600.0
_RATE = ("coinalyze", (38, 60.0))
PRIMARY_EXCHANGE = "Bybit"
AGG_EXCHANGES = ("Bybit", "Binance")          # OI + liquidations summed across these

# Canonical (shared with derivs.py) + Coinalyze-only extras.
FIELDS = (
    "funding_rate", "funding_8h", "funding_interval_h", "funding_pct_7d", "funding_pct_30d",
    "funding_avg_7d_8h", "oi_usd", "oi_chg_1h", "oi_chg_4h", "oi_chg_24h",
    "ls_ratio", "ls_pct_4d", "ls_chg_24h", "taker_ratio_1h", "taker_ratio_24h",
    "pred_funding_8h", "liq_long_24h", "liq_short_24h", "liq_skew_24h", "liq_long_1h",
    "liq_short_1h", "oi_usd_agg", "oi_chg_24h_agg",
)


def api_key() -> str:
    return os.environ.get("COINALYZE_API_KEY", "").strip()


def enabled() -> bool:
    return bool(api_key())


def _get(path: str, params: dict | None = None) -> Any:
    k = api_key()
    if not k:
        return None
    return get_json(f"{BASE}{path}", params, headers={"api_key": k},
                    bucket=_RATE[0], rate=_RATE[1], timeout=8)


def markets() -> list[dict]:
    hit = cache_get("cz:markets", MARKETS_TTL)
    if hit is not None:
        return hit
    js = _get("/future-markets")
    rows = js if isinstance(js, list) else []
    if rows:
        cache_put("cz:markets", rows)
    return rows


def resolve(base: str, exchange: str = PRIMARY_EXCHANGE,
            mkts: list[dict] | None = None) -> dict | None:
    """The USDT perpetual market for `base` (Bybit spelling, e.g. 1000PEPE) on
    `exchange`, or None. Falls back to the unprefixed core coin."""
    mkts = mkts if mkts is not None else markets()
    _, core = split_symbol(base)
    want = [f"{base}USDT", f"{core}USDT", f"1000{core}USDT"]
    best = None
    for m in mkts:
        if str(m.get("exchange", "")).lower() != exchange.lower() or not m.get("is_perpetual"):
            continue
        if str(m.get("quote_asset", "USDT")).upper() not in ("USDT", ""):
            continue
        soe = str(m.get("symbol_on_exchange", "")).upper().replace("-", "").replace("_", "")
        if soe in want:
            rank = want.index(soe)
            if best is None or rank < best[0]:
                best = (rank, m)
    return best[1] if best else None


def _hist(path: str, symbols: list[str], interval: str, hours: float, **extra) -> dict[str, list]:
    now = int(time.time())
    js = _get(path, {"symbols": ",".join(symbols), "interval": interval,
                     "from": now - int(hours * 3600), "to": now, **extra})
    out: dict[str, list] = {}
    for row in js if isinstance(js, list) else []:
        out[row.get("symbol")] = row.get("history") or []
    return out


def _chg_series(vals: list[float], back: int) -> float | None:
    if len(vals) <= back or not vals[-1 - back]:
        return None
    return round((vals[-1] / vals[-1 - back] - 1) * 100, 3)


def funding_scale(values: list[float]) -> float:
    """Multiplier that turns Coinalyze funding values into a fraction.
    The spec does not say whether values are percent (0.01 = 0.01%) or a
    fraction (0.0001). Untested without a key, so detect it: across a history
    window the median |rate| of a USDT perp is ~0.0001 as a fraction and ~0.01
    as percent; anything above 0.002 is read as percent."""
    vals = sorted(abs(v) for v in values if v is not None)
    if not vals:
        return 1.0
    med = vals[len(vals) // 2]
    return 0.01 if med > 0.002 else 1.0


def features(base: str, mkts: list[dict] | None = None) -> dict[str, Any]:
    """Coinalyze features for one Bybit base (e.g. 'SOL', '1000PEPE')."""
    out: dict[str, Any] = {k: None for k in FIELDS}
    mkts = mkts if mkts is not None else markets()
    m = resolve(base, PRIMARY_EXCHANGE, mkts)
    if not m:
        return out
    sym = m["symbol"]
    agg = [x["symbol"] for x in (resolve(base, ex, mkts) for ex in AGG_EXCHANGES) if x]
    agg = list(dict.fromkeys([sym] + agg))

    # Funding: current, predicted, 30d history (1hour bars -> ~720 points).
    fr = _get("/funding-rate", {"symbols": sym})
    cur = fnum(fr[0].get("value")) if isinstance(fr, list) and fr else None
    pf = _get("/predicted-funding-rate", {"symbols": sym})
    pred = fnum(pf[0].get("value")) if isinstance(pf, list) and pf else None
    fh = _hist("/funding-rate-history", [sym], "1hour", 30 * 24).get(sym, [])
    closes = [fnum(b.get("c")) for b in fh]
    closes = [c for c in closes if c is not None]
    scale = funding_scale(closes + ([cur] if cur is not None else []))
    # Coinalyze does not expose the funding interval. Bybit runs some small caps
    # on 1h/4h funding: funding_8h here assumes 8h and funding_interval_h stays
    # None (snapshot.py then takes the interval from OKX when it has one).
    ih = 8.0
    if cur is not None:
        out["funding_rate"] = cur * scale
        out["funding_8h"] = cur * scale
    if pred is not None:
        out["pred_funding_8h"] = pred * scale * 8.0 / ih
    if closes:
        ref = cur if cur is not None else closes[-1]
        out["funding_pct_7d"] = pct_rank(ref, closes[-7 * 24:])
        out["funding_pct_30d"] = pct_rank(ref, closes)
        w = closes[-7 * 24:]
        out["funding_avg_7d_8h"] = sum(w) / len(w) * scale * 8.0 / ih

    # Open interest, hourly, ~2 days. Changes use the primary market in its
    # native units (coins for USDT perps) so a price move alone is not read as
    # new positioning; the level and the cross-venue aggregate are in USD.
    oi_n = _hist("/open-interest-history", [sym], "1hour", 48, convert_to_usd="false")
    p = [fnum(b.get("c")) for b in oi_n.get(sym, [])]
    p = [v for v in p if v is not None]
    if p:
        out["oi_chg_1h"] = _chg_series(p, 1)
        out["oi_chg_4h"] = _chg_series(p, 4)
        out["oi_chg_24h"] = _chg_series(p, 24)
    oi = _hist("/open-interest-history", agg, "1hour", 48, convert_to_usd="true")
    pu = [fnum(b.get("c")) for b in oi.get(sym, [])]
    pu = [v for v in pu if v is not None]
    if pu:
        out["oi_usd"] = pu[-1]
    series = [[fnum(b.get("c")) or 0.0 for b in oi.get(s, [])] for s in agg if oi.get(s)]
    if series:
        n = min(len(s) for s in series)
        tot = [sum(s[-n + i] for s in series) for i in range(n)]
        out["oi_usd_agg"] = tot[-1] if tot else None
        out["oi_chg_24h_agg"] = _chg_series(tot, 24)

    # Liquidations (USD), hourly, last 24h, summed across agg markets.
    lq = _hist("/liquidation-history", agg, "1hour", 25, convert_to_usd="true")
    lg = sh = lg1 = sh1 = 0.0
    have = False
    for s in agg:
        bars = lq.get(s) or []
        if not bars:
            continue
        have = True
        last24 = bars[-24:]
        lg += sum(fnum(b.get("l")) or 0 for b in last24)
        sh += sum(fnum(b.get("s")) or 0 for b in last24)
        lg1 += fnum(bars[-1].get("l")) or 0
        sh1 += fnum(bars[-1].get("s")) or 0
    if have:
        out["liq_long_24h"], out["liq_short_24h"] = lg, sh
        out["liq_long_1h"], out["liq_short_1h"] = lg1, sh1
        out["liq_skew_24h"] = round((lg - sh) / (lg + sh), 4) if (lg + sh) else 0.0

    # Long/short account ratio, hourly ~4 days (Bybit market).
    if m.get("has_long_short_ratio_data", True):
        ls = _hist("/long-short-ratio-history", [sym], "1hour", 96).get(sym, [])
        r = [fnum(b.get("r")) for b in ls]
        r = [v for v in r if v is not None]
        if r:
            out["ls_ratio"] = r[-1]
            out["ls_pct_4d"] = pct_rank(r[-1], r)
            out["ls_chg_24h"] = _chg_series(r, 24)

    # Taker flow from OHLCV buy volume (sell = v - bv). Last bar is forming: skip it.
    if m.get("has_buy_sell_data", True):
        ov = _hist("/ohlcv-history", [sym], "1hour", 26).get(sym, [])
        done = ov[:-1] if len(ov) > 1 else []
        if done:
            def ratio(bars):
                v = sum(fnum(b.get("v")) or 0 for b in bars)
                bv = sum(fnum(b.get("bv")) or 0 for b in bars)
                sv = v - bv
                return round(bv / sv, 4) if sv > 0 else None
            out["taker_ratio_1h"] = ratio(done[-1:])
            out["taker_ratio_24h"] = ratio(done[-24:])
    return out


def get(symbol: str) -> dict[str, Any]:
    """{} when no key. Otherwise FIELDS (None where unavailable). Never raises."""
    if not enabled():
        return {}
    base, _ = split_symbol(symbol)
    key = f"cz:{base}"
    hit = cache_get(key, CACHE_TTL)
    if hit is not None:
        return dict(hit)
    try:
        out = features(base)
    except Exception as exc:                        # noqa: BLE001
        log.debug("coinalyze %s failed: %s", symbol, exc)
        out = {k: None for k in FIELDS}
    cache_put(key, dict(out))
    return out
