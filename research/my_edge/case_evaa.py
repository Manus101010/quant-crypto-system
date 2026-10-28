"""EVAAUSDT case study (live example from the trader, 28 Oct 2026).
Binance 1h cache ends 26 Oct, so recent bars come from MEXC public 1h (cross checked
against Bitget: same high 1.6000 at 15:00 UTC). Runs the version A detectors and the
exits on that chart. Universe volume filter is ignored here (it is a single chart).
Run: python research/my_edge/case_evaa.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core as C          # noqa: E402
import setups as S        # noqa: E402

D = Path(__file__).resolve().parent / "data"


def main():
    m = pd.read_csv(D / "EVAAUSDT_1h_mexc.csv", parse_dates=["t"]).set_index("t")
    m = m.rename(columns={"volume": "volume"})
    b = pd.read_parquet(C.BUM / "k1h" / "EVAAUSDT.parquet")
    b = b[b.index < m.index[0]][["open", "high", "low", "close", "volume"]]
    k = pd.concat([b, m[["open", "high", "low", "close", "volume"]]]).sort_index()
    k = k[~k.index.duplicated(keep="last")]
    k = k.reindex(pd.date_range(k.index[0], k.index[-1], freq="1h"))
    k["quote_volume"] = k["volume"] * k["close"]
    k["fund"] = 0.0
    k["dvol30"] = 1e12           # single chart: no universe filter
    k["age_h"] = np.arange(len(k))
    sig, _ = S.signals(k)
    o, h, l, c, f = (k[x].to_numpy() for x in ("open", "high", "low", "close", "fund"))
    since = pd.Timestamp("2026-10-27 12:00")
    print("bars to", k.index[-1] + pd.Timedelta(hours=1), "close", c[-1])
    print("Version A entries that fired after 27 Oct 12:00 UTC (time = bar close, UTC):")
    rows = []
    for en, (ii, side, stops) in sig.items():
        if not en.startswith("A|"):
            continue
        for i, st in zip(ii, stops):
            tc = k.index[i] + pd.Timedelta(hours=1)
            if tc < since:
                continue
            sp = (st - c[i]) / c[i]
            rr = {"entry": en, "t_close_utc": tc, "px": c[i], "stop": st, "stop_pct": sp * 100,
                  "valid_stop": C.MIN_STOP <= sp <= C.MAX_STOP}
            for xn, (a, tr) in {"act3_tr5": (0.03, 0.05), "act0_tr3": (0.0, 0.03), "act2_tr7": (0.02, 0.07)}.items():
                j, net, _, code, _ = C.sim(o, h, l, c, f, int(i), -1, float(st), a, tr, np.nan, 168, 0.0036, False)
                rr[xn] = f"{(net)/sp:+.2f}R ({net*100:+.1f}%) {['stop','trail','tgt','time','dead','OPEN'][code if code < 6 else 3]} @{k.index[j]+pd.Timedelta(hours=1):%d %H:%M}"
            rows.append(rr)
    df = pd.DataFrame(rows).sort_values("t_close_utc")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 20)
    print(df.to_string(index=False))
    df.to_csv(Path(__file__).resolve().parent / "results" / "case_evaa.csv", index=False)
    # run up condition snapshot at the trader's moment
    t0 = pd.Timestamp("2026-10-28 12:00")
    i0 = k.index.get_loc(t0)
    lo7 = k["low"].iloc[i0 - 24 * 7:i0].min()
    print(f"\nat 28 Oct 13:00 UTC close {c[i0]:.4f}; 72h peak {k['high'].iloc[i0-71:i0+1].max():.4f}; "
          f"7d base {lo7:.4f}; run up {k['high'].iloc[i0-71:i0+1].max()/lo7-1:+.0%}")


if __name__ == "__main__":
    main()
