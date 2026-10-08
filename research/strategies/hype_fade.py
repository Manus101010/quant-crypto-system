"""
Post-hype FADE short: a coin that has pumped hard (+100% or more off its recent
low) has peaked, volume has dried up, and price has rolled over. The bagholders
are trapped and new buyers are gone. Works on young listings (40 days of history).
"""
from research.families.common import Plan

NAME = "Post-hype fade short (pump, peak, volume taper, roll-over)"
SOURCE = "Manus: small caps that taper off after hype make excellent shorts"
HYPOTHESIS = ("After an attention-driven pump, demand is exhausted while unlocks, "
              "early holders and trapped buyers keep supplying; price mean-reverts "
              "toward the pre-pump level.")
DIRECTION = "short"
MIN_BARS = 40
MIN_QV = 0.2e6
PARAMS = [{"pump": 1.0, "taper": 0.4},
          {"pump": 2.0, "taper": 0.4},
          {"pump": 1.0, "taper": 0.6},
          {"pump": 0.7, "taper": 0.4},
          {"pump": 1.0, "taper": 0.3}]


def signal(x, pump=1.0, taper=0.4):
    hi30 = x["h"].rolling(30).max()
    lo60 = x["l"].rolling(60, min_periods=30).min()
    pumped = hi30 / lo60 - 1 >= pump
    bars_since_peak = x["h"].rolling(30).apply(lambda w: len(w) - 1 - w.argmax(), raw=True)
    peaked = bars_since_peak.between(3, 20)
    vol5 = x["qv"].rolling(5).mean()                          # 5-day avg $ volume
    tapered = vol5 <= taper * vol5.rolling(30).max()          # vs its 30-day peak
    rolled = (x["c"] <= 0.8 * hi30) & (x["c"] < x["ema9"])
    return pumped & peaked & tapered & rolled


def plan(x, i, **_):
    c, a = float(x["c"].iat[i]), float(x["atr"].iat[i])
    return Plan("short", c + 2.5 * a, None, 3.0, 30)
