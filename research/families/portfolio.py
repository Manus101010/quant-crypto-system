"""Helpers for position-based (portfolio) strategies on daily bars."""
from __future__ import annotations
import numpy as np
import pandas as pd

SIDE_COST = 0.0018          # 0.18% per side = the 0.36% round trip used everywhere


def run_positions(close: pd.Series, pos: pd.Series) -> pd.Series:
    """Daily strategy returns. pos[t] is decided at the close of t and earns the
    return of t+1. Costs are charged on every change in position size."""
    pos = pos.reindex(close.index).fillna(0.0)
    ret = close.pct_change().fillna(0.0)
    held = pos.shift(1).fillna(0.0)
    turn = pos.diff().abs().fillna(pos.abs())
    return held * ret - turn.shift(1).fillna(0.0) * SIDE_COST


def perf(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 30:
        return {"cagr": 0, "dd": 0, "sharpe": 0, "days": len(r)}
    eq = (1 + r).cumprod()
    yrs = len(r) / 365
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if eq.iloc[-1] > 0 else -1.0
    dd = float((eq / eq.cummax() - 1).min())
    sh = float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0
    return {"cagr": 100 * cagr, "dd": 100 * dd, "sharpe": sh, "days": len(r)}


def halves(r: pd.Series) -> tuple[dict, dict]:
    r = r.dropna()
    m = len(r) // 2
    return perf(r.iloc[:m]), perf(r.iloc[m:])


def line(name: str, r: pd.Series) -> str:
    p = perf(r)
    a, b = halves(r)
    yrs = " ".join(f"{y}:{100 * ((1 + g).prod() - 1):+.0f}%" for y, g in r.groupby(r.index.year))
    return (f"| {name} | {p['cagr']:+.1f}% | {p['dd']:.1f}% | {p['sharpe']:.2f} | "
            f"{a['sharpe']:.2f} | {b['sharpe']:.2f} | {yrs} |")


HEAD = ("| strategy | CAGR | max drawdown | Sharpe | Sharpe 1st half | Sharpe 2nd half | by year |\n"
        "|---|---|---|---|---|---|---|")
