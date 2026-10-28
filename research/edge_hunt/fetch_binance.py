"""
Historical data for the edge hunt from data.binance.vision (public S3 archive,
reachable from this sandbox; the Binance API itself returns 451 here).

Why Binance archives and not MEXC/OKX: MEXC perp intraday history stops at
~2025-11, OKX rubik OI keeps 100 hourly rows and funding ~3 months. The Binance
archive has 1h klines (with taker buy volume), funding, the premium index
(perp vs index basis) and 5m open interest back to 2020, AND it keeps DELISTED
symbols, so the universe can be built point in time (less survivorship bias).
Binance USDT perps are a close proxy for Bybit USDT perps (same coins, same
funding mechanics, prices within a few bps).

Writes research/edge_hunt/cache/h1/<SYM>.parquet with columns
  open high low close volume qv tbq (taker buy quote) funding (rate settled in
  that hour, else NaN) fint (funding interval h) prem (premium index 1h close)
and, with `oi`, cache/oi/<SYM>.parquet: 1h last of 5m metrics (oi coin units,
oi usd, top trader L/S, account L/S, taker L/S vol ratio).

Run: python research/edge_hunt/fetch_binance.py [h1|oi] [n_oi=50]
"""
from __future__ import annotations

import io
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = "https://data.binance.vision/"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
CACHE = Path(__file__).resolve().parent / "cache"
START_M, END_M = "2023-01", "2026-09"        # monthly files; Oct 2026 from daily files
DAILY_FROM = "2026-10-01"
SESSION = requests.Session()
SESSION.mount("https://", requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64))
STABLE = {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "USDE", "EUR", "GBP", "AEUR", "XUSD", "BFUSD", "USD1"}


def get(url, tries=4):
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code == 404:
                return None
            if r.ok:
                return r.content
        except Exception:                          # noqa: BLE001
            pass
        time.sleep(1 + i)
    return None


def s3_list(prefix, delimiter=None, marker=None):
    out, mk = [], marker
    while True:
        p = {"prefix": prefix}
        if delimiter:
            p["delimiter"] = delimiter
        if mk:
            p["marker"] = mk
        r = None
        for i in range(6):
            try:
                r = SESSION.get(S3, params=p, timeout=30).text
                break
            except Exception:                      # noqa: BLE001
                time.sleep(2 + 2 * i)
        if r is None:
            raise RuntimeError("s3 list failed " + prefix)
        keys = re.findall(r"<Key>([^<]+)</Key>", r) if not delimiter else re.findall(r"<Prefix>([^<]+)</Prefix>", r)[1:]
        out += keys
        if "<IsTruncated>true</IsTruncated>" not in r:
            return out
        nm = re.search(r"<NextMarker>([^<]+)</NextMarker>", r)
        mk = nm.group(1) if nm else (keys[-1] if keys else None)
        if not mk:
            return out


def symbols():
    pre = s3_list("data/futures/um/monthly/klines/", "/")
    syms = [p.rstrip("/").split("/")[-1] for p in pre]
    syms = [s for s in syms if s.endswith("USDT") and s[:-4] not in STABLE and "_" not in s]
    return syms


def read_csv_zip(blob, header_guess):
    z = zipfile.ZipFile(io.BytesIO(blob))
    raw = z.read(z.namelist()[0])
    first = raw[:40].decode(errors="ignore")
    has_header = not first[0].isdigit() and not first.startswith("-")
    df = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None)
    if not has_header:
        df.columns = header_guess[: df.shape[1]]
    return df


KL = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count",
      "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def months_in(keys):
    return sorted({re.search(r"(\d{4}-\d{2})\.zip$", k).group(1) for k in keys if k.endswith(".zip")})


def fetch_symbol(sym):
    try:
        return _fetch_symbol(sym)
    except Exception as e:                         # noqa: BLE001
        print("ERR", sym, e, flush=True)
        return sym, 0


