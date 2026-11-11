"""
Round 2 (#2): pairs mean reversion (market neutral: long one coin, short another).

Walk-forward, no lookahead:
  formation  every 90 days, look back 180 days over the 40 most liquid coins with
             history; keep pairs whose daily log-return correlation >= RHO and whose
             spread (log A - beta * log B, OLS beta) mean-reverts with a half-life of
             2 to 30 days. Up to 10 best pairs by correlation.
  trading    next 90 days only. z = spread vs its trailing 30-day mean / std.
             Enter when |z| >= ENTRY (short the rich leg, long the cheap leg, half the
             capital each), exit when z crosses 0, stop at |z| >= 4, or after 20 days.
Return per trade = 0.5 x long-leg return + 0.5 x short-leg return, minus 0.36%
(both legs' round trips on half the capital each).

Run:  ./venv/bin/python research/families/pairs.py history.pkl [report.md]
"""
from __future__ import annotations
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.families.common import HEADER, load, row, stats  # noqa: E402

COST = 0.36


def half_life(s: pd.Series) -> float:
    ds, lag = s.diff().dropna(), s.shift().dropna()
    lag = lag.loc[ds.index]
    b = np.polyfit(lag.values, ds.values, 1)[0]
    return -np.log(2) / b if b < 0 else np.inf


def run(closes, qv, rho, entry):
    logp = np.log(closes)
    trades = []
    days = closes.index
    for f0 in range(400, len(days) - 30, 90):
        fdays = days[f0 - 180:f0]
        liq = qv.iloc[f0].dropna()
        uni = [s for s in liq.nlargest(40).index if closes[s].loc[fdays].notna().all()]
        if len(uni) < 10:
            continue
        lr = logp[uni].loc[fdays].diff().dropna()
        corr = lr.corr()
        cands = []
        for a, b in itertools.combinations(uni, 2):
            if corr.loc[a, b] < rho:
                continue
            beta = np.polyfit(logp[b].loc[fdays], logp[a].loc[fdays], 1)[0]
            hl = half_life(logp[a].loc[fdays] - beta * logp[b].loc[fdays])
            if 2 <= hl <= 30:
                cands.append((corr.loc[a, b], a, b, beta))
        for _, a, b, beta in sorted(cands, reverse=True)[:10]:
            spread = logp[a] - beta * logp[b]
            z = (spread - spread.rolling(30).mean()) / spread.rolling(30).std()
            i, end = f0, min(f0 + 90, len(days) - 1)
            while i < end:
                zi = z.iat[i]
                if not np.isfinite(zi) or abs(zi) < entry:
                    i += 1; continue
                long_a = zi < 0                                   # A cheap vs B
                j = i + 1
                while j < min(i + 21, len(days) - 1):
                    zj = z.iat[j]
                    if (long_a and zj >= 0) or (not long_a and zj <= 0) or abs(zj) >= 4:
                        break
                    j += 1
                ra = closes[a].iat[j] / closes[a].iat[i] - 1
                rb = closes[b].iat[j] / closes[b].iat[i] - 1
                ret = 100 * (0.5 * ra - 0.5 * rb if long_a else 0.5 * rb - 0.5 * ra) - COST
                trades.append({"ret_pct": ret, "r_mult": ret, "entry": days[i], "exit": days[j],
                               "bars": j - i, "pair": f"{a}/{b}"})
                i = j + 1
    return trades


def main(path, out=None):
    coins, _ = load(path)
    closes = pd.DataFrame({s: df["close"] for s, df in coins.items()})
    qv = pd.DataFrame({s: (df["close"] * df["volume"]).rolling(60).mean() for s, df in coins.items()})
    lines = ["# Pairs mean reversion (walk-forward, market neutral)\n",
             "'expR' and 'totR' are mean / total % return per trade on the capital used.\n", HEADER]
    for rho in (0.7, 0.8):
        for entry in (2.0, 2.5):
            tr = run(closes, qv, rho, entry)
            lines.append(row(f"corr>={rho} entry |z|>={entry}", stats(tr)))
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
