"""Round 1 pass: fade a sharp bounce in a coin that is below its 200 SMA, while BTC
is in a MIXED regime. Target the 20 EMA, stop just above the recent high."""
from research.families import exhaustion as E
from research.families.common import Plan  # noqa: F401  (plan comes from exhaustion)

NAME = "Downtrend bounce fade (short)"
SOURCE = "research/families/REPORT.md, round 1"
HYPOTHESIS = ("Relief rallies in downtrending coins are driven by short covering, not "
              "new demand; once volatility fades, sellers return.")
DIRECTION = "short"
MIN_BARS = 200
PARAMS = [{"Z": 2.0, "S": 2.5}, {"Z": 2.5, "S": 2.5}, {"Z": 2.0, "S": 3.0}, {"Z": 3.0, "S": 2.5}]


def signal(x, Z=2.0, S=2.5):
    s = E.signal("short", Z, S, 1.0, "none")(x)
    return s & (x["c"] < x["sma200"]) & (x["btc_regime"] == "MIXED")


def plan(x, i, **_):
    return E.plan("short", "ema20")(x, i)
