"""
Free public derivatives positioning for one coin: funding, open interest,
long/short account ratio and taker buy/sell flow.

Sources, filled field by field in this order (a later source only fills what an
earlier one left as None):

  1. OKX public v5 (reachable from US hosts, no key)
       /api/v5/public/funding-rate                          current funding + interval
       /api/v5/public/funding-rate-history                  ~100 settled rates (~33d at 8h)
       /api/v5/rubik/stat/contracts/open-interest-history   OI per hour (last 100h), per coin pair
       /api/v5/rubik/stat/contracts/long-short-account-ratio-contract   L/S accounts per hour
       /api/v5/rubik/stat/taker-volume-contract             taker sell/buy per hour
  2. MEXC contract API (reachable, no key): current funding, funding history,
     current open interest (holdVol). No OI history, no L/S, no taker split.
  3. Bybit public v5 (the venue actually traded; 403 from US hosts, so the host
     is remembered as blocked for an hour after the first refusal).

All values are unitless or % so a Bybit 1000PEPE maps cleanly to OKX PEPE.
Rates are kept per interval AND normalised to an 8h equivalent (`funding_8h`)
because OKX/Bybit run some coins on 1h/4h funding.

`get(symbol)` returns a flat dict of floats (None when unavailable) and never
raises. Results are cached for CACHE_TTL seconds.
"""
from __future__ import annotations

import time
from typing import Any

from features._http import cache_get, cache_put, fnum, get_json, pct_rank, split_symbol
from utils.logger import get_logger

log = get_logger(__name__)

CACHE_TTL = 300.0                       # 5 min; hourly stats update once an hour anyway
OKX = "https://www.okx.com"
MEXC = "https://contract.mexc.com"
BYBIT = "https://api.bybit.com"
# OKX: rubik stats 5 req / 2 s per IP, public 20 / 2 s. Stay well under.
_OKX_RUBIK = ("okx_rubik", (4, 2.0))
_OKX_PUB = ("okx_pub", (8, 2.0))
_MEXC_RATE = ("mexc", (10, 2.0))
_BYBIT_RATE = ("bybit", (10, 1.0))

FIELDS = (
    "funding_rate", "funding_8h", "funding_interval_h", "funding_pct_7d", "funding_pct_30d",
    "funding_avg_7d_8h", "oi_usd", "oi_chg_1h", "oi_chg_4h", "oi_chg_24h",
    "ls_ratio", "ls_pct_4d", "ls_chg_24h", "taker_ratio_1h", "taker_ratio_24h",
)


def _empty() -> dict[str, Any]:
    return {k: None for k in FIELDS}


# ── OKX ─────────────────────────────────────────────────────────────────────
def okx_instruments() -> set[str]:
    """Live OKX USDT swap instIds (cached 6h)."""
    hit = cache_get("okx:inst", 6 * 3600)
    if hit is not None:
        return hit
    js = get_json(f"{OKX}/api/v5/public/instruments", {"instType": "SWAP"},
                  bucket=_OKX_PUB[0], rate=_OKX_PUB[1], timeout=10)
    ids = {d["instId"] for d in (js or {}).get("data", [])
           if d.get("instId", "").endswith("-USDT-SWAP") and d.get("state") == "live"}
    if ids:
        cache_put("okx:inst", ids)
    return ids


def _okx(path: str, params: dict, rate=_OKX_RUBIK) -> list:
    js = get_json(f"{OKX}{path}", params, bucket=rate[0], rate=rate[1])
    if not js or str(js.get("code")) != "0":
        return []
    return js.get("data") or []


def _chg(rows: list[tuple[int, float]], hours: int) -> float | None:
    """% change from `hours` ago to latest. rows sorted newest first, hourly."""
    if len(rows) <= hours:
        return None
    new, old = rows[0][1], rows[hours][1]
    if not old:
        return None
    return round((new / old - 1) * 100, 3)


def _funding_feats(cur: float | None, interval_h: float | None,
                   hist: list[tuple[int, float]]) -> dict:
    """hist: (ts_ms, rate) newest first."""
    out: dict[str, Any] = {}
    ih = interval_h or 8.0
    out["funding_rate"] = cur
    out["funding_interval_h"] = interval_h
    out["funding_8h"] = None if cur is None else cur * 8.0 / ih
    if hist:
        now_ms = hist[0][0]
        h7 = [r for t, r in hist if now_ms - t <= 7 * 86_400_000]
        h30 = [r for t, r in hist if now_ms - t <= 30 * 86_400_000]
        out["funding_pct_7d"] = pct_rank(cur, h7)
        out["funding_pct_30d"] = pct_rank(cur, h30)
        out["funding_avg_7d_8h"] = (sum(h7) / len(h7) * 8.0 / ih) if h7 else None
    return out


