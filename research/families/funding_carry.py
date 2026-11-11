"""
Round 2 (#6): funding carry. Long spot + short the same coin's MEXC perpetual,
collecting funding while it is positive. Price risk cancels; you earn funding.

Data: MEXC funding history (starts ~Apr 2025), summed into 8-hour buckets.
Rule: at each 8h bucket, hold up to N coins whose trailing 3-day average funding is
>= THR, choosing the highest. Each position = 1/N of capital, and every $1 of
hedged notional needs $1.33 of capital ($1 spot + $0.33 perp margin at 3x).
Costs: 0.2% per side for the two legs together (spot taker + perp + slippage),
charged on entry and exit. Basis moves and venue risk are NOT modelled.

Run:  ./venv/bin/python research/families/funding_carry.py funding.pkl report.md history.pkl 20e6
      (last two args restrict to coins with >= $20M daily volume)
"""
from __future__ import annotations
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CAP_PER_NOTIONAL = 1.33
SIDE_COST = 0.002


def buckets(fr: dict) -> pd.DataFrame:
    cols = {}
    for sym, s in fr.items():
        if s is None or not len(s):
            continue
        cols[sym] = s.groupby(s.index.floor("8h")).sum()
    return pd.DataFrame(cols).sort_index().fillna(0.0)


def run(F: pd.DataFrame, n: int, thr: float, min_hold: int = 0):
    trail = F.rolling(9).mean().shift(1)                      # known before the bucket
    held: set = set()
    age: dict = {}
    out = []
    for t in F.index[9:]:
        cand = trail.loc[t][trail.loc[t] >= thr].nlargest(n)
        want = set(cand.index)
        keep = {s for s in held if age.get(s, 0) < min_hold and trail.loc[t, s] > 0}
        want = set(list((want | keep)))
        if len(want) > n:
            want = set(sorted(want, key=lambda s: -trail.loc[t, s])[:n])
        changes = len(want ^ held)
        r = sum(F.loc[t, s] for s in want) / n / CAP_PER_NOTIONAL
        r -= changes * SIDE_COST / n / CAP_PER_NOTIONAL
        for s in want:
            age[s] = age.get(s, 0) + 1 if s in held else 1
        held = want
        out.append((t, r, len(want)))
    return pd.DataFrame(out, columns=["t", "r", "n"]).set_index("t")


def liquid_only(F: pd.DataFrame, hist_path: str, min_qv: float) -> pd.DataFrame:
    """Zero out funding for coins below `min_qv` 20-day average daily volume that day:
    the highest-funding coins are mostly illiquid microcaps that squeeze 30%+ and
    would liquidate the short leg."""
    coins = pickle.loads(Path(hist_path).read_bytes())["coins"]
    out = F.copy()
    for sym in F.columns:
        df = coins.get(sym)
        if df is None:
            out[sym] = 0.0; continue
        qv = (df["close"] * df["volume"]).rolling(20).mean()
        qv.index = pd.DatetimeIndex(qv.index).normalize()
        ok = qv.reindex(F.index.normalize()).fillna(0).values >= min_qv
        out[sym] = F[sym].where(ok, 0.0)
    return out


def main(path, out=None, hist_path=None, min_qv=0.0):
    F = buckets(pickle.loads(Path(path).read_bytes()))
    if hist_path and min_qv:
        F = liquid_only(F, hist_path, min_qv)
    lines = [f"# Funding carry: long spot + short perp (MEXC funding since Apr 2025), coins with >= ${min_qv/1e6:.0f}M daily volume\n",
             f"{F.shape[1]} coins, {F.index.min().date()} to {F.index.max().date()}. "
             "Yield is on total capital including spot and perp margin, net of costs.\n",
             "\n| coins held | min trailing funding (per 8h) | min hold | annual yield | yield 1st half | yield 2nd half | avg coins held | $ per year on $500 |",
             "|---|---|---|---|---|---|---|---|"]
    per_year = 3 * 365
    for n in (1, 3, 5):
        for thr in (0.0001, 0.0003, 0.0005):
            for mh in (0, 9):
                d = run(F, n, thr, mh)
                ann = d["r"].mean() * per_year * 100
                m = len(d) // 2
                a, b = d["r"].iloc[:m].mean() * per_year * 100, d["r"].iloc[m:].mean() * per_year * 100
                lines.append(f"| {n} | {thr*100:.2f}% | {mh // 3} days | {ann:+.1f}% | {a:+.1f}% | {b:+.1f}% | "
                             f"{d['n'].mean():.1f} | ${ann * 5:+.2f} |")
    med = F.where(F != 0).stack().median()
    lines.append(f"\nMedian funding per 8h across all coins and buckets: {med*100:+.4f}% "
                 f"({med*per_year*100:+.1f}% a year).")
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text)
    print(text)


if __name__ == "__main__":
    a = sys.argv
    main(a[1], a[2] if len(a) > 2 else None, a[3] if len(a) > 3 else None,
         float(a[4]) if len(a) > 4 else 0.0)
