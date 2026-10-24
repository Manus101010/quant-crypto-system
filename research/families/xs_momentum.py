"""
Round 2 (#4): cross-sectional momentum and reversal across the MEXC perp universe.

Every Monday close, rank eligible coins (>= 200 days of history, >= $0.5M average
daily volume) by their return over the lookback, skipping the most recent day.
Hold for one week, equal weight, 1x gross per side.

Books per lookback (7, 28, 84 days):
  mom L/S   long top K, short bottom K   (dollar neutral)
  mom long  long top K only
  rev L/S   long bottom K, short top K   (short-term reversal)
Plus "mom L/S BTC-gated": only hold the book when BTC is above its 200 SMA.
Costs: 0.18% per side on every unit of weight that changes at a rebalance.

Run:  ./venv/bin/python research/families/xs_momentum.py history.pkl [report.md]
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.families.common import MIN_VOL_USD, load  # noqa: E402
from research.families.portfolio import HEAD, SIDE_COST, line  # noqa: E402

K = 5


def book(closes, eligible, look, kind, gate=None):
    rets = closes.pct_change()
    score = closes.shift(1) / closes.shift(1 + look) - 1          # skip the last day
    mondays = closes.index[closes.index.weekday == 0]
    w = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    cur = pd.Series(0.0, index=closes.columns)
    for d in closes.index:
        if d in mondays:
            s = score.loc[d][eligible.loc[d]].dropna()
            new = pd.Series(0.0, index=closes.columns)
            if len(s) >= 4 * K and (gate is None or bool(gate.get(d, False))):
                top, bot = s.nlargest(K).index, s.nsmallest(K).index
                if kind == "mom_ls":
                    new[top], new[bot] = 1 / K, -1 / K
                elif kind == "mom_long":
                    new[top] = 1 / K
                elif kind == "rev_ls":
                    new[bot], new[top] = 1 / K, -1 / K
            cur = new
        w.loc[d] = cur
    held = w.shift(1).fillna(0.0)
    gross = (held * rets.fillna(0.0)).sum(axis=1)
    turn = w.diff().abs().sum(axis=1).shift(1).fillna(0.0)
    return gross - turn * SIDE_COST


def main(path, out=None):
    coins, btc = load(path)
    closes = pd.DataFrame({s: df["close"] for s, df in coins.items()})
    qv = pd.DataFrame({s: (df["close"] * df["volume"]).rolling(20).mean() for s, df in coins.items()})
    age = closes.notna().cumsum()
    eligible = (age >= 200) & (qv >= MIN_VOL_USD) & closes.notna()
    bc = btc["close"].reindex(closes.index)
    gate = (bc > bc.rolling(200).mean())
    start = pd.Timestamp("2021-01-01")
    lines = [f"# Cross-sectional momentum / reversal (weekly, top/bottom {K}, 0.36% round trip)\n",
             f"Universe {len(coins)} coins, eligible = 200+ days of history and $0.5M daily volume.\n",
             HEAD]
    for look in (7, 28, 84):
        for kind, label in (("mom_ls", "mom L/S"), ("mom_long", "mom long only"), ("rev_ls", "rev L/S")):
            r = book(closes, eligible, look, kind)
            lines.append(line(f"{label} {look}d", r[r.index >= start]))
        r = book(closes, eligible, look, "mom_ls", gate)
        lines.append(line(f"mom L/S {look}d, only when BTC > 200 SMA", r[r.index >= start]))
    bh = bc.pct_change()
    lines.append(line("BTC buy and hold (reference)", bh[bh.index >= start]))
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
