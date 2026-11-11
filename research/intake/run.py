"""
Strategy intake runner: test ANY strategy module in research/strategies/ through
the same harness and pass rules, with a bar that gets stricter the more
strategies have been tried (so testing 50 ideas cannot crown a lucky one).

    ./venv/bin/python research/intake/run.py <strategy_slug> [history.pkl]

History defaults to $RESEARCH_HISTORY. Writes research/intake/results/<slug>.md and
appends every variant to research/intake/leaderboard.csv.

Verdicts
  REJECT    fails the basic bar
  WATCH     basic bar: PF > 1, n >= 50, PF > 1 in both halves, expectancy R > 0
  CANDIDATE WATCH + t-stat of R clears the multiple-testing threshold
            + still positive with crowded days removed (<= 3 signals that day)
            + most neighbouring variants also have positive expectancy
Only CANDIDATEs should ever be wired into the live scanner (then they still go
through the production validation and the "Took it" forward test).
"""
from __future__ import annotations
import csv
import datetime as dt
import importlib
import os
import sys
from pathlib import Path

import numpy as np
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.families.common import (HEADER, MIN_VOL_USD, by, prepare, row,  # noqa: E402
                                      run_signals, stats, tag, tiered_cost)

HERE = Path(__file__).resolve().parent
BOARD = HERE / "leaderboard.csv"
FIELDS = ["date", "strategy", "variant", "direction", "n", "pf", "win", "expR", "t",
          "t_needed", "pf1", "pf2", "verdict", "tests_so_far", "source"]


def tests_so_far() -> int:
    if not BOARD.exists():
        return 0
    with BOARD.open() as f:
        return sum(1 for _ in csv.DictReader(f))


def tstat(tr) -> float:
    r = np.array([t["r_mult"] for t in tr])
    return float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 2 and r.std() > 0 else 0.0


def main(slug: str, hist: str):
    mod = importlib.import_module(f"research.strategies.{slug}")
    params = getattr(mod, "PARAMS", [{}])
    min_bars = getattr(mod, "MIN_BARS", 200)
    min_qv = getattr(mod, "MIN_QV", MIN_VOL_USD)
    ind, _ = prepare(hist, min_rows=min_bars + 5)
    prior = tests_so_far()
    n_tests = prior + len(params)
    t_needed = float(norm.ppf(1 - 0.05 / (2 * max(n_tests, 1))))     # Bonferroni, two-sided 5%

    results = []
    for p in params:
        tr = run_signals(ind, lambda x: mod.signal(x, **p), lambda x, i: mod.plan(x, i, **p),
                         tag, min_i=min_bars, cost_fn=tiered_cost, min_qv=min_qv)
        results.append((p, tr))

    pos_neighbours = np.mean([stats(tr)["expR"] > 0 for _, tr in results]) if results else 0
    lines = [f"# {getattr(mod, 'NAME', slug)}\n",
             f"Source: {getattr(mod, 'SOURCE', 'n/a')}\n",
             f"Hypothesis: {getattr(mod, 'HYPOTHESIS', 'n/a')}\n",
             f"Coins: {len(ind)}. Tiered costs (0.36% liquid, 0.80% under $2M a day). "
             f"Strategies tested so far incl. this: {n_tests}, so t-stat needed = {t_needed:.2f}.\n",
             HEADER.replace("| verdict |", "| t | verdict |").replace("|---|---|---|---|---|---|---|---|---|---|",
                                                                  "|---|---|---|---|---|---|---|---|---|---|---|")]
    board_rows, best = [], None
    for p, tr in results:
        s = stats(tr)
        s["n_ok"] = s["n"] >= 50
        t = tstat(tr) if tr else 0.0
        dates = by(tr, lambda t: t["entry"])
        uncrowded = stats([x for x in tr if len(dates[x["entry"]]) <= 3])
        if not (s["pass"] and s["n_ok"]):
            verdict = "REJECT"
        elif t >= t_needed and uncrowded["pf"] > 1 and uncrowded["expR"] > 0 and pos_neighbours > 0.5:
            verdict = "CANDIDATE"
        else:
            verdict = "WATCH"
        name = ", ".join(f"{k}={v}" for k, v in p.items()) or "default"
        lines.append(row(name, s).replace(f"| {'PASS' if s['pass'] else 'fail'} |", f"| {t:.2f} | {verdict} |"))
        board_rows.append({"date": dt.date.today().isoformat(), "strategy": slug, "variant": name,
                           "direction": getattr(mod, "DIRECTION", "?"), "n": s["n"], "pf": f"{s['pf']:.2f}",
                           "win": f"{s['win']:.0f}", "expR": f"{s['expR']:+.3f}", "t": f"{t:.2f}",
                           "t_needed": f"{t_needed:.2f}", "pf1": f"{s['pf1']:.2f}", "pf2": f"{s['pf2']:.2f}",
                           "verdict": verdict, "tests_so_far": n_tests, "source": getattr(mod, "SOURCE", "")})
        if best is None or s["expR"] > best[1]["expR"]:
            best = (name, s, tr)

    if best and best[2]:
        name, s, tr = best
        lines += [f"\n## Best variant ({name}) split by context\n", HEADER]
        for k, g in sorted(by(tr, lambda t: f"BTC {t['btc']}").items()):
            lines.append(row(k, stats(g)))
        for k, g in sorted(by(tr, lambda t: "liquid (>= $2M/day)" if t.get("cost", 0.36) < 0.5
                              else "small cap (< $2M/day)").items()):
            lines.append(row(k, stats(g)))
        dates = by(tr, lambda t: t["entry"])
        lines.append(row("excluding crowded days (> 3 signals)",
                         stats([x for x in tr if len(dates[x["entry"]]) <= 3])))
        yr = " · ".join(f"{y}: n{len(g)} PF {stats(g)['pf']:.2f} expR {stats(g)['expR']:+.2f}"
                        for y, g in sorted(by(tr, lambda t: t["year"]).items()))
        lines.append(f"\nBy year: {yr}\n")

    out = HERE / "results" / f"{slug}.md"
    out.write_text("\n".join(lines))
    new = not BOARD.exists()
    with BOARD.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(board_rows)
    print("\n".join(lines))


if __name__ == "__main__":
    a = sys.argv
    main(a[1], a[2] if len(a) > 2 else os.environ["RESEARCH_HISTORY"])
