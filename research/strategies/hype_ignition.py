"""
Hype ignition LONG: a coin (often a small cap or fresh listing) suddenly trades
several times its normal volume, prints a range far wider than usual, and closes
near the high at a fresh 20-day high. Works on young listings (40 days of history).
"""
from research.families.common import Plan

NAME = "Hype ignition long (volume + volatility expansion)"
SOURCE = "Manus: enter small caps showing hype, volume and volatility expansion"
HYPOTHESIS = ("Attention shocks on thin coins are under-reacted to on day one; late "
              "buyers keep arriving for days, so momentum continues after the ignition bar.")
DIRECTION = "long"
MIN_BARS = 40
MIN_QV = 0.2e6
PARAMS = [{"vol": 3.0, "rng": 1.5, "cap": "any"},
          {"vol": 5.0, "rng": 1.5, "cap": "any"},
          {"vol": 3.0, "rng": 2.0, "cap": "any"},
          {"vol": 3.0, "rng": 1.5, "cap": "small"},
          {"vol": 5.0, "rng": 2.0, "cap": "small"}]


def signal(x, vol=3.0, rng=1.5, cap="any"):
    span = (x["h"] - x["l"]).where(lambda s: s > 0)
    near_high = (x["c"] - x["l"]) / span >= 0.75
    s = ((x["volr"] >= vol) & (x["tr"] >= rng * x["atr"].shift(1)) & near_high
         & (x["c"] > x["hh20p"]) & (x["c"] > x["o"]))
    if cap == "small":
        s &= x["qvol20"].shift(1) < 5e6           # small before the ignition day
    return s


def plan(x, i, **_):
    c, a = float(x["c"].iat[i]), float(x["atr"].iat[i])
    return Plan("long", c - 2.0 * a, None, 2.5, 20)
