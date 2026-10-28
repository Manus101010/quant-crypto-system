"""
Open interest (coin units) at the daily close for each Distribution Short /
Downtrend Bounce Fade signal, from Binance's archived 5m metrics
(data.binance.vision .../daily/metrics/<SYM>/<SYM>-metrics-<date>.zip, from
2021-12). Adds oi_chg3d and oi_chg7d (signal close vs 3 / 7 closes earlier) so
the pre-registered rules from docs/night/features.md can be tested on the wide
universe:  DS needs oi_chg3d > 0;  DBF skips oi_chg7d >= +10%.

Run:  python research/edge_fix/shorts_oi.py <out_dir>   (reads/updates short_trades.parquet)
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

DL = "https://data.binance.vision/data/futures/um/daily/metrics/{s}/{s}-metrics-{d}.zip"
_sess = requests.Session()


def oi_close(sym: str, day: pd.Timestamp) -> float:
    d = day.strftime("%Y-%m-%d")
    for _ in range(3):
        try:
            r = _sess.get(DL.format(s=sym, d=d), timeout=40)
            if r.status_code == 404:
                return np.nan
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])))
            v = pd.to_numeric(df["sum_open_interest"], errors="coerce").dropna()
            return float(v.iloc[-1]) if len(v) else np.nan
        except Exception:                          # noqa: BLE001
            continue
    return np.nan


def main():
    out = Path(sys.argv[1])
    T = pd.read_parquet(out / "short_trades.parquet")
    cache_p = out / "short_oi_cache.json"
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    need = set()
    for _, r in T[T.setup.isin(["Distribution Short", "Downtrend Bounce Fade"])].iterrows():
        for lag in (0, 3, 7):
            dd = r.date - pd.Timedelta(days=lag)
            if dd >= pd.Timestamp("2021-12-01"):
                need.add((r.sym, dd.strftime("%Y-%m-%d")))
    todo = [k for k in need if f"{k[0]}|{k[1]}" not in cache]
    print(f"{len(need)} OI points needed, {len(todo)} to fetch", flush=True)
    with ThreadPoolExecutor(32) as ex:
        for n, (k, v) in enumerate(zip(todo, ex.map(lambda k: oi_close(k[0], pd.Timestamp(k[1])), todo)), 1):
            cache[f"{k[0]}|{k[1]}"] = None if not np.isfinite(v) else v
            if n % 500 == 0:
                print(f"  {n}/{len(todo)}", flush=True)
                cache_p.write_text(json.dumps(cache))
    cache_p.write_text(json.dumps(cache))

    def get(sym, day):
        v = cache.get(f"{sym}|{day.strftime('%Y-%m-%d')}")
        return np.nan if v is None else v
    o0 = np.array([get(s, d) for s, d in zip(T.sym, T.date)])
    o3 = np.array([get(s, d - pd.Timedelta(days=3)) for s, d in zip(T.sym, T.date)])
    o7 = np.array([get(s, d - pd.Timedelta(days=7)) for s, d in zip(T.sym, T.date)])
    with np.errstate(all="ignore"):
        T["oi_chg3d"] = o0 / o3 - 1
        T["oi_chg7d"] = o0 / o7 - 1
    T.to_parquet(out / "short_trades.parquet")
    print(T.groupby("setup")[["oi_chg3d", "oi_chg7d"]].count())


if __name__ == "__main__":
    main()
