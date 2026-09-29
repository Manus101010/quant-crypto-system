"""
Research: does a market-wide GARCH "storm" setting improve the validated setups?

Method (after Miles Deutscher's GARCH Method, MIT — github.com/milesdeutscher/garchmethod):
  1. Walk-forward GARCH(1,1) on BTC daily returns — refit every 21 days on an
     expanding window, each 1-day-ahead forecast uses only data up to that
     day's close (no lookahead).
  2. Regime = percentile of the forecast vs the trailing 365 days:
     calm < 25th, storm > 75th, otherwise normal.
  3. Every trade of the 4 validated setups (production _simulate, 0.36% cost)
     is re-weighted by a risk multiplier chosen on its ENTRY day:
       base        1.0 always
       storm½      0.5 in a storm, 1.0 otherwise
       storm½calm↑ 0.5 in a storm, 1.25 when calm
       voltarget   clip(median_365 / forecast, 0.25, 2.0)   (Miles's sizing rule)
  4. Portfolio equity in R, booked on each trade's EXIT date: total R, max
     drawdown, worst month, return/drawdown — overall and in each half.

Run:  ./venv/bin/python research/garch_storm.py
Not wired into anything live.
"""
from __future__ import annotations
import os
import pickle
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from backtesting.crypto_optimize import _signals, _simulate, management_for
from backtesting.crypto_validation import _apply_costs
from backtesting.setup_validation import _MIN_HISTORY

SCR = Path(os.environ.get("RESEARCH_DIR", "/tmp"))
SETUPS = ["Relative Strength Leader", "Momentum Runner", "Donchian Breakout (55d)",
          "Breakdown Short (55d low)"]


def walkforward_garch(close: pd.Series, min_train=500, refit_every=21) -> pd.Series:
    from arch import arch_model
    r = 100 * np.log(close).diff().dropna()
    out = pd.Series(np.nan, index=r.index)
    params = None
    for t in range(min_train, len(r)):
        if params is None or (t - min_train) % refit_every == 0:
            params = arch_model(r.iloc[:t], vol="GARCH", p=1, q=1,
                                mean="Constant").fit(disp="off").params
        mu, om, a, b = params["mu"], params["omega"], params["alpha[1]"], params["beta[1]"]
        # Roll the variance recursion through day t with the fixed params.
        eps = r.iloc[:t + 1] - mu
        var = om / max(1 - a - b, 1e-6)
        for e in eps.iloc[-250:]:
            var = om + a * e * e + b * var
        out.iloc[t] = np.sqrt(var)                     # forecast for day t+1 (daily %)
    return out


def regimes(fc: pd.Series) -> pd.DataFrame:
    pct = fc.rolling(365, min_periods=120).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)
    med = fc.rolling(365, min_periods=120).median()
    df = pd.DataFrame({"fc": fc, "pct": pct, "med": med})
    df["regime"] = np.where(df.pct > 0.75, "storm", np.where(df.pct < 0.25, "calm", "normal"))
    return df


def mult(rule: str, row) -> float:
    if row is None or pd.isna(row.pct):
        return 1.0
    if rule == "base":
        return 1.0
    if rule == "storm½":
        return 0.5 if row.regime == "storm" else 1.0
    if rule == "storm½calm↑":
        return 0.5 if row.regime == "storm" else (1.25 if row.regime == "calm" else 1.0)
    if rule == "voltarget":
        return float(np.clip(row.med / row.fc, 0.25, 2.0))
    raise ValueError(rule)


def curve_stats(tr: list[dict]) -> dict:
    if not tr:
        return {}
    s = pd.Series([t["R"] for t in tr], index=[t["exit"] for t in tr]).sort_index()
    eq = s.cumsum()
    dd = (eq - eq.cummax()).min()
    monthly = s.groupby(s.index.to_period("M")).sum()
    return {"n": len(tr), "totR": s.sum(), "maxDD": dd, "worstM": monthly.min(),
            "ret/dd": s.sum() / abs(dd) if dd else float("inf"),
            "mSharpe": monthly.mean() / monthly.std() if monthly.std() else 0}


def main():
    data, btc_sig = pickle.load(open(SCR / "scaled_data.pkl", "rb"))
    btc = pickle.load(open(SCR / "btc_long.pkl", "rb"))["close"]
    print(f"BTC history {btc.index.min().date()} → {btc.index.max().date()}; fitting walk-forward GARCH …")
    reg = regimes(walkforward_garch(btc))
    reg.index = reg.index.normalize()
    print("regime share in trade window:",
          reg.loc["2025-02-01":, "regime"].value_counts(normalize=True).round(2).to_dict())

    trades = []
    for sym, df in data.items():
        if len(df) < _MIN_HISTORY + 20:
            continue
        v = df["volume"] if "volume" in df.columns else None
        for i, ind in _signals(df["close"], df["high"], df["low"], v, btc_sig):
            lab = ind["_label"]
            if lab not in SETUPS:
                continue
            t = _simulate(df["close"], df["high"], df["low"], i, ind, management_for(lab))
            if t:
                t["entry"] = df.index[i].normalize()
                t["exit"] = df.index[min(i + max(t["bars_held"], 1), len(df) - 1)].normalize()
                trades.append(t)
    trades = _apply_costs(trades, 0.36)
    mid = sorted(t["entry"] for t in trades)[len(trades) // 2]
    print(f"{len(trades)} trades; halves split at {mid.date()}\n")

    rules = ["base", "storm½", "storm½calm↑", "voltarget"]
    for scope in ["ALL"] + SETUPS:
        pool = [t for t in trades if scope == "ALL" or t["setup"] == scope]
        print(f"=== {scope}  (n={len(pool)})")
        print(f"{'rule':<13}{'totR':>9}{'maxDD':>9}{'worstM':>9}{'ret/dd':>8}{'mSharpe':>9}"
              f"   {'ret/dd 1st½':>11}{'ret/dd 2nd½':>12}")
        for rule in rules:
            rows = []
            for t in pool:
                row = reg.loc[t["entry"]] if t["entry"] in reg.index else None
                rows.append({"R": t["r_mult"] * mult(rule, row), "exit": t["exit"],
                             "half": 0 if t["entry"] < mid else 1})
            a = curve_stats(rows)
            h0 = curve_stats([r for r in rows if r["half"] == 0])
            h1 = curve_stats([r for r in rows if r["half"] == 1])
            print(f"{rule:<13}{a['totR']:>9.1f}{a['maxDD']:>9.1f}{a['worstM']:>9.1f}"
                  f"{a['ret/dd']:>8.2f}{a['mSharpe']:>9.2f}   {h0.get('ret/dd', 0):>11.2f}"
                  f"{h1.get('ret/dd', 0):>12.2f}")
        print()


if __name__ == "__main__":
    main()
