"""
Survivorship-free perp history for the shorts decay study (Oct 2026).

Source: data.binance.vision, Binance's public S3 archive of USDT-M perpetual
futures. Unlike the live exchange APIs it keeps DELISTED symbols (LUNA, FTT,
SRM, ... and every small cap that was later removed), so the universe at each
date is the set of perps that actually traded then.

Downloads per symbol:
  1h klines   monthly zips 2021-06 .. last full month, then daily zips for the
              current month (daily/4h are resampled from 1h)
  funding     monthly fundingRate zips (8h or 4h prints)
and writes one parquet per symbol: <out>/k1h/<SYM>.parquet, <out>/fund/<SYM>.parquet.

Run:  python research/edge_fix/fetch_binance_um.py <out_dir> [--workers 24]
Resumable: a symbol whose parquet exists is skipped.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DL = "https://data.binance.vision/"
START = pd.Timestamp("2021-06-01")
_sess = requests.Session()


def _list(prefix: str, delimiter: bool = True) -> tuple[list[str], list[str]]:
    """(common prefixes, keys) under an S3 prefix, all pages."""
    pres, keys, marker = [], [], ""
    while True:
        p = {"prefix": prefix, "marker": marker}
        if delimiter:
            p["delimiter"] = "/"
        for att in range(6):
            try:
                r = _sess.get(S3, params=p, timeout=60)
                r.raise_for_status()
                break
            except Exception:                      # noqa: BLE001
                if att == 5:
                    raise
                time.sleep(2 + 3 * att)
        t = r.text
        pres += re.findall(r"<Prefix>([^<]+/)</Prefix>", t)[1:] if delimiter else []
        keys += re.findall(r"<Key>([^<]+)</Key>", t)
        if "<IsTruncated>true</IsTruncated>" not in t:
            break
        nm = re.search(r"<NextMarker>([^<]+)</NextMarker>", t)
        marker = nm.group(1) if nm else (keys[-1] if keys else pres[-1])
    return [p for p in pres if p != prefix], keys


def _zip_csv(key: str, names: list[str]) -> pd.DataFrame | None:
    for _ in range(3):
        try:
            r = _sess.get(DL + key, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            raw = z.read(z.namelist()[0]).decode()
            first = raw.split("\n", 1)[0]
            hdr = 0 if not first[:1].isdigit() else None
            df = pd.read_csv(io.StringIO(raw), header=hdr)
            df = df.iloc[:, :len(names)]
            df.columns = names
            return df
        except Exception:                          # noqa: BLE001
            time.sleep(2)
            continue
    return None


K_COLS = ["ts", "open", "high", "low", "close", "volume", "close_time", "quote_volume"]
F_COLS = ["ts", "interval_h", "rate"]


def fetch_symbol(sym: str, out: Path) -> str:
    kp, fp = out / "k1h" / f"{sym}.parquet", out / "fund" / f"{sym}.parquet"
    if kp.exists() and fp.exists():
        return f"{sym} cached"
    _, mk = _list(f"data/futures/um/monthly/klines/{sym}/1h/", delimiter=False)
    _, dk = _list(f"data/futures/um/daily/klines/{sym}/1h/", delimiter=False)
    mk = [k for k in mk if k.endswith(".zip")]
    months = {re.search(r"(\d{4}-\d{2})\.zip$", k).group(1): k for k in mk}
    months = {m: k for m, k in months.items() if pd.Timestamp(m + "-01") >= START}
    last_m = max(months) if months else "2021-05"
    days = [k for k in dk if k.endswith(".zip")
            and re.search(r"(\d{4}-\d{2})-\d{2}\.zip$", k).group(1) > last_m]
    frames = []
    for k in list(months.values()) + days:
        df = _zip_csv(k, K_COLS)
        if df is not None and len(df):
            frames.append(df)
    if frames:
        k = pd.concat(frames)
        k["ts"] = pd.to_numeric(k["ts"], errors="coerce")
        k = k.dropna(subset=["ts"])
        k["ts"] = k["ts"].astype("int64")
        k.loc[k["ts"] > 1e14, "ts"] //= 1000          # 2025+ archives use microseconds
        k = k.drop_duplicates("ts").sort_values("ts")
        k.index = pd.to_datetime(k.pop("ts"), unit="ms")
        k = k[["open", "high", "low", "close", "volume", "quote_volume"]].astype(float)
        kp.parent.mkdir(parents=True, exist_ok=True)
        k.to_parquet(kp)
    _, fk = _list(f"data/futures/um/monthly/fundingRate/{sym}/", delimiter=False)
    ff = []
    for key in fk:
        if not key.endswith(".zip"):
            continue
        m = re.search(r"(\d{4}-\d{2})\.zip$", key)
        if m and pd.Timestamp(m.group(1) + "-01") < START:
            continue
        df = _zip_csv(key, F_COLS)
        if df is not None and len(df):
            ff.append(df)
    f = pd.DataFrame(columns=["rate"])
    if ff:
        f = pd.concat(ff)
        f["ts"] = pd.to_numeric(f["ts"], errors="coerce")
        f = f.dropna(subset=["ts"]).drop_duplicates("ts").sort_values("ts")
        f.index = pd.to_datetime(f.pop("ts").astype("int64"), unit="ms")
        f = f[["rate"]].astype(float)
    fp.parent.mkdir(parents=True, exist_ok=True)
    f.to_parquet(fp)
    return f"{sym} k={len(frames)} files, fund={len(ff)}"


def _safe(sym: str, out: Path) -> str:
    try:
        return fetch_symbol(sym, out)
    except Exception as e:                         # noqa: BLE001
        return f"{sym} FAILED {e!r:.80}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--workers", type=int, default=24)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pres, _ = _list("data/futures/um/monthly/klines/")
    syms = sorted({p.rstrip("/").split("/")[-1] for p in pres})
    syms = [s for s in syms if s.endswith("USDT") and "_" not in s]
    pd.Series(syms).to_csv(out / "symbols.csv", index=False)
    print(f"{len(syms)} USDT-M perps in the archive (incl. delisted)", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        for k, msg in enumerate(ex.map(lambda s: _safe(s, out), syms), 1):
            if k % 25 == 0:
                print(f"  {k}/{len(syms)}  {msg}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
