"""
Sensitivity check: how much does 5m OHLC understate grid fills vs 1m?

Fetches the last ~30 days of OKX USDT-swap 1m candles for a few coins (cached),
resamples them to 5m, runs the SAME grid entries on both and compares PF and
mean grid profit. If 1m is much better, the 5m sweep is biased against grids.

Run:  python research/grid/check_1m.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.grid.sim import MAKER_FEE, MMR, MODES, OK, SLIPPAGE, TAKER_FEE, run_batch  # noqa: E402
from research.grid.run import _atr  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache"
COINS = ["BTC", "ETH", "SOL", "DOGE", "XRP", "SUI", "WLD", "PENGU"]
DAYS = 30


def fetch_1m(base: str) -> pd.DataFrame | None:
    p = CACHE / f"okx1m_{base}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    import ccxt
    opts = {"enableRateLimit": True, "timeout": 20000}
    if os.environ.get("HTTPS_PROXY"):
        opts["httpsProxy"] = os.environ["HTTPS_PROXY"]
    ex = ccxt.okx(opts)
    end = int(time.time() * 1000) // 60_000 * 60_000
    cur = end - DAYS * 86_400_000
    rows = []
    while cur < end:
        b = None
        for i in range(4):
            try:
                b = ex.fetch_ohlcv(f"{base}/USDT:USDT", "1m", since=cur, limit=300)
                break
            except Exception:                      # noqa: BLE001
                time.sleep(1 + i)
        if not b:
            break
        rows += b
        nxt = b[-1][0] + 60_000
        if nxt <= cur:
            break
        cur = nxt
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).drop_duplicates("ts")
    df.index = pd.to_datetime(df.pop("ts"), unit="ms")
    df = df.sort_index().astype(float)
    df.to_parquet(p)
    return df


def run(df: pd.DataFrame, pos: np.ndarray, lo, hi, n, mode, lev, hold_bars):
    a = [np.ascontiguousarray(df[k].to_numpy(np.float64)) for k in ("open", "high", "low", "close")]
    out = run_batch(*a, np.zeros(len(df)), pos, lo, hi, n, MODES[mode], False, 50.0, float(lev),
                    0.002, mode != "neutral", hold_bars, 12.5, 2.0, MMR, MAKER_FEE, TAKER_FEE,
                    SLIPPAGE, False)
    return out[out[:, 0] == OK]


def main() -> None:
    res = []
    for base in COINS:
        m1 = fetch_1m(base)
        if m1 is None or len(m1) < 10_000:
            print(base, "no 1m data")
            continue
        m5 = m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        h = m1.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        atr = _atr(h)
        t = h.index[30::6]                          # an entry every 6h after warm-up
        for mode in ("neutral", "short"):
            for n in (20, 50, 100, 200):
                for width in (8, 32):
                    w = width * atr.reindex(t).to_numpy()
                    t1 = t + pd.Timedelta(hours=1)
                    p5 = m5.index.searchsorted(t1)
                    p1 = m1.index.searchsorted(t1)
                    ok = (p5 < len(m5) - 300) & (p1 < len(m1) - 1500)
                    o = m5["open"].to_numpy()[p5[ok]]
                    if mode == "neutral":
                        lo, hi = o - w[ok] / 2, o + w[ok] / 2
                    else:
                        lo, hi = o - 2 * w[ok] / 3, o + w[ok] / 3
                    r5 = run(m5, p5[ok].astype(np.int64), lo, hi, n, mode, 3, 24 * 12)
                    # 1m: same levels, same start price (open of the same 5m bar)
                    r1 = run(m1, p1[ok].astype(np.int64), lo, hi, n, mode, 3, 24 * 60)
                    res.append({"coin": base, "mode": mode, "grids": n, "width": width,
                                "n5": len(r5), "n1": len(r1),
                                "pnl5": r5[:, 3].sum(), "pnl1": r1[:, 3].sum(),
                                "grid5": r5[:, 4].sum(), "grid1": r1[:, 4].sum()})
    d = pd.DataFrame(res)
    g = d.groupby(["mode", "grids", "width"])[["n5", "n1", "pnl5", "pnl1", "grid5", "grid1"]].sum()
    g["grid_ratio_1m_vs_5m"] = g["grid1"] / g["grid5"]
    g["exp_r_5m"] = g["pnl5"] / g["n5"] / 12.5
    g["exp_r_1m"] = g["pnl1"] / g["n1"] / 12.5
    out = Path(__file__).resolve().parent / "results" / "check_1m.csv"
    g.round(4).to_csv(out)
    print(g.round(3).to_string())


if __name__ == "__main__":
    main()