def from_okx(core: str) -> dict:
    inst = f"{core}-USDT-SWAP"
    insts = okx_instruments()
    if insts and inst not in insts:
        return {}
    out: dict[str, Any] = {}
    fr = _okx("/api/v5/public/funding-rate", {"instId": inst}, _OKX_PUB)
    cur = ih = None
    if fr:
        d = fr[0]
        cur = fnum(d.get("fundingRate"))
        ft, nft = fnum(d.get("fundingTime")), fnum(d.get("nextFundingTime"))
        if ft and nft and nft > ft:
            ih = round((nft - ft) / 3_600_000, 2)
    fh = _okx("/api/v5/public/funding-rate-history", {"instId": inst, "limit": 100}, _OKX_PUB)
    hist = [(int(d["fundingTime"]), fnum(d.get("realizedRate") or d.get("fundingRate")))
            for d in fh if d.get("fundingTime")]
    hist = [(t, r) for t, r in hist if r is not None]
    if cur is not None or hist:
        out.update(_funding_feats(cur if cur is not None else (hist[0][1] if hist else None),
                                  ih, hist))

    oi = _okx("/api/v5/rubik/stat/contracts/open-interest-history",
              {"instId": inst, "period": "1H", "limit": 100})
    # rows: [ts, oi_contracts, oi_coin, oi_usd]; coin units strip the price move
    oi_rows = [(int(r[0]), fnum(r[2])) for r in oi if len(r) >= 4 and fnum(r[2])]
    if oi_rows:
        out["oi_usd"] = fnum(oi[0][3])
        out["oi_chg_1h"] = _chg(oi_rows, 1)
        out["oi_chg_4h"] = _chg(oi_rows, 4)
        out["oi_chg_24h"] = _chg(oi_rows, 24)

    ls = _okx("/api/v5/rubik/stat/contracts/long-short-account-ratio-contract",
              {"instId": inst, "period": "1H", "limit": 100})
    ls_rows = [(int(r[0]), fnum(r[1])) for r in ls if len(r) >= 2 and fnum(r[1])]
    if ls_rows:
        out["ls_ratio"] = ls_rows[0][1]
        out["ls_pct_4d"] = pct_rank(ls_rows[0][1], [v for _, v in ls_rows])
        out["ls_chg_24h"] = _chg(ls_rows, 24)

    tk = _okx("/api/v5/rubik/stat/taker-volume-contract",
              {"instId": inst, "period": "1H", "limit": 25, "unit": "2"})
    # rows: [ts, sell_vol, buy_vol]. Row 0 is the still-forming hour: use 1..
    tk_rows = [(fnum(r[1]), fnum(r[2])) for r in tk if len(r) >= 3]
    tk_rows = [(s, b) for s, b in tk_rows if s is not None and b is not None]
    if len(tk_rows) >= 2:
        s1, b1 = tk_rows[1]
        out["taker_ratio_1h"] = round(b1 / s1, 4) if s1 else None
        s24 = sum(s for s, _ in tk_rows[1:25])
        b24 = sum(b for _, b in tk_rows[1:25])
        out["taker_ratio_24h"] = round(b24 / s24, 4) if s24 else None
    return out


# ── MEXC ────────────────────────────────────────────────────────────────────
def from_mexc(base: str, core: str) -> dict:
    out: dict[str, Any] = {}
    for b in dict.fromkeys((base, core)):
        sym = f"{b}_USDT"
        js = get_json(f"{MEXC}/api/v1/contract/funding_rate/{sym}",
                      bucket=_MEXC_RATE[0], rate=_MEXC_RATE[1])
        if not js or not js.get("success"):
            continue
        d = js.get("data") or {}
        cur = fnum(d.get("fundingRate"))
        ih = fnum(d.get("collectCycle"))
        hj = get_json(f"{MEXC}/api/v1/contract/funding_rate/history",
                      {"symbol": sym, "page_num": 1, "page_size": 100},
                      bucket=_MEXC_RATE[0], rate=_MEXC_RATE[1])
        rows = ((hj or {}).get("data") or {}).get("resultList") or []
        hist = [(int(r["settleTime"]), fnum(r.get("fundingRate"))) for r in rows
                if r.get("settleTime")]
        hist = [(t, r) for t, r in hist if r is not None]
        out.update(_funding_feats(cur, ih, hist))
        # MEXC ticker holdVol is a contract count without history; it adds no
        # change-over-time signal, so OI is left to OKX/Bybit.
        break
    return out


