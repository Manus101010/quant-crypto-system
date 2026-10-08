"""
Family C add-on: SQUEEZE FUEL. Does crowded positioning (funding) make breakouts
better? Uses MEXC perpetual funding history, which only goes back to ~April 2025,
so this is a SHORT sample (it does include the Oct 2025 crash and the 2026 bear).
Open interest history is not available far enough back from MEXC to test at all.

For every FIRED breakout (long) / breakdown (short) from breakout.py, the average
funding over the 3 days before the fire is recorded, then results are split:
  long  breakouts: funding < 0 (shorts paying, crowded short)  vs  >= 0
  short breakdowns: funding > +0.01% per 8h (crowded long)     vs  <= +0.01%

Run:  ./venv/bin/python research/families/squeeze.py history.pkl [report.md]
"""
from __future__ import annotations
import pickle
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.families.breakout import run  # noqa: E402
from research.families.common import HEADER, by, prepare, row, stats  # noqa: E402

URL = "https://contract.mexc.com/api/v1/contract/funding_rate/history"


def funding(base: str) -> pd.Series | None:
    rows, page, fails = [], 1, 0
    while True:
        try:
            r = requests.get(URL, params={"symbol": f"{base}_USDT", "page_num": page,
                                          "page_size": 1000}, timeout=10).json()
        except Exception:                               # noqa: BLE001
            fails += 1
            if fails > 3:
                break                                   # give up on this coin, keep partial
            time.sleep(2); continue
        d = r.get("data") or {}
        rows += d.get("resultList") or []
        if page >= (d.get("totalPage") or 0):
            break
        page += 1
        time.sleep(0.05)
    if not rows:
        return None
    s = pd.Series({pd.Timestamp(x["settleTime"], unit="ms"): x["fundingRate"] for x in rows})
    return s.sort_index()


def funding_all(syms, cache: Path) -> dict:
    got = pickle.loads(cache.read_bytes()) if cache.exists() else {}
    for k, sym in enumerate(syms, 1):
        if sym not in got:
            got[sym] = funding(sym.replace("-USD", ""))
            if k % 25 == 0:
                cache.write_bytes(pickle.dumps(got))
    cache.write_bytes(pickle.dumps(got))
    return got


def main(path, out=None):
    ind, _ = prepare(path)
    fr = funding_all(list(ind), Path(path).with_name("funding.pkl"))
    start = min((s.index.min() for s in fr.values() if s is not None and len(s)), default=None)
    lines = ["# Squeeze fuel: funding before breakouts\n",
             f"Funding history from {start.date() if start is not None else 'n/a'} (MEXC). "
             "Only breakouts after that date are counted.\n"]

    def f3(t):
        s = fr.get(t["sym"])
        if s is None:
            return None
        w = s[(s.index < t["entry"] + pd.Timedelta(days=1)) & (s.index >= t["entry"] - pd.Timedelta(days=2))]
        return float(w.mean()) if len(w) else None

    for direction in ("long", "short"):
        for ctx in ("post-trend", "any"):
            tr = run(ind, direction, 0.20, 1.5, ctx, "fired", "trail")
            tr = [dict(t, fund=f3(t)) for t in tr]
            tr = [t for t in tr if t["fund"] is not None]
            lines += [f"\n## {direction} fired, coil20 vol1.5 {ctx}, trail (since funding exists)\n", HEADER,
                      row("all", stats(tr))]
            if direction == "long":
                g = by(tr, lambda t: "funding < 0 (crowded short)" if t["fund"] < 0 else "funding >= 0")
            else:
                g = by(tr, lambda t: "funding > +0.01% (crowded long)" if t["fund"] > 1e-4 else "funding <= +0.01%")
            for k, v in sorted(g.items()):
                lines.append(row(k, stats(v)))
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
