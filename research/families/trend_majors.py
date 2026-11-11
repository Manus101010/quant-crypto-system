"""
Round 2 (#3): trend following on the majors only (BTC, ETH, SOL), 1x, daily,
0.36% round-trip cost on every position change. Compared with buy and hold.

Rules
  sma200      long when close > 200 SMA, else flat
  x20/100 LF  long when 20 SMA > 100 SMA, else flat
  x20/100 LS  long when 20 > 100, short when below
  don55/20 LF Turtle: enter long on a 55-day high close, exit on a 20-day low close
  don55/20 LS same, plus the mirror short
  tsmom90 LF  long when the 90-day return is positive, else flat
  tsmom90 LS  long when positive, short when negative
Leverage scales return and drawdown roughly linearly, so read these as 1x.

Run:  ./venv/bin/python research/families/trend_majors.py history.pkl [report.md]
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.families.common import load  # noqa: E402
from research.families.portfolio import HEAD, line, run_positions  # noqa: E402


def donchian(c, h, l, short: bool):
    hi, lo = h.rolling(55).max().shift(1), l.rolling(55).min().shift(1)
    xlo, xhi = l.rolling(20).min().shift(1), h.rolling(20).max().shift(1)
    pos, p = [], 0.0
    for i in range(len(c)):
        if p == 0:
            if c.iat[i] > hi.iat[i]:
                p = 1.0
            elif short and c.iat[i] < lo.iat[i]:
                p = -1.0
        elif p > 0 and c.iat[i] < xlo.iat[i]:
            p = -1.0 if (short and c.iat[i] < lo.iat[i]) else 0.0
        elif p < 0 and c.iat[i] > xhi.iat[i]:
            p = 1.0 if c.iat[i] > hi.iat[i] else 0.0
        pos.append(p)
    return pd.Series(pos, index=c.index)


def rules(df):
    c, h, l = df["close"], df["high"], df["low"]
    s20, s100, s200 = c.rolling(20).mean(), c.rolling(100).mean(), c.rolling(200).mean()
    m90 = c / c.shift(90) - 1
    return {
        "buy and hold":  pd.Series(1.0, index=c.index),
        "sma200 LF":     (c > s200).astype(float),
        "x20/100 LF":    (s20 > s100).astype(float),
        "x20/100 LS":    np.sign(s20 - s100).fillna(0.0),
        "don55/20 LF":   donchian(c, h, l, False),
        "don55/20 LS":   donchian(c, h, l, True),
        "tsmom90 LF":    (m90 > 0).astype(float),
        "tsmom90 LS":    np.sign(m90).fillna(0.0),
    }


def main(path, out=None):
    coins, btc = load(path)
    assets = {"BTC": btc, "ETH": coins.get("ETH-USD"), "SOL": coins.get("SOL-USD")}
    start = pd.Timestamp("2021-01-01")       # every rule has its 200 days of warm-up by then
    lines = ["# Trend following on the majors (1x, daily, 0.36% round trip)\n",
             f"Period {start.date()} to latest. Sharpe uses 365 days.\n"]
    basket: dict[str, list] = {}
    for name, df in assets.items():
        if df is None:
            continue
        lines += [f"\n## {name}\n", HEAD]
        for rn, pos in rules(df).items():
            r = run_positions(df["close"], pos)
            r = r[r.index >= start]
            basket.setdefault(rn, []).append(r)
            lines.append(line(rn, r))
    lines += ["\n## Equal-weight basket of BTC, ETH, SOL\n", HEAD]
    for rn, rs in basket.items():
        lines.append(line(rn, pd.concat(rs, axis=1).fillna(0).mean(axis=1)))
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
