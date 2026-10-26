"""
One call that merges every feature source into a flat dict for a signal.

    from features.snapshot import snapshot, alert_line
    snap = snapshot("SOL-USD", direction="short")    # never raises
    alert_line(snap)  ->  "Pos: fund +0.010% (p62) · OI 24h +3.1% · L/S 2.9 (p88) · taker 0.97"

Features are LOGGED with each signal for later evaluation
(research/features_eval.py). They are not trade calls and do not gate anything
until the evaluation shows a measured lift.

Sources run in parallel threads with a time budget; whatever has not answered
in time is None. Each source caches its own responses, so a second snapshot of
the same coin within 5 minutes costs no HTTP calls.

Derived flags (1.0 / 0.0, None when the inputs are missing):
  crowded_longs   funding in the top 10% of its 7d range AND L/S accounts in the
                  top 10% of its 4d range AND funding above the +0.01%/8h clamp
  crowded_shorts  mirror: both in the bottom 10% (and funding < 0)
  oi_spike        OI (coin units) +5% in 1h, or +10% in 4h, or +25% in 24h
  dex_hype        DEX volume running >= 3x its 24h pace with >= 55% buy txns
                  (>= $100k 24h DEX volume), or the token is paid-boosted
  squeeze_risk    short-squeeze fuel: funding negative and in the bottom 20% of
                  7d with OI up >= 5% in 24h, or crowded_shorts
  flush_risk      long-flush fuel: crowded_longs with OI rising (oi_chg_24h >= 5)
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any

from features import coinalyze, coinglass, derivs, dex, hyperliquid, whales
from features._http import cache_get, cache_put, fnum, get_json, split_symbol
from utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_BUDGET = 6.0
FUNDING_CLAMP_8H = 0.0001       # the default +0.01% per 8h interest-rate clamp
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="features")

FLAGS = ("crowded_longs", "crowded_shorts", "oi_spike", "dex_hype", "squeeze_risk", "flush_risk")


def ref_price(core: str) -> float | None:
    """USD price of one core coin from OKX swap ticker, else MEXC (cached 60s)."""
    key = f"px:{core}"
    hit = cache_get(key, 60)
    if hit is not None:
        return hit
    px = None
    js = get_json("https://www.okx.com/api/v5/market/ticker", {"instId": f"{core}-USDT-SWAP"},
                  bucket="okx_pub", rate=(8, 2.0))
    if js and str(js.get("code")) == "0" and js.get("data"):
        px = fnum(js["data"][0].get("last"))
    if px is None:
        js = get_json("https://contract.mexc.com/api/v1/contract/ticker",
                      {"symbol": f"{core}_USDT"}, bucket="mexc", rate=(10, 2.0))
        if js and js.get("success"):
            px = fnum((js.get("data") or {}).get("lastPrice"))
    if px is not None:
        cache_put(key, px)
    return px


def derive_flags(f: dict) -> dict[str, float | None]:
    fp, lp, f8 = f.get("funding_pct_7d"), f.get("ls_pct_4d"), f.get("funding_8h")
    o1, o4, o24 = f.get("oi_chg_1h"), f.get("oi_chg_4h"), f.get("oi_chg_24h")
    out: dict[str, float | None] = {k: None for k in FLAGS}

    def b(x):
        return None if x is None else (1.0 if x else 0.0)

    if fp is not None and lp is not None and f8 is not None:
        # Funding sits pinned at the +0.01%/8h clamp most of the time, so in a
        # quiet week the clamp itself ranks p90+. Crowded longs therefore also
        # need funding strictly above the clamp.
        out["crowded_longs"] = b(fp > 90 and lp > 90 and f8 > FUNDING_CLAMP_8H * 1.05)
        out["crowded_shorts"] = b(fp < 10 and lp < 10 and f8 < 0)
    if any(v is not None for v in (o1, o4, o24)):
        out["oi_spike"] = b((o1 or 0) >= 5 or (o4 or 0) >= 10 or (o24 or 0) >= 25)
    ve, br, v24 = f.get("dex_vol_exp_1h"), f.get("dex_buy_ratio_h1"), f.get("dex_vol_h24")
    if f.get("dex_pairs"):
        hype = (ve is not None and br is not None and (v24 or 0) >= 100_000
                and ve >= 3 and br >= 0.55)
        out["dex_hype"] = b(hype or bool(f.get("dex_boosted")))
    elif f.get("dex_pairs") == 0:
        out["dex_hype"] = 0.0
    if fp is not None and f8 is not None and o24 is not None:
        out["squeeze_risk"] = b((f8 < 0 and fp <= 20 and o24 >= 5)
                                or out["crowded_shorts"] == 1.0)
        out["flush_risk"] = b(out["crowded_longs"] == 1.0 and o24 >= 5)
    return out


CANONICAL = derivs.FIELDS          # positioning fields both derivs sources fill


def merge(parts: dict[str, dict]) -> dict[str, Any]:
    """Coinalyze (Bybit market, primary) wins for the canonical positioning
    fields; OKX/MEXC/Bybit public (derivs.py) fills whatever it left None.
    `pos_src` records which one supplied funding_8h. OKX's own readings are
    also kept as okx_* for cross-venue comparison when Coinalyze was primary."""
    out: dict[str, Any] = {}
    cz, dv = parts.get("coinalyze") or {}, parts.get("derivs") or {}
    for name, part in parts.items():
        if name in ("coinalyze", "derivs"):
            continue
        out.update({k: v for k, v in part.items() if k != "derivs_ts"})
    for k in coinalyze.FIELDS:
        if k not in CANONICAL:
            out[k] = cz.get(k)
    for k in CANONICAL:
        v = cz.get(k)
        out[k] = v if v is not None else dv.get(k)
    if cz.get("funding_8h") is not None and dv.get("funding_interval_h"):
        out["funding_interval_h"] = dv.get("funding_interval_h")
    out["pos_src"] = ("coinalyze" if cz.get("funding_8h") is not None
                      else dv.get("derivs_src"))
    if cz:
        for k in ("funding_8h", "oi_chg_24h", "ls_ratio"):
            out[f"okx_{k}"] = dv.get(k)
    return out


def snapshot(symbol: str, direction: str | None = None, *, budget: float = DEFAULT_BUDGET,
             with_dex: bool = True, with_paid: bool = True) -> dict[str, Any]:
    """Flat numeric features for `symbol` at this moment. Never raises.
    Keys: every derivs/dex/coinglass/whales field (None when missing), the
    FLAGS, plus meta: symbol, direction, ts, ms, sources."""
    t0 = time.time()
    snap: dict[str, Any] = {"symbol": symbol, "direction": direction, "ts": int(t0)}
    for k in coinalyze.FIELDS + derivs.FIELDS + dex.FIELDS + hyperliquid.FIELDS:
        snap[k] = None
    try:
        _, core = split_symbol(symbol)
        jobs = {}
        if coinalyze.enabled():
            jobs["coinalyze"] = _pool.submit(coinalyze.get, symbol)
        jobs["derivs"] = _pool.submit(derivs.get, symbol)
        jobs["hyperliquid"] = _pool.submit(hyperliquid.get, symbol)
        if with_dex:
            jobs["dex"] = _pool.submit(lambda: dex.get(symbol, ref_price(core)))
        if with_paid and coinglass.enabled():
            jobs["coinglass"] = _pool.submit(coinglass.get, symbol)
        if with_paid and whales.enabled():
            jobs["whales"] = _pool.submit(whales.get, symbol)
        done, _ = wait(list(jobs.values()), timeout=budget)
        parts: dict[str, dict] = {}
        for name, fut in jobs.items():
            if fut not in done:
                log.debug("snapshot %s: %s timed out", symbol, name)
                continue
            try:
                parts[name] = fut.result() or {}
            except Exception as exc:                # noqa: BLE001
                log.debug("snapshot %s: %s failed: %s", symbol, name, exc)
        snap.update(merge(parts))
        srcs = []
        meta = ("derivs_src", "derivs_ts", "dex_pairs", "dex_price_checked")
        for name, part in parts.items():
            if any(v for k, v in part.items() if k not in meta):
                srcs.append((part.get("derivs_src") or name) if name == "derivs" else name)
        snap["sources"] = ",".join(srcs) or None
        snap.update(derive_flags(snap))
    except Exception as exc:                        # noqa: BLE001
        log.warning("snapshot %s failed: %s", symbol, exc)
        for k in FLAGS:
            snap.setdefault(k, None)
    snap["ms"] = int((time.time() - t0) * 1000)
    return snap


def to_json(snap: dict) -> str:
    """Compact JSON for a DB column (floats rounded, None kept)."""
    def r(v):
        return round(v, 6) if isinstance(v, float) else v
    return json.dumps({k: r(v) for k, v in snap.items()}, separators=(",", ":"))


def _pct(v: float | None, nd: int = 1) -> str:
    return "n/a" if v is None else f"{v:+.{nd}f}%"


def alert_line(snap: dict | None) -> str:
    """One compact Telegram line. Empty string when nothing useful is known."""
    if not snap:
        return ""
    parts = []
    f8 = snap.get("funding_8h")
    if f8 is not None:
        p = snap.get("funding_pct_7d")
        parts.append(f"fund {f8 * 100:+.3f}%" + (f" (p{p:.0f})" if p is not None else ""))
    if snap.get("oi_chg_24h") is not None:
        parts.append(f"OI 24h {_pct(snap['oi_chg_24h'])}")
    if snap.get("ls_ratio") is not None:
        p = snap.get("ls_pct_4d")
        parts.append(f"L/S {snap['ls_ratio']:.2f}" + (f" (p{p:.0f})" if p is not None else ""))
    if snap.get("taker_ratio_24h") is not None:
        parts.append(f"taker {snap['taker_ratio_24h']:.2f}")
    if snap.get("dex_vol_exp_1h") is not None and (snap.get("dex_vol_h24") or 0) >= 100_000:
        parts.append(f"DEX vol {snap['dex_vol_exp_1h']:.1f}x")
    if snap.get("whale_netflow_usd"):
        parts.append(f"whales→exch ${snap['whale_netflow_usd'] / 1e6:+.1f}M")
    flags = [k.replace("_", " ") for k in FLAGS if snap.get(k) == 1.0]
    if not parts and not flags:
        return ""
    line = "Pos: " + " · ".join(parts)
    if flags:
        line += "  ⚠ " + ", ".join(flags)
    return line
