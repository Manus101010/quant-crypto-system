"""Download Binance 5m OI metrics for top 150 coins, keep hourly OI (value at each hh:00 bar close)."""
import io, sys, zipfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np, pandas as pd, requests

sys.path.insert(0, "/home/claude/quant-crypto-system/research/my_edge")
import core as C

OUT = Path("/tmp/claude-0/-home-claude/f9afb357-b96a-5c99-93e3-0ac2bb39e920/scratchpad/edge2/forced/oi")
OUT.mkdir(parents=True, exist_ok=True)
START, END = pd.Timestamp("2022-12-25"), pd.Timestamp("2026-10-26")


def pick():
    rows = []
    for s in C.universe_symbols():
        k = pd.read_parquet(C.BUM / "k1h" / f"{s}.parquet", columns=["quote_volume"])
        k = k[(k.index >= START) & (k.index <= END)]
        if len(k) < 24 * 60:
            continue
        rows.append((s, k["quote_volume"].mean(), k.index[0], k.index[-1]))
    df = pd.DataFrame(rows, columns=["sym", "qv", "a", "b"]).sort_values("qv", ascending=False).head(150)
    df.to_csv(OUT.parent / "oi_coins.csv", index=False)
    return df


sess = requests.Session()
ad = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64)
sess.mount("https://", ad)


def fetch(args):
    sym, day = args
    url = f"https://data.binance.vision/data/futures/um/daily/metrics/{sym}/{sym}-metrics-{day:%Y-%m-%d}.zip"
    for t in range(3):
        try:
            r = sess.get(url, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            d = pd.read_csv(z.open(z.namelist()[0]), usecols=[0, 2, 3])
            d.columns = ["t", "oi", "oiv"]
            d["t"] = pd.to_datetime(d["t"])
            d = d[d["t"].dt.minute == 0]
            return d
        except Exception:
            time.sleep(1 + t)
    return None


def main():
    df = pick()
    with ThreadPoolExecutor(64) as ex:
        for n, r in enumerate(df.itertuples()):
            p = OUT / f"{r.sym}.parquet"
            if p.exists():
                continue
            days = pd.date_range(max(r.a.normalize(), START), min(r.b.normalize(), END), freq="D")
            parts = [x for x in ex.map(fetch, [(r.sym, d) for d in days]) if x is not None]
            if parts:
                o = pd.concat(parts).drop_duplicates("t").set_index("t").sort_index()
                o.to_parquet(p)
            print(n, r.sym, len(days), len(parts), flush=True)


if __name__ == "__main__":
    main()
