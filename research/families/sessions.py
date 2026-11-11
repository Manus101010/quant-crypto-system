"""
Round 2 (#5): session and weekday effects on hourly bars (60 most liquid coins,
Jun 2024 onward). Average hourly return and average hourly range by UTC hour and
by weekday, pooled across coins, with t-stats on the mean return. The weekend vs
weekday GRID comparison lives in grids_5m.py.

Run:  ./venv/bin/python research/families/sessions.py hourly.pkl [report.md]
"""
from __future__ import annotations
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def main(path, out=None):
    h = pickle.loads(Path(path).read_bytes())
    rows = []
    for sym, df in h.items():
        r = np.log(df["close"]).diff()
        rng = (df["high"] - df["low"]) / df["open"]
        rows.append(pd.DataFrame({"r": r, "rng": rng, "hour": df.index.hour,
                                  "wd": df.index.weekday, "sym": sym}).dropna())
    d = pd.concat(rows)
    # de-mean each coin so a coin's trend does not leak into every hour
    d["r"] = d["r"] - d.groupby("sym")["r"].transform("mean")

    # Coins move together, so pooled coin-hours overstate significance. The t-stat
    # below uses ONE cross-coin average per timestamp, which is the honest version.
    ts = d.groupby(level=0).agg(r=("r", "mean"), rng=("rng", "mean"))
    ts["hour"], ts["wd"] = ts.index.hour, ts.index.weekday

    def tab(key, labels):
        g = ts.groupby(key)
        m, s, n, rg = g["r"].mean(), g["r"].std(), g["r"].count(), g["rng"].mean()
        lines = [f"| {key} | mean excess return (bp) | t-stat | avg range (bp) |", "|---|---|---|---|"]
        for k in m.index:
            t = m[k] / (s[k] / np.sqrt(n[k]))
            lines.append(f"| {labels(k)} | {m[k]*1e4:+.2f} | {t:+.1f} | {rg[k]*1e4:.0f} |")
        return lines

    wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    lines = ["# Session and weekday effects (hourly, cross-coin average per hour, each coin de-meaned)\n",
             f"{len(h)} coins, {d.shape[0]:,} coin-hours.\n", "\n## By UTC hour\n"]
    lines += tab("hour", lambda k: f"{k:02d}:00 UTC ({(k + 11) % 24:02d}:00 Sydney)")
    lines += ["\n## By weekday (UTC)\n"] + tab("wd", lambda k: wd[k])
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
