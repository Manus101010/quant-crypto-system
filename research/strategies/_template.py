"""
TEMPLATE for a strategy module. Copy to research/strategies/<slug>.py, fill in,
then run:  ./venv/bin/python research/intake/run.py <slug> history.pkl

Rules that keep results honest
  * signal(x) may only use data up to and including bar t (no .shift(-1), no
    centred windows, no "security(..., lookahead_on)" equivalents from Pine).
  * Entry happens on the CLOSE of the signal bar (the harness does this).
  * PARAMS: list the published settings FIRST, then a few neighbours
    (e.g. +/-20%). Do not tune dozens of values; every variant counts toward the
    multiple-testing bar for all future strategies.

Columns available in x (daily): o h l c, tr atr tr3, ema9 ema20 sma20 sma50 sma200,
rsi14, z5 (5d return z vs 90d), ret120, bbw bbw_pct, hh20p ll20p hh55p ll55p
(prior-bar channels), volr (volume / prior 20d avg), qvol20 ($ volume 20d avg),
er20 (efficiency ratio), stretch ((c - ema20) / atr), btc_regime (UP/MIXED/DOWN),
btc_up_200_50, breadth50.  Plan(direction, stop, target_or_None, trail_atr_or_None, max_hold).
"""
from research.families.common import Plan

NAME = "Example: 20-day breakout"
SOURCE = "where the idea came from (URL / Pine script / paper)"
HYPOTHESIS = "why it should work: who is on the other side of the trade"
DIRECTION = "long"            # "long" | "short"
MIN_BARS = 200                # history needed before the first signal
MIN_QV = 0.5e6                # minimum 20-day average daily $ volume
PARAMS = [{"vol": 2.0}, {"vol": 1.5}, {"vol": 2.5}]


def signal(x, vol=2.0):
    return (x["c"] > x["hh20p"]) & (x["volr"] >= vol)


def plan(x, i, vol=2.0):
    c, a = float(x["c"].iat[i]), float(x["atr"].iat[i])
    return Plan("long", c - 2 * a, None, 3.0, 30)