# ── Bybit ───────────────────────────────────────────────────────────────────
def _bybit(path: str, params: dict) -> dict | None:
    js = get_json(f"{BYBIT}{path}", params, bucket=_BYBIT_RATE[0], rate=_BYBIT_RATE[1],
                  host="api.bybit.com")
    if not js or js.get("retCode") != 0:
        return None
    return js.get("result") or {}


def from_bybit(base: str) -> dict:
    sym = f"{base}USDT"
    out: dict[str, Any] = {}
    tk = _bybit("/v5/market/tickers", {"category": "linear", "symbol": sym})
    if tk is None:
        return out
    lst = tk.get("list") or []
    if lst:
        d = lst[0]
        cur = fnum(d.get("fundingRate"))
        ih = fnum(d.get("fundingIntervalHour"))
        fh = _bybit("/v5/market/funding/history",
                    {"category": "linear", "symbol": sym, "limit": 200}) or {}
        hist = [(int(r["fundingRateTimestamp"]), fnum(r.get("fundingRate")))
                for r in fh.get("list") or [] if r.get("fundingRateTimestamp")]
        hist = [(t, r) for t, r in hist if r is not None]
        out.update(_funding_feats(cur, ih, hist))
        oi_val = fnum(d.get("openInterestValue"))
        if oi_val:
            out["oi_usd"] = oi_val
    oi = _bybit("/v5/market/open-interest",
                {"category": "linear", "symbol": sym, "intervalTime": "1h", "limit": 30}) or {}
    oi_rows = [(int(r["timestamp"]), fnum(r.get("openInterest")))
               for r in oi.get("list") or [] if fnum(r.get("openInterest"))]
    if oi_rows:
        out["oi_chg_1h"] = _chg(oi_rows, 1)
        out["oi_chg_4h"] = _chg(oi_rows, 4)
        out["oi_chg_24h"] = _chg(oi_rows, 24)
    ar = _bybit("/v5/market/account-ratio",
                {"category": "linear", "symbol": sym, "period": "1h", "limit": 100}) or {}
    rows = []
    for r in ar.get("list") or []:
        b, s = fnum(r.get("buyRatio")), fnum(r.get("sellRatio"))
        if b is not None and s:
            rows.append((int(r["timestamp"]), b / s))
    if rows:
        out["ls_ratio"] = round(rows[0][1], 4)
        out["ls_pct_4d"] = pct_rank(rows[0][1], [v for _, v in rows])
        out["ls_chg_24h"] = _chg(rows, 24)
    return out


# ── Public entry ────────────────────────────────────────────────────────────
def get(symbol: str, *, use_cache: bool = True) -> dict:
    """Flat derivs features for `symbol` (any of BTC, BTC-USD, 1000PEPE-USD,
    SOLUSDT). Adds 'derivs_src' (string, which venues filled anything). Never raises."""
    key = f"derivs:{symbol.upper()}"
    if use_cache:
        hit = cache_get(key, CACHE_TTL)
        if hit is not None:
            return dict(hit)
    out = _empty()
    srcs: list[str] = []
    try:
        base, core = split_symbol(symbol)
        for name, fn in (("okx", lambda: from_okx(core)),
                         ("mexc", lambda: from_mexc(base, core)),
                         ("bybit", lambda: from_bybit(base))):
            if all(out[k] is not None for k in FIELDS if k != "funding_interval_h"):
                break
            # MEXC only offers funding: skip it when funding is already filled.
            if name == "mexc" and out["funding_rate"] is not None:
                continue
            try:
                part = fn()
            except Exception as exc:                # noqa: BLE001
                log.debug("derivs %s %s failed: %s", name, symbol, exc)
                part = {}
            filled = False
            for k, v in part.items():
                if k in out and out[k] is None and v is not None:
                    out[k] = v
                    filled = True
            if filled:
                srcs.append(name)
    except Exception as exc:                        # noqa: BLE001
        log.debug("derivs %s failed: %s", symbol, exc)
    out["derivs_src"] = "+".join(srcs) or None
    out["derivs_ts"] = int(time.time())
    cache_put(key, dict(out))
    return out
