"""
Research (Oct 18 2026): longs in a "Bitcoin-only" market.

Live: BTC above its 50d and 200d, but only ~23% of alts above their 50d, so the
breadth gate (>= 60%) blocks every long. The gate was tuned on all coins pooled.
Question: do the long setups still work on the most LIQUID coins (top 20 by 20d
turnover that day) when BTC is up but breadth is low?

Same signals/exits as the validation backtest (backtesting.crypto_optimize),
0.36% cost, 2020-2026, trades tagged with symbol, liquidity rank, breadth, BTC.

Run:  ./venv/bin/python research/btc_only_longs.py ~/quantcore_cache/long_history.pkl
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting.crypto_optimize import _signals, _simulate, management_for, SHORT_SETUPS  # noqa: E402
from backtesting.crypto_validation import _apply_costs  # noqa: E402
from backtesting.setup_validation import _MIN_HISTORY  # noqa: E402

LONGS = {"Momentum Runner", "Donchian Breakout (55d)", "Relative Strength Leader",
         "Volume Breakout", "Squeeze Breakout"}


def main(pkl):
    src = Path(pkl); cache = src.with_name("btc_only_trades.pkl")
    d = pickle.load(open(src, "rb"))
    btc = d["btc"]["close"].copy(); btc.index = btc.index.normalize()
    coins = {}
    for s, df in d["coins"].items():
        if df is not None and len(df) >= _MIN_HISTORY + 20:
            df = df.copy(); df.index = df.index.normalize(); coins[s] = df
    closes = pd.DataFrame({s: df["close"] for s, df in coins.items()})
    above50 = (closes > closes.rolling(50).mean()).where(closes.rolling(50).count() >= 50)
    breadth = above50.mean(axis=1) * 100
    qv = pd.DataFrame({s: (df["close"] * df["volume"]).rolling(20).mean() for s, df in coins.items()})
    rank = qv.rank(axis=1, ascending=False)
    btc_up = (btc > btc.rolling(200).mean()) & (btc > btc.rolling(50).mean())
    if cache.exists():
        trades = pickle.load(open(cache, "rb"))
    else:
        trades = []
        for sym, df in coins.items():
            v = df["volume"] if "volume" in df.columns else None
            for i, ind in _signals(df["close"], df["high"], df["low"], v, btc):
                lab = ind["_label"]
                if lab not in LONGS:
                    continue
                t = _simulate(df["close"], df["high"], df["low"], i, ind, management_for(lab))
                if t:
                    t = _apply_costs([t], 0.36)[0]
                    t["sym"], t["entry"] = sym, df.index[i]
                    trades.append(t)
        pickle.dump(trades, open(cache, "wb"))
    T = pd.DataFrame(trades)
    T["breadth"] = breadth.reindex(T["entry"]).values
    T["rank"] = [rank.at[e, s] if e in rank.index else np.nan for e, s in zip(T["entry"], T["sym"])]
    T["btc_up"] = btc_up.reindex(T["entry"]).fillna(False).values

    def rep(name, x):
        r = x["r_mult"].values
        if len(r) < 5:
            print(f"{name:<58} n={len(r)}"); return
        pf = r[r > 0].sum() / -r[r < 0].sum() if (r < 0).any() else 99
        t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
        e = x["entry"].values; mid = np.sort(e)[len(e) // 2]
        h = lambda m: (lambda a: a[a > 0].sum() / -a[a < 0].sum() if (a < 0).any() else 99)(r[m])
        yrs = x.groupby(x["entry"].dt.year)["r_mult"].sum()
        print(f"{name:<58} n={len(r):>5} PF {pf:.2f} avg {r.mean():+.3f} t={t:5.2f} halves {h(e<mid):.2f}/{h(e>=mid):.2f} | "
              + " ".join(f"{y}:{v:+.0f}" for y, v in yrs.items()))

    low = T["btc_up"] & (T["breadth"] < 60)
    high = T["btc_up"] & (T["breadth"] >= 60)
    for lab in sorted(LONGS) + ["ALL LONGS"]:
        X = T if lab == "ALL LONGS" else T[T["setup"] == lab]
        print(f"\n== {lab}")
        rep("live gate (BTC up, breadth >= 60)", X[high[X.index]])
        rep("BTC up, breadth < 60 - all coins", X[low[X.index]])
        rep("BTC up, breadth < 60 - top 20 liquid", X[low[X.index] & (X["rank"] <= 20)])
        rep("BTC up, breadth < 60 - top 10 liquid", X[low[X.index] & (X["rank"] <= 10)])
        rep("BTC up, breadth < 40 - top 20 liquid", X[T["btc_up"][X.index] & (X["breadth"] < 40) & (X["rank"] <= 20)])


if __name__ == "__main__":
    main(sys.argv[1])
