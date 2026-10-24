"""
Family C: COMPRESSION BREAKOUTS after a trend (staged), plus mirrored breakdowns.

LONG (the "violent breakout after a bear" idea):
  context   "post-down": the coin fell >= 30% over the previous 120 days, or 50 SMA < 200 SMA
  COILED    Bollinger width in the bottom P of its last 180 days
  FIRED     close above the prior 20-day high on >= V x average volume, coiled within the last 10 bars
  CONFIRMED after a FIRE, within 7 bars price retests to within 0.5 ATR of the breakout
            level and closes back above it (a close more than 1 ATR below the level kills it)
  PREPOS    enter on the first COILED bar while price is in the upper half of its 20-day range
SHORT mirrors everything after an up move (rose >= 50% over 120 days, or 50 > 200 SMA).

Management (breakouts must be allowed to run):
  "trail"  initial stop 3.5 ATR, trailing 3.5 ATR on closes, 60 bars (production _TRAIL)
  "struct" stop just beyond the range (prepos) or 1 ATR beyond the breakout level,
           then a 3 ATR trail, 60 bars

A control row reruns the production "Donchian Breakout (55d)" idea (55-day high above
the 200 SMA) under this harness, as a sanity check against the live validation (PF 1.27).

Run:  ./venv/bin/python research/families/breakout.py history.pkl [report.md]
"""
from __future__ import annotations
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.families.common import (HEADER, MIN_VOL_USD, Plan, apply_costs, by,  # noqa: E402
                                      prepare, row, simulate, stats, tag)

PS, VS, CTX, STAGES, MS = (0.10, 0.20), (1.5, 2.0), ("post-trend", "any"), \
    ("prepos", "fired", "confirmed"), ("trail", "struct")


def _context(x, direction, ctx):
    if ctx == "any":
        return pd.Series(True, index=x.index)
    if direction == "long":
        return (x["ret120"] <= -0.30) | (x["sma50"] < x["sma200"])
    return (x["ret120"] >= 0.50) | (x["sma50"] > x["sma200"])


def events(x, direction, P, V, ctx, stage):
    """Return list of (entry_index, level, range_edge) for one coin."""
    long = direction == "long"
    coiled = (x["bbw_pct"] <= P) & _context(x, direction, ctx)
    out = []
    if stage == "prepos":
        mid = (x["hh20p"] + x["ll20p"]) / 2
        side = (x["c"] > mid) if long else (x["c"] < mid)
        first = coiled & ~coiled.shift(fill_value=False)
        for i in np.flatnonzero((first & side).values):
            edge = x["ll20p"].iat[i] if long else x["hh20p"].iat[i]
            out.append((i, np.nan, float(edge)))
        return out
    recent_coil = coiled.rolling(10).max().shift(1).fillna(0).astype(bool)
    brk = (x["c"] > x["hh20p"]) if long else (x["c"] < x["ll20p"])
    fired = brk & (x["volr"] >= V) & recent_coil
    for f in np.flatnonzero(fired.values):
        level = float(x["hh20p"].iat[f] if long else x["ll20p"].iat[f])
        if stage == "fired":
            out.append((f, level, np.nan)); continue
        a = float(x["atr"].iat[f])
        for j in range(f + 1, min(f + 8, len(x))):
            c, lo, hi = x["c"].iat[j], x["l"].iat[j], x["h"].iat[j]
            if (long and c < level - a) or (not long and c > level + a):
                break                                    # failed breakout
            touched = (lo <= level + 0.5 * a) if long else (hi >= level - 0.5 * a)
            held = (c >= level) if long else (c <= level)
            if touched and held:
                out.append((j, level, np.nan)); break
    return out


def plan_for(x, i, direction, M, level, edge):
    c, a = float(x["c"].iat[i]), float(x["atr"].iat[i])
    long = direction == "long"
    if M == "trail":
        return Plan(direction, c - 3.5 * a if long else c + 3.5 * a, None, 3.5, 60)
    if np.isfinite(edge):
        stop = edge - 0.25 * a if long else edge + 0.25 * a
    else:
        stop = level - a if long else level + a
    if (long and stop >= c) or (not long and stop <= c):
        return None
    return Plan(direction, stop, None, 3.0, 60)


def run(ind, direction, P, V, ctx, stage, M):
    trades = []
    for sym, x in ind.items():
        busy = -1
        for i, level, edge in events(x, direction, P, V, ctx, stage):
            if i <= busy or i < 200 or x["qvol20"].iat[i] < MIN_VOL_USD:
                continue
            p = plan_for(x, i, direction, M, level, edge)
            if p is None:
                continue
            t = simulate(x, i, p)
            if t is None:
                continue
            t.update(tag(x, i)); t["sym"] = sym
            busy = i + t["bars"]
            trades.append(t)
    return apply_costs(trades)


def control(ind):
    trades = []
    for sym, x in ind.items():
        sig = (x["c"] >= x["hh55p"]) & (x["c"] > x["sma200"]) & (x["rsi14"] < 82)
        busy = -1
        for i in np.flatnonzero(sig.fillna(False).values):
            if i <= busy or i < 200 or x["qvol20"].iat[i] < MIN_VOL_USD:
                continue
            c, a = float(x["c"].iat[i]), float(x["atr"].iat[i])
            t = simulate(x, i, Plan("long", c - 3.5 * a, None, 3.5, 60))
            if t:
                t.update(tag(x, i)); busy = i + t["bars"]; trades.append(t)
    return apply_costs(trades)


def main(path, out=None):
    ind, _ = prepare(path)
    lines = ["# Compression breakouts (staged) and mirrored breakdowns\n",
             f"Coins: {len(ind)}. Costs 0.36% round trip. Daily bars.\n",
             "\n## Control: production Donchian 55d idea under this harness\n", HEADER,
             row("Donchian 55d long, trail 3.5 ATR", stats(control(ind)))]
    allres = []
    for direction in ("long", "short"):
        lines += [f"\n## {direction.upper()} variants\n", HEADER]
        for P, V, ctx, stage, M in itertools.product(PS, VS, CTX, STAGES, MS):
            if stage == "prepos" and V != VS[0]:
                continue                                  # volume only matters on a fire
            name = f"{direction} {stage} coil{int(P*100)} vol{V if stage != 'prepos' else '-'} {ctx} {M}"
            tr = run(ind, direction, P, V, ctx, stage, M)
            s = stats(tr)
            lines.append(row(name, s))
            allres.append((s["pf"] if s["n"] >= 25 else 0, name, tr))
    allres.sort(key=lambda r: -r[0])
    lines.append("\n## Top variants split by context\n")
    for _, name, tr in allres[:6]:
        lines += [f"\n### {name}\n", HEADER]
        for k, g in sorted(by(tr, lambda t: f"BTC {t['btc']}").items()):
            lines.append(row(k, stats(g)))
        yr = " · ".join(f"{y}: n{len(g)} PF {stats(g)['pf']:.2f}"
                        for y, g in sorted(by(tr, lambda t: t["year"]).items()))
        lines.append(f"\nBy year: {yr}\n")
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