def _fetch_symbol(sym):
    out = CACHE / "h1" / f"{sym}.parquet"
    if out.exists():
        return sym, -1
    kk = s3_list(f"data/futures/um/monthly/klines/{sym}/1h/")
    ms = [m for m in months_in(kk) if START_M <= m <= END_M]
    dk = [k for k in s3_list(f"data/futures/um/daily/klines/{sym}/1h/", marker=f"data/futures/um/daily/klines/{sym}/1h/{sym}-1h-2026-09-30.zip") if k.endswith(".zip")]
    days = sorted({re.search(r"(\d{4}-\d{2}-\d{2})\.zip$", k).group(1) for k in dk})
    days = [d for d in days if d >= DAILY_FROM]
    if not ms and not days:
        return sym, 0
    urls = []
    for m in ms:
        urls += [("k", f"{BASE}data/futures/um/monthly/klines/{sym}/1h/{sym}-1h-{m}.zip"),
                 ("p", f"{BASE}data/futures/um/monthly/premiumIndexKlines/{sym}/1h/{sym}-1h-{m}.zip"),
                 ("f", f"{BASE}data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{m}.zip")]
    for d in days:
        urls += [("k", f"{BASE}data/futures/um/daily/klines/{sym}/1h/{sym}-1h-{d}.zip"),
                 ("p", f"{BASE}data/futures/um/daily/premiumIndexKlines/{sym}/1h/{sym}-1h-{d}.zip")]
    with ThreadPoolExecutor(8) as pool:
        blobs = list(pool.map(lambda u: get(u[1]), urls))
    parts, prem, fund = [], [], []
    for (kind, _), b in zip(urls, blobs):
        if not b:
            continue
        if kind == "k":
            parts.append(read_csv_zip(b, KL))
        elif kind == "p":
            prem.append(read_csv_zip(b, KL))
        else:
            fund.append(read_csv_zip(b, ["calc_time", "funding_interval_hours", "last_funding_rate"]))
    if not parts:
        return sym, 0
    k = pd.concat(parts)
    k = k[pd.to_numeric(k["open_time"], errors="coerce").notna()]
    k["open_time"] = k["open_time"].astype(np.int64)
    k = k.drop_duplicates("open_time").sort_values("open_time")
    df = pd.DataFrame({
        "open": k["open"].astype(float).values, "high": k["high"].astype(float).values,
        "low": k["low"].astype(float).values, "close": k["close"].astype(float).values,
        "volume": k["volume"].astype(float).values, "qv": k["quote_volume"].astype(float).values,
        "tbq": k["taker_buy_quote_volume"].astype(float).values,
    }, index=pd.to_datetime(k["open_time"].values, unit="ms"))
    df["funding"] = np.nan
    df["fint"] = np.nan
    if fund:
        f = pd.concat(fund)
        f = f[pd.to_numeric(f["calc_time"], errors="coerce").notna()]
        ts = pd.to_datetime(f["calc_time"].astype(np.int64), unit="ms").dt.floor("h")
        # funding settles at the hour boundary: attribute to the bar that ENDS there,
        # i.e. the bar opened one hour earlier (a position held through that bar pays it)
        ts = ts - pd.Timedelta(hours=1)
        fs = pd.Series(f["last_funding_rate"].astype(float).values, index=ts)
        fs = fs[~fs.index.duplicated()]
        fi = pd.Series(f["funding_interval_hours"].astype(float).values, index=ts)
        fi = fi[~fi.index.duplicated()]
        df.loc[df.index.intersection(fs.index), "funding"] = fs
        df.loc[df.index.intersection(fi.index), "fint"] = fi
    df["prem"] = np.nan
    if prem:
        p = pd.concat(prem)
        p = p[pd.to_numeric(p["open_time"], errors="coerce").notna()]
        ps = pd.Series(p["close"].astype(float).values, index=pd.to_datetime(p["open_time"].astype(np.int64), unit="ms"))
        ps = ps[~ps.index.duplicated()]
        df["prem"] = ps.reindex(df.index)
    df = df.astype("float32")
    df.to_parquet(out)
    return sym, len(df)


MET = ["create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
       "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
       "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]


def fetch_oi(sym):
    out = CACHE / "oi" / f"{sym}.parquet"
    if out.exists():
        return sym, -1
    keys = [k for k in s3_list(f"data/futures/um/daily/metrics/{sym}/", marker=f"data/futures/um/daily/metrics/{sym}/{sym}-metrics-2022-12-31.zip") if k.endswith(".zip")]
    rows = []

    def one(k):
        b = get(BASE + k)
        if not b:
            return None
        try:
            d = read_csv_zip(b, MET)
            return d
        except Exception:                          # noqa: BLE001
            return None
    with ThreadPoolExecutor(16) as pool:
        for d in pool.map(one, keys):
            if d is not None and len(d):
                rows.append(d)
    if not rows:
        return sym, 0
    d = pd.concat(rows)
    d.index = pd.to_datetime(d["create_time"])
    d = d.sort_index()
    d = d[~d.index.duplicated()]
    o = pd.DataFrame({
        "oi": d["sum_open_interest"].astype(float), "oiv": d["sum_open_interest_value"].astype(float),
        "top_ls": d["sum_toptrader_long_short_ratio"].astype(float),
        "acc_ls": d["count_long_short_ratio"].astype(float),
        "taker_ls": d["sum_taker_long_short_vol_ratio"].astype(float),
    })
    # value stamped at time t describes the state AT t; resample to hourly "last known at bar close"
    o = o.resample("1h", label="left", closed="left").last()
    o.astype("float32").to_parquet(out)
    return sym, len(o)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "h1"
    if mode == "h1":
        (CACHE / "h1").mkdir(parents=True, exist_ok=True)
        syms = symbols()
        print(len(syms), "symbols", flush=True)
        t0 = time.time()
        with ThreadPoolExecutor(6) as pool:
            for i, (s, n) in enumerate(pool.map(fetch_symbol, syms), 1):
                if i % 25 == 0 or n == 0:
                    print(i, s, n, f"{time.time()-t0:.0f}s", flush=True)
    else:
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        (CACHE / "oi").mkdir(parents=True, exist_ok=True)
        lst = [l.strip() for l in (CACHE / "oi_universe.txt").read_text().split()][:n]
        t0 = time.time()
        for i, s in enumerate(lst, 1):
            print(i, *fetch_oi(s), f"{time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
