"""
Family B: EXHAUSTION MEAN REVERSION ("rip, then volatility fades, then fade it").

SHORT (mirror for capitulation LONGS):
  1. Rip:      5-day return z-score (vs its own 90 days) >= Z on some bar in the last 7
  2. Stretch:  peak distance above the 20 EMA in the last 7 bars >= S ATR
  3. Fade:     the last 3 days' average true range <= F x ATR(14)   (optional, F = 1.0)
  4. Confirm:  TODAY is the first close back below the 9 EMA ("ema9"),
               a close below yesterday's low ("prevbar"), or no confirmation ("none")
  5. Room:     price is still >= 0.25 ATR above the 20 EMA (target worth taking)
Management:
  "ema20": target = 20 EMA at entry, stop = highest high of the last 7 bars + 0.25 ATR, 10 bars
  "2R":    stop 2 ATR, target 2R, 10 bars

Unlike every production short, this does NOT require price below the 200 SMA.
Results are split by above/below 200 and by BTC regime.

Run:  ./venv/bin/python research/families/exhaustion.py history.pkl [report.md]
"""
from __future__ import annotations
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.families.common import (HEADER, Plan, by, prepare, row, run_signals,  # noqa: E402
                                      stats, tag)

ZS, SS, FS, CS, MS = (2.0, 3.0), (2.5, 3.5), (None, 1.0), ("ema9", "prevbar", "none"), ("ema20", "2R")
ROOM = 0.25   # price must still be >= ROOM x ATR beyond the 20 EMA (target worth taking)


def signal(direction, Z, S, F, C):
    sgn = 1 if direction == "short" else -1

    def fn(x):
        rip = (sgn * x["z5"]).rolling(7).max() >= Z
        peak = (x["h"] - x["ema20"]) / x["atr"] if sgn > 0 else (x["ema20"] - x["l"]) / x["atr"]
        stretch = peak.rolling(7).max() >= S
        fade = (x["tr3"] <= F * x["atr"]) if F else True
        if C == "ema9":
            now = (x["c"] < x["ema9"]) if sgn > 0 else (x["c"] > x["ema9"])
            was = (x["c"].shift() >= x["ema9"].shift()) if sgn > 0 else (x["c"].shift() <= x["ema9"].shift())
            conf = now & was
        elif C == "prevbar":
            conf = (x["c"] < x["l"].shift()) if sgn > 0 else (x["c"] > x["h"].shift())
        else:
            conf = True                                      # enter on the stretch itself
        room = (sgn * (x["c"] - x["ema20"])) >= ROOM * x["atr"]
        return rip & stretch & fade & conf & room
    return fn


def plan(direction, M):
    short = direction == "short"

    def fn(x, i):
        c, a = float(x["c"].iat[i]), float(x["atr"].iat[i])
        if M == "ema20":
            if short:
                stop = float(x["h"].iloc[i - 6:i + 1].max()) + 0.25 * a
            else:
                stop = float(x["l"].iloc[i - 6:i + 1].min()) - 0.25 * a
            return Plan(direction, stop, float(x["ema20"].iat[i]), None, 10)
        stop = c + 2 * a if short else c - 2 * a
        tgt = c - 4 * a if short else c + 4 * a
        return Plan(direction, stop, tgt, None, 10)
    return fn


def main(path, out=None):
    ind, _ = prepare(path)
    lines = ["# Exhaustion mean reversion (fade the rip / buy the capitulation)\n",
             f"Coins: {len(ind)}. Costs 0.36% round trip. Daily bars.\n"]
    best = []
    for direction in ("short", "long"):
        lines += [f"\n## {direction.upper()} variants (all regimes)\n", HEADER]
        for Z, S, F, C, M in itertools.product(ZS, SS, FS, CS, MS):
            name = f"{direction} Z{Z} S{S} F{F or '-'} {C} {M}"
            tr = run_signals(ind, signal(direction, Z, S, F, C), plan(direction, M), tag)
            s = stats(tr)
            lines.append(row(name, s))
            best.append((s["pf"] if s["n"] >= 25 else 0, name, tr))
    best.sort(key=lambda b: -b[0])
    lines.append("\n## Top variants split by context\n")
    for _, name, tr in best[:6]:
        lines += [f"\n### {name}\n", HEADER]
        for k, g in sorted(by(tr, lambda t: "above 200" if t["above200"] else "below 200").items()):
            lines.append(row(k, stats(g)))
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
