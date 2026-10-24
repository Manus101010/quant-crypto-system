"""
Family D: GRID BOTS — does the deployment rule matter, and is "long grid on a
breakout signal" (what the live bot suggests today) a good idea?

Grid model (MEXC futures style, arithmetic):
  range  = entry close +/- K ATR, N = 10 grids, run up to 30 days
  kill   = price moves one grid beyond either edge -> close everything (the stop)
  modes  neutral: flat at the centre, long below it, short above it
         long:    holds N/2 units at the centre (bought at deploy), N at the bottom, 0 at the top
         short:   mirror of long
  intrabar path approximated from daily OHLC: O->L->H->C on up days, O->H->L->C on down days
  costs  0.05% per fill (0.02% fee + 0.03% slippage) on every unit traded
Return per run is % of the notional needed at 1x to fund the grid's maximum
exposure (N/2 units neutral, N units long/short), so leverage scales it linearly.

Deployment rules compared (one grid per coin at a time, liquidity floor applies):
  every10      neutral grid every 10th day regardless (baseline)
  chop         neutral when efficiency ratio(20) <= 0.25 and Bollinger width <= its 180d median
  chop+btcmix  chop AND BTC regime MIXED (neither trending up nor down)
  brk->long    LONG grid on a fresh 20-day high close (the live bot's CAKE suggestion)
  brk->neutral NEUTRAL grid on the same trigger
  chop->long   LONG grid in chop

Run:  ./venv/bin/python research/families/grids.py history.pkl [report.md]
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.families.common import HEADER, MIN_VOL_USD, by, prepare, row, stats, tag  # noqa: E402

N, MAX_BARS, FEE = 10, 30, 0.05 / 100


def _sim(bars, center, a, mode, K):
    """bars: iterable of (o, h, l, c) in time order after deployment."""
    if not np.isfinite(a) or a <= 0 or K * a >= center:
        return None
    sp = 2 * K * a / N
    lower = center - K * a
    lv = lambda j: lower + j * sp                      # noqa: E731
    mid = N // 2

    def units(last):                                   # position after touching level `last`
        if mode == "neutral":
            return mid - last
        if mode == "long":
            return N - last
        return -last                                   # short

    last = mid
    u = units(last)
    pnl = -abs(u) * center * FEE                       # initial position (long/short modes)
    price, killed, steps = center, False, 0
    for (o, h, l, c) in bars:
        steps += 1
        path = [o, l, h, c] if c >= o else [o, h, l, c]
        for tgt in path:
            step = 1 if tgt > price else -1
            while True:
                nxt_idx = last + step
                lvl = lv(nxt_idx)
                if (step > 0 and lvl > tgt) or (step < 0 and lvl < tgt):
                    break
                pnl += u * (lvl - price)
                price = lvl
                if nxt_idx <= -1 or nxt_idx >= N + 1:  # one grid beyond the edge: kill
                    pnl -= abs(u) * lvl * FEE
                    u, killed = 0, True
                    break
                last = nxt_idx
                nu = units(last)
                pnl -= abs(nu - u) * lvl * FEE
                u = nu
            if killed:
                break
            pnl += u * (tgt - price)
            price = tgt
        if killed:
            break
    if steps == 0:
        return None
    if not killed:
        pnl -= abs(u) * price * FEE                    # close at the end of the run
    cap = (N / 2 if mode == "neutral" else N) * center
    return pnl / cap * 100, killed


def run_grid(x, i, mode, K, hourly=None):
    center, a = float(x["c"].iat[i]), float(x["atr"].iat[i])
    if hourly is None:
        j1 = min(i + MAX_BARS, len(x) - 1)
        if j1 <= i:
            return None
        sub = x.iloc[i + 1:j1 + 1]
    else:
        t0 = x.index[i] + pd.Timedelta(days=1)
        sub = hourly[(hourly.index >= t0) & (hourly.index < t0 + pd.Timedelta(days=MAX_BARS))]
        if len(sub) < 24 * 5:
            return None
        sub = sub.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c"})
    bars = zip(sub["o"].values, sub["h"].values, sub["l"].values, sub["c"].values)
    r = _sim(bars, center, a, mode, K)
    if r is None:
        return None
    ret, killed = r
    # elapsed days until the run ended (kill or time) are approximated by MAX_BARS when not killed
    return {"ret_pct": ret, "r_mult": ret, "bars": MAX_BARS, "killed": killed,
            "entry": x.index[i], "exit": x.index[min(i + MAX_BARS, len(x) - 1)]}


RULES = {
    "every10":      ("neutral", lambda x: np.arange(len(x)) % 10 == 0),
    "chop":         ("neutral", lambda x: ((x["er20"] <= 0.25) & (x["bbw_pct"] <= 0.5)).values),
    "chop+btcmix":  ("neutral", lambda x: ((x["er20"] <= 0.25) & (x["bbw_pct"] <= 0.5)
                                           & (x["btc_regime"] == "MIXED")).values),
    "brk->long":    ("long",    lambda x: (x["c"] > x["hh20p"]).values),
    "brk->neutral": ("neutral", lambda x: (x["c"] > x["hh20p"]).values),
    "chop->long":   ("long",    lambda x: ((x["er20"] <= 0.25) & (x["bbw_pct"] <= 0.5)).values),
}


def run(ind, rule, K, hourly=None):
    mode, fn = RULES[rule]
    out = []
    for sym, x in ind.items():
        hx = None
        if hourly is not None:
            hx = hourly.get(sym)
            if hx is None:
                continue
        sig = np.asarray(fn(x), dtype=bool) & (x["qvol20"].values >= MIN_VOL_USD)
        busy = -1
        for i in np.flatnonzero(sig):
            if i <= busy or i < 200:
                continue
            t = run_grid(x, i, mode, K, hx)
            if t is None:
                continue
            t.update(tag(x, i)); t["sym"] = sym
            busy = i + t["bars"]
            out.append(t)
    return out


def main(path, out=None, hourly_path=None):
    ind, _ = prepare(path)
    hourly = None
    if hourly_path:
        import pickle
        hourly = pickle.loads(Path(hourly_path).read_bytes())
        ind = {s: x for s, x in ind.items() if s in hourly}   # deploys outside hourly coverage are skipped
    lines = [f"# Grid deployment rules ({'hourly' if hourly else 'daily'} price paths)\n",
             f"Coins: {len(ind)}. 10 grids, up to 30 days, 0.05% per fill, kill one grid past "
             "either edge. 'expR' and 'totR' here are mean / total % return per grid run at 1x.\n",
             "\n| rule | range | runs | PF | win | mean % per run | killed | PF 1st half | PF 2nd half | verdict |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    keep = {}
    for rule in RULES:
        for K in (2.0, 3.0):
            tr = run(ind, rule, K, hourly)
            s = stats(tr)
            kill = 100 * sum(t["killed"] for t in tr) / max(len(tr), 1)
            lines.append(f"| {rule} | ±{K:.0f} ATR | {s['n']} | {s['pf']:.2f} | {s['win']:.0f}% | "
                         f"{s['expR']:+.2f}% | {kill:.0f}% | {s['pf1']:.2f} | {s['pf2']:.2f} | "
                         f"{'PASS' if s['pass'] else 'fail'} |")
            keep[(rule, K)] = tr
    lines.append("\n## By BTC regime (±3 ATR)\n")
    for rule in RULES:
        lines += [f"\n### {rule}\n", HEADER]
        for k, g in sorted(by(keep[(rule, 3.0)], lambda t: f"BTC {t['btc']}").items()):
            lines.append(row(k, stats(g)))
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text)
    print(text)


if __name__ == "__main__":
    a = sys.argv
    main(a[1], a[2] if len(a) > 2 else None, a[3] if len(a) > 3 else None)
