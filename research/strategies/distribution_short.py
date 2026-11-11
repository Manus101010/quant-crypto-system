"""Round 1 pass: after a big run-up, volatility compresses (Bollinger width in the
bottom 10 to 20% of 180 days) and price sits in the lower half of its 20-day range.
Short the first coiled bar; not when BTC is trending DOWN. Trailing stop."""
import numpy as np
import pandas as pd

from research.families.breakout import events, plan_for

NAME = "Distribution short (coil after a run-up)"
SOURCE = "research/families/REPORT.md, round 1"
HYPOTHESIS = ("After a strong run, a tight range with price slipping to its lower half "
              "is supply absorbing demand; the next expansion tends to be down.")
DIRECTION = "short"
MIN_BARS = 200
PARAMS = [{"P": 0.10, "M": "trail"}, {"P": 0.20, "M": "trail"},
          {"P": 0.10, "M": "struct"}, {"P": 0.15, "M": "trail"}]


def signal(x, P=0.10, M="trail"):
    s = pd.Series(False, index=x.index)
    for i, _, _ in events(x, "short", P, 1.5, "post-trend", "prepos"):
        s.iat[i] = True
    return s & (x["btc_regime"] != "DOWN")


def plan(x, i, P=0.10, M="trail"):
    edge = float(x["hh20p"].iat[i])
    return plan_for(x, i, "short", M, np.nan, edge)
