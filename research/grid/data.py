"""
Data for the grid backtest: MEXC USDT-perp 5m candles + MEXC funding history,
cached to research/grid/cache/*.parquet (untracked).

MEXC perp 5m history only reaches back to ~2025-11-01 through the public API,
so the backtest window is 2025-11-01 -> now (~12 months). Bybit itself returns
403 from this sandbox, MEXC is the closest reachable proxy for Bybit perps.

ccxt in this sandbox must be handed the HTTPS proxy explicitly (it does not read
HTTPS_PROXY), so the client is built with `httpsProxy` when the env var is set.

Run:  python research/grid/data.py [n_top=40] [n_small=15]
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from utils.logger import get_logger  # noqa: E402

log = get_logger(__name__)
CACHE = Path(__file__).resolve().parent / "cache"
START = "2025-11-01"
M5 = 300_000
_local: dict = {}


def client():
    import threading
    import ccxt
    k = threading.get_ident()
    if k not in _local:
        opts = {"enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "swap"}}
        if os.environ.get("HTTPS_PROXY"):
            opts["httpsProxy"] = os.environ["HTTPS_PROXY"]
        _local[k] = ccxt.mexc(opts)
    return _local[k]


def _retry(fn, *a, **k):
    for i in range(5):
        try:
            return fn(*a, **k)
        except Exception:                          # noqa: BLE001
            time.sleep(1.5 * (i + 1))
    return None


def universe(n_top: int = 40, n_small: int = 15) -> list[dict]:
    """Bybit perps (data/bybit_perps.json) that trade on MEXC, ranked by MEXC 24h
    quote volume: the top n_top plus n_small evenly picked from ranks 150-350."""
    bybit = {s.replace("-USD", "") for s in json.loads((ROOT / "data/bybit_perps.json").read_text())["symbols"]}
    r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=20).json()["data"]
    rows = []
    for t in r:
        sym = t["symbol"]
        if not sym.endswith("_USDT"):
            continue
        base = sym[:-5]
        if base in bybit or base.replace("1000", "") in bybit:
            rows.append({"base": base, "mexc": sym, "vol": float(t.get("amount24") or 0)})
    rows.sort(key=lambda x: -x["vol"])
    stable = {"USDC", "USDE", "FDUSD", "DAI", "XAUT", "PAXG"}
    rows = [x for x in rows if x["base"] not in stable]
    top = rows[:n_top]
    pool = rows[150:350]
    small = pool[:: max(1, len(pool) // n_small)][:n_small] if pool else []
    for x in top:
        x["tier"] = "top"
    for x in small:
        x["tier"] = "small"
    extra = [x for x in rows if x["base"] == "DOOD" and x not in top + small]
    for x in extra:
        x["tier"] = "small"
    return top + small + extra


def candles(base: str, since_ms: int, until_ms: int) -> pd.DataFrame | None:
    ex = client()
    sym = f"{base}/USDT:USDT"
    rows, cur = [], since_ms
    while cur < until_ms:
        b = _retry(ex.fetch_ohlcv, sym, "5m", since=cur, limit=1000)
        if b is None:
            break
        if not b:
            cur += 1000 * M5                       # listing later than START
            continue
        rows += [x for x in b if x[0] < until_ms]
        nxt = b[-1][0] + M5
        if nxt <= cur:
            break
        cur = nxt
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts")
    df.index = pd.to_datetime(df.pop("ts"), unit="ms")
    return df.astype(float)


def funding(mexc_sym: str) -> pd.Series:
    out = {}
    for page in range(1, 6):
        r = _retry(requests.get, "https://contract.mexc.com/api/v1/contract/funding_rate/history",
                   params={"symbol": mexc_sym, "page_num": page, "page_size": 1000}, timeout=20)
        if r is None:
            break
        d = r.json().get("data") or {}
        for x in d.get("resultList", []):
            out[x["settleTime"]] = float(x["fundingRate"])
        if page >= (d.get("totalPage") or 1):
            break
    s = pd.Series(out, dtype=float).sort_index()
    s.index = pd.to_datetime(s.index, unit="ms")
    return s


def fetch_one(x: dict, since_ms: int, until_ms: int) -> tuple[str, int]:
    p = CACHE / f"{x['base']}.parquet"
    if p.exists():
        return x["base"], -1
    df = candles(x["base"], since_ms, until_ms)
    if df is None or len(df) < 2000:
        return x["base"], 0
    f = funding(x["mexc"])
    df["funding"] = 0.0
    if len(f):
        f = f[(f.index >= df.index[0]) & (f.index <= df.index[-1])]
        pos = df.index.searchsorted(f.index)
        ok = pos < len(df)
        df.iloc[pos[ok], df.columns.get_loc("funding")] = f.values[ok]
    df.to_parquet(p)
    return x["base"], len(df)


def main(n_top: int = 40, n_small: int = 15) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    uni = universe(n_top, n_small)
    if not any(x["base"] == "BTC" for x in uni):
        uni.insert(0, {"base": "BTC", "mexc": "BTC_USDT", "vol": 0, "tier": "top"})
    (CACHE / "universe.json").write_text(json.dumps(uni, indent=1))
    since = int(pd.Timestamp(START).value // 1_000_000)
    until = int(time.time() * 1000) // M5 * M5
    log.info("grid data: %d coins, %s -> now, 5m", len(uni), START)
    t0 = time.time()
    with ThreadPoolExecutor(4) as pool:
        for k, (b, n) in enumerate(pool.map(lambda x: fetch_one(x, since, until), uni), 1):
            log.info("  %d/%d %s bars=%s (%.0fs)", k, len(uni), b, n, time.time() - t0)


if __name__ == "__main__":
    a = [int(x) for x in sys.argv[1:3]]
    main(*a)
