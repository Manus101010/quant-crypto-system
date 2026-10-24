"""
Round 2 (#1): futures GRID bots on 5-minute price paths, with grid count,
range width, leverage and liquidation modelled.

Grid (MEXC futures style, arithmetic levels):
  range    deploy price +/- K x daily ATR(14)   K = 1 (narrow), 2.5 (medium), 5 (wide)
  grids    N = 10, 30, 60, 100 ; each grid = 1/N of the bot's notional (margin x leverage)
  modes    neutral (flat at the centre), long (half-filled at the centre), short (mirror)
  exit     "stop": close everything one grid beyond either edge
           "hold": keep the position; orders simply stop beyond the range
  run      D days (default 7), then close at market
  costs    0.02% per fill (config.GRID_FEE_PCT), every fill
  liquidation: equity (margin + P&L) <= 1% of open notional at any 5-minute bar
           -> the run returns -100% of margin
Intrabar path from OHLC: O->L->H->C on up bars, O->H->L->C on down bars.

Returns are % of MARGIN at leverage L, so 10x numbers are the real 10x outcome
including liquidations. One P&L path serves every leverage (P&L scales linearly
until the liquidation check, which is applied per leverage).

Deployment rules (decided at 00:00 UTC from the previous daily close):
  daily       a fresh bot every D days on every coin (baseline)
  chop        efficiency ratio(20) <= 0.25 and Bollinger width <= its 180-day median
  highvol     Bollinger width >= its 70th percentile (harvest big swings)
  btc_mixed   BTC regime MIXED (not trending either way)
  weekend     Friday 22:00 UTC, run 2 days (vs a weekday control, Tue 00:00, 2 days)

Run:  ./venv/bin/python research/families/grids_5m.py history.pkl m5.pkl [report.md]
"""
from __future__ import annotations
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.families.common import prepare  # noqa: E402

FEE = 0.0002
MM = 0.01
LEVS = (3, 5, 10)


@njit(cache=True)
def sim(o, h, l, c, center, lower, sp, N, mode, stop_on_exit):
    """Return (pnl_frac, worst_margin_frac, killed, fills). pnl_frac is P&L as a
    fraction of the bot's full notional (N units x centre price)."""
    mid = N // 2
    last = mid
    if mode == 0:
        u = mid - last
    elif mode == 1:
        u = N - last
    else:
        u = -last
    unit = 1.0 / (N * center)          # 1 unit = 1/N of notional, in fraction-of-notional
    pnl = -abs(u) * center * FEE * unit
    price = center
    worst = 0.0
    killed = False
    fills = 0
    for k in range(len(c)):
        if c[k] >= o[k]:
            p0, p1, p2, p3 = o[k], l[k], h[k], c[k]
        else:
            p0, p1, p2, p3 = o[k], h[k], l[k], c[k]
        for q in range(4):
            tgt = p0 if q == 0 else (p1 if q == 1 else (p2 if q == 2 else p3))
            step = 1 if tgt > price else -1
            while True:
                nxt = last + step
                if (not stop_on_exit) and (nxt < 0 or nxt > N):
                    break
                lvl = lower + nxt * sp
                if (step > 0 and lvl > tgt) or (step < 0 and lvl < tgt):
                    break
                pnl += u * (lvl - price) * unit
                price = lvl
                if nxt <= -1 or nxt >= N + 1:
                    pnl -= abs(u) * lvl * FEE * unit
                    u = 0
                    killed = True
                    break
                last = nxt
                if mode == 0:
                    nu = mid - last
                elif mode == 1:
                    nu = N - last
                else:
                    nu = -last
                pnl -= abs(nu - u) * lvl * FEE * unit
                fills += abs(nu - u)
                u = nu
            if killed:
                break
            pnl += u * (tgt - price) * unit
            price = tgt
            m = pnl - MM * abs(u) * price * unit
            if m < worst:
                worst = m
        if killed:
            break
    if not killed:
        pnl -= abs(u) * price * FEE * unit
    return pnl, worst, killed, fills


def deploy_times(x: pd.DataFrame, rule: str, D: int, m5_index: pd.DatetimeIndex):
    """Daily decisions -> list of (start timestamp, run days)."""
    days = x.index[(x.index >= m5_index[0].normalize()) & (x.index < m5_index[-1].normalize())]
    out, busy = [], pd.Timestamp(0)
    for d in days:
        start = d + pd.Timedelta(days=1)
        if start < busy:
            continue
        r = x.loc[d]
        ok = {
            "daily": True,
            "chop": r["er20"] <= 0.25 and r["bbw_pct"] <= 0.5,
            "highvol": r["bbw_pct"] >= 0.7,
            "btc_mixed": r["btc_regime"] == "MIXED",
            "weekend": start.weekday() == 4,          # Friday
            "weekday": start.weekday() == 1,          # Tuesday control
        }[rule]
        if not ok:
            continue
        if rule == "weekend":
            s, dd = start + pd.Timedelta(hours=22), 2
        elif rule == "weekday":
            s, dd = start, 2
        else:
            s, dd = start, D
        out.append((s, dd, float(r["atr"]), float(r["c"])))
        busy = s + pd.Timedelta(days=dd)
    return out


