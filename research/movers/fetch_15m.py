"""Fetch Binance USDT-M 15m klines for the coin-months with mover events (plus the month
before, for indicator warm up). Source data.binance.vision (keeps delisted coins).
Run: python research/movers/fetch_15m.py <mover_months.csv> <out_dir>
Writes <out_dir>/<SYM>.parquet. Resumable."""
from __future__ import annotations

import io
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

DL = "https://data.binance.vision/data/futures/um/monthly/klines/{s}/15m/{s}-15m-{m}.zip"
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
        "trades", "tbv", "tqv", "ignore"]
sess = requests.Session()


def one(s: str, m: str) -> pd.DataFrame | None:
    for att in range(4):
        try:
            r = sess.get(DL.format(s=s, m=m), timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            raw = z.read(z.namelist()[0]).decode()
            first = raw.split("\n", 1)[0]
            df = pd.read_csv(io.StringIO(raw), header=0 if first.startswith("open_time") else None)
            df.columns = COLS[: len(df.columns)]
            return df
        except Exception:                       # noqa: BLE001
            time.sleep(2 + 3 * att)
    return None


def sym(args):
    s, months, out = args
    p = out / f"{s}.parquet"
    if p.exists():
        return s, 0
    parts = [x for x in (one(s, m) for m in months) if x is not None]
    if not parts:
        return s, 0
    df = pd.concat(parts)
    df["t"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms")
    df = df.set_index("t")[["open", "high", "low", "close", "volume", "quote_volume"]].astype(float)
    df = df[~df.index.duplicated()].sort_index()
    df.to_parquet(p)
    return s, len(df)


if __name__ == "__main__":
    mm = pd.read_csv(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for s, g in mm.groupby("sym"):
        ms = set(g["mo"])
        for m in list(ms):
            ms.add(str(pd.Period(m) - 1))
        ms = sorted(x for x in ms if x <= "2026-09")
        jobs.append((s, ms, out))
    done = 0
    with ThreadPoolExecutor(24) as ex:
        for s, n in ex.map(sym, jobs):
            done += 1
            if done % 25 == 0:
                print(done, len(jobs), flush=True)
    print("done")
