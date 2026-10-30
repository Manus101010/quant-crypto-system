"""Daily movers board: offline."""
from __future__ import annotations

import numpy as np
import pandas as pd

from desk import movers


def _df(closes, spread=0.004):
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + spread)
    l = np.minimum(o, c) * (1 - spread)
    idx = pd.date_range("2026-10-01", periods=len(c), freq="1h")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 1.0}, index=idx)


def test_dumping_loser():
    closes = list(np.linspace(1.0, 0.70, 80))
    st, sc, why = movers.classify(movers.features_1h(_df(closes + [0.69])), "loser")
    assert st == "STILL DUMPING" and 40 <= sc <= 100 and "SAR above price" in why


def test_running_gainer():
    closes = list(np.linspace(1.0, 1.35, 80))
    st, sc, _ = movers.classify(movers.features_1h(_df(closes + [1.36])), "gainer")
    assert st == "STILL RUNNING" and sc >= 40


def test_rollover_gainer():
    # flat, a hard run with big bars, then small bars topping out and slipping
    base = [1.0] * 40
    run = list(np.linspace(1.0, 1.6, 8))
    top = [1.60, 1.59, 1.585]
    df = _df(base + run + top + [1.56])
    # make the run bars wide and the top bars narrow
    n = len(df)
    df.iloc[40:48, df.columns.get_loc("high")] *= 1.03
    df.iloc[40:48, df.columns.get_loc("low")] *= 0.97
    f = movers.features_1h(df)
    assert f["comp"] < 0.7 and f["stretch_up"] >= 3
    st, sc, _ = movers.classify(f, "gainer")
    assert st in ("ROLLING OVER", "STRETCHED UP")


def test_top_movers_filters_and_sorts():
    tk = {
        "AAA/USDT:USDT": {"percentage": 40, "quoteVolume": 5e6},
        "BBB/USDT:USDT": {"percentage": 25, "quoteVolume": 5e6},
        "THIN/USDT:USDT": {"percentage": 90, "quoteVolume": 1e5},
        "CCC/USDT:USDT": {"percentage": -30, "quoteVolume": 9e6},
        "TSLASTOCK/USDT:USDT": {"percentage": 50, "quoteVolume": 9e9},
        "DDD/USDT": {"percentage": 70, "quoteVolume": 9e9},
    }
    g, l = movers.top_movers(5, tickers=tk)
    assert [x[0] for x in g] == ["AAA", "BBB"] and [x[0] for x in l] == ["CCC"]


def test_board_text(monkeypatch):
    monkeypatch.setattr("utils.breadth.long_gate", lambda: (False, "BTC below 50d"))
    tk = {"AAA/USDT:USDT": {"percentage": 35, "quoteVolume": 5e6},
          "CCC/USDT:USDT": {"percentage": -30, "quoteVolume": 9e6}}
    candles = {"AAA": _df(list(np.linspace(1.0, 1.35, 81))),
               "CCC": _df(list(np.linspace(1.0, 0.70, 81)))}
    b = movers.board(tickers=tk, candles=candles, store=False)
    txt = movers.text(b)
    assert "AAA" in txt and "CCC" in txt and "Still Dumping" in txt
    assert "Long gate is closed" in txt and "What the backtest says" in txt