def run(ind, m5, rule, K, N, mode, stop, D=7):
    res = []
    for sym, df in m5.items():
        if df is None or sym not in ind:
            continue
        x = ind[sym]
        ts = df.index.values
        o, h, l, c = (df[k].values.astype(np.float64) for k in ("open", "high", "low", "close"))
        for s, dd, atr, _ in deploy_times(x, rule, D, df.index):
            i0 = np.searchsorted(ts, np.datetime64(s))
            i1 = np.searchsorted(ts, np.datetime64(s + pd.Timedelta(days=dd)))
            if i1 - i0 < 12 * 24 or not np.isfinite(atr) or atr <= 0:
                continue
            center = c[i0 - 1] if i0 > 0 else o[i0]
            if K * atr >= center:
                continue
            lower, sp = center - K * atr, 2 * K * atr / N
            pnl, worst, killed, fills = sim(o[i0:i1], h[i0:i1], l[i0:i1], c[i0:i1],
                                            center, lower, sp, N, mode, stop)
            res.append({"sym": sym, "start": s, "pnl": pnl, "worst": worst,
                        "killed": killed, "fills": fills, "spacing_pct": 100 * sp / center})
    return res


def summarise(res):
    if not res:
        return None
    out = {"runs": len(res), "fills": float(np.mean([r["fills"] for r in res])),
           "spacing": float(np.mean([r["spacing_pct"] for r in res])),
           "killed": 100 * float(np.mean([r["killed"] for r in res]))}
    half = sorted(r["start"] for r in res)[len(res) // 2]
    for L in LEVS:
        rets = np.array([-100.0 if r["worst"] <= -1.0 / L else 100 * r["pnl"] * L for r in res])
        liq = np.array([r["worst"] <= -1.0 / L for r in res])
        a = np.array([r["start"] < half for r in res])
        gw, gl = rets[rets > 0].sum(), -rets[rets <= 0].sum()
        out[L] = {"mean": rets.mean(), "median": float(np.median(rets)),
                  "win": 100 * (rets > 0).mean(), "liq": 100 * liq.mean(),
                  "pf": gw / gl if gl else 99.0,
                  "m1": rets[a].mean(), "m2": rets[~a].mean()}
    return out


def main(hist, m5_path, out=None):
    ind, _ = prepare(hist)
    m5 = pickle.loads(Path(m5_path).read_bytes())
    span = [d.index for d in m5.values() if d is not None]
    lines = ["# Grid bots on 5-minute paths: range width x grid count x leverage\n",
             f"{len(span)} most liquid MEXC coins, {min(s[0] for s in span).date()} to "
             f"{max(s[-1] for s in span).date()}. 0.02% per fill, liquidation at 1% maintenance. "
             "Returns are % of margin per bot run.\n"]
    modes = {"neutral": 0, "long": 1, "short": 2}

    def table(title, combos):
        nonlocal lines
        lines += [f"\n## {title}\n",
                  "| rule | mode | range | grids | spacing | exit | runs | stopped out | "
                  + " | ".join(f"{L}x mean / win / liq" for L in LEVS) + " | 3x mean 1st / 2nd half |",
                  "|---|---|---|---|---|---|---|---|" + "---|" * len(LEVS) + "---|"]
        for rule, mode, K, N, stop, D in combos:
            s = summarise(run(ind, m5, rule, K, N, modes[mode], stop, D))
            if s is None:
                continue
            cells = " | ".join(f"{s[L]['mean']:+.1f}% / {s[L]['win']:.0f}% / {s[L]['liq']:.0f}%" for L in LEVS)
            lines.append(f"| {rule} | {mode} | ±{K} ATR | {N} | {s['spacing']:.2f}% | "
                         f"{'stop' if stop else 'hold'} | {s['runs']} | {s['killed']:.0f}% | {cells} | "
                         f"{s[3]['m1']:+.1f}% / {s[3]['m2']:+.1f}% |")

    grid = [("daily", "neutral", K, N, st, 7) for K in (1.0, 2.5, 5.0) for N in (10, 30, 60, 100)
            for st in (True, False)]
    table("Baseline: a neutral bot every 7 days on every coin", grid)
    rules = [(r, "neutral", K, N, False, 7) for r in ("chop", "highvol", "btc_mixed")
             for K in (2.5, 5.0) for N in (30, 100)]
    table("Deployment filters (neutral, hold at the edges, 7 days)", rules)
    longs = [("daily", m, K, N, False, 7) for m in ("long", "short") for K in (2.5, 5.0) for N in (30, 100)]
    table("Long and short grids (every 7 days, hold)", longs)
    sess = [(r, "neutral", K, N, False, 2) for r in ("weekend", "weekday") for K in (1.0, 2.5) for N in (30, 100)]
    table("Weekend vs weekday (2-day neutral bots)", sess)
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text)
    print(text)


if __name__ == "__main__":
    a = sys.argv
    main(a[1], a[2], a[3] if len(a) > 3 else None)
