"""
Fetch DAILY candles for EVERY active MEXC USDT perpetual (the full futures list,
small caps and fresh listings included), using the perp's own candles.

Kept: every USDT perp except MEXC's TradFi zone (tokenised stocks, ETFs, indices)
and commodities, minus stablecoins / wrapped / leveraged tokens. Coins with >= 30 days
of history are saved, so young listings are included.

Output matches fetch_history.py: {"coins": {"PEPE-USD": DataFrame, ...}, "btc": DataFrame}

Run:  ./venv/bin/python research/families/fetch_perps.py out.pkl [threads]
"""
from __future__ import annotations
import pickle
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.families.fetch_history import START, _client, _retry  # noqa: E402
from utils.crypto_universe import _BLOCKLIST  # noqa: E402

DAY = 86_400_000


def universe() -> list[tuple[str, str]]:
    ex = _client("mexc")
    mk = _retry(ex.load_markets)
    commodities = {"XAU", "XAUT", "PAXG", "SILVER", "USOIL", "UKOIL", "NGAS", "COPPER", "XPD", "XPT"}
    out = []
    for m in mk.values():
        if not (m.get("swap") and m.get("active") and m.get("quote") == "USDT"
                and m.get("settle") == "USDT"):
            continue
        base = str(m["base"]).upper()
        zones = " ".join(map(str, (m.get("info") or {}).get("conceptPlate") or []))
        if "tradfi" in zones or "Stock" in zones or base in _BLOCKLIST or base in commodities:
            continue
        if any(base.endswith(s) for s in ("3L", "3S", "5L", "5S", "UP", "DOWN")):
            continue
        out.append((base, m["symbol"], float(m.get("contractSize") or 1.0)))
    return sorted(set(out))


def fetch(item):
    base, sym, csize = item
    ex = _client("mexc")
    start, rows, win = ex.parse8601(START), [], 250
    end = int(time.time() * 1000) // DAY * DAY
    try:
        while end > start:
            since = max(start, end - win * DAY)
            b = _retry(ex.fetch_ohlcv, sym, "1d", since=since, limit=300)
            b = [r for r in (b or []) if since <= r[0] < end + DAY]
            if not b:
                break
            rows = b + rows
            end = since - DAY
    except Exception:                                   # noqa: BLE001
        return base, None
    if len(rows) < 30:
        return base, None
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts")
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("ts"), unit="ms")).normalize()
    df = df[~df.index.duplicated()]
    df["volume"] = df["volume"] * csize      # perp volume is in CONTRACTS -> base units
    return base, df


def main(out, threads=4):
    uni = universe()
    print(f"{len(uni)} MEXC USDT crypto perps", flush=True)
    res = {"coins": {}, "btc": None}
    with ThreadPoolExecutor(threads) as pool:
        for k, (base, df) in enumerate(pool.map(fetch, uni), 1):
            if base == "BTC":
                res["btc"] = df
            res["coins"][f"{base}-USD"] = df
            if k % 100 == 0:
                print(f"  {k}/{len(uni)}", flush=True)
    Path(out).write_bytes(pickle.dumps(res))
    got = [d for d in res["coins"].values() if d is not None]
    print(f"saved {len(got)} coins with >= 30 days", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 4)
