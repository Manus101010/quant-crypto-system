"""Round 1 pass: a coin that was in a downtrend coils (Bollinger width in the bottom
10 to 20% of 180 days), then closes above its 20-day high on 1.5x+ volume. Long
ONLY while BTC is in an UP regime. Stop 1 ATR under the breakout level, trail 3 ATR."""
import numpy as np
import pandas as pd

from research.families.breakout import events, plan_for

NAME = "Compression breakout long (BTC up only)"
SOURCE = "research/families/REPORT.md, round 1"
HYPOTHESIS = ("Coins basing after a decline break out hard once the market turns, "
              "because sidelined buyers return at the same time; in a weak market "
              "the same breakouts fail.")
DIRECTION = "long"
MIN_BARS = 200
PARAMS = [{"P": 0.10, "V": 1.5}, {"P": 0.20, "V": 1.5}, {"P": 0.10, "V": 2.0}, {"P": 0.15, "V": 1.5}]

_LEVELS: dict = {}


def signal(x, P=0.10, V=1.5):
    s = pd.Series(False, index=x.index)
    for i, level, _ in events(x, "long", P, V, "post-trend", "fired"):
        s.iat[i] = True
        _LEVELS[(id(x), i)] = level
    return s & (x["btc_regime"] == "UP")


def plan(x, i, **_):
    level = _LEVELS.get((id(x), i), float(x["hh20p"].iat[i]))
    return plan_for(x, i, "long", "struct", level, np.nan)
