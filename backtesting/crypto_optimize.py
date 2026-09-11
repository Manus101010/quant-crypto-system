"""
Trade-Management Optimizer.

The validation showed the scanner's entries find turning points (high win rate)
but lose net (PF<1) because the exits are equity-tuned. This sweeps crypto trade
management — ATR stop width, target R-multiple vs trailing, max hold — with a
TRAIN/TEST split so we keep only management that generalises out-of-sample.

Efficiency: each coin's setup signals are computed ONCE (indicators are the
expensive part); every config just re-simulates the forward trade from those
signal bars. Mean-reversion setups additionally require price > 200-SMA
(Connors rule) — buying oversold in a downtrend is what bled the MR setups.
"""
from __future__ import annotations
import copy
import numpy as np
from backtesting.setup_validation import _indicators_at, ACTIONABLE_BUY_SETUPS, _MIN_HISTORY
from backtesting.crypto_validation import _apply_costs, save_validation, validated_setups
from backtesting.setup_validation import _aggregate, recommend_base_scores
from skills.scanner import classify_setup, trade_suggestion
from utils.exchange import get_ohlcv_batch
from utils.crypto_universe import get_top_crypto
from utils.logger import get_logger

log = get_logger(__name__)

# Management configs to sweep (200-SMA filter for MR is always on).
CONFIGS = [
    {"name": "baseline 2.0×ATR / 2R / 20b",  "stop_mult": 2.0, "target_r": 2.0, "trailing": False, "max_hold": 20},
    {"name": "wider 3.0×ATR / 3R / 30b",     "stop_mult": 3.0, "target_r": 3.0, "trailing": False, "max_hold": 30},
    {"name": "let-run 2.5×ATR / 4R / 40b",   "stop_mult": 2.5, "target_r": 4.0, "trailing": False, "max_hold": 40},
    {"name": "trail 2.5×ATR / 40b",          "stop_mult": 2.5, "target_r": 99,  "trailing": True,  "max_hold": 40},
    {"name": "trail 3.5×ATR / 60b",          "stop_mult": 3.5, "target_r": 99,  "trailing": True,  "max_hold": 60},
    {"name": "tight 2.0×ATR / 3R / 15b",     "stop_mult": 2.0, "target_r": 3.0, "trailing": False, "max_hold": 15},
]


def _simulate(close, high, low, i, ind, cfg) -> dict | None:
    """Simulate one trade forward from bar i under a management config."""
    atr = ind.get("atr")
    entry = ind["price"]
    if not atr or atr <= 0:
        return None
    stop = entry - cfg["stop_mult"] * atr
    risk = entry - stop
    if risk <= 0:
        return None
    target = entry + cfg["target_r"] * risk
    n = len(close)
    trail = stop
    exit_p, reason, k = None, "time", 0
    for k in range(1, cfg["max_hold"] + 1):
        j = i + k
        if j >= n:
            k -= 1
            break
        hi, lo, cl = float(high.iloc[j]), float(low.iloc[j]), float(close.iloc[j])
        cur_stop = trail if cfg["trailing"] else stop
        if lo <= cur_stop:                    # stop checked first (conservative)
            exit_p, reason = cur_stop, "stop"; break
        if hi >= target:
            exit_p, reason = target, "target"; break
        if cfg["trailing"]:
            new_stop = cl - cfg["stop_mult"] * atr
            if new_stop > trail:
                trail = new_stop
    if exit_p is None:
        j = min(i + max(k, 1), n - 1)
        exit_p = float(close.iloc[j])
    ret_pct = (exit_p / entry - 1) * 100
    return {"setup": ind["_label"], "win": ret_pct > 0, "ret_pct": ret_pct,
            "r_mult": (exit_p - entry) / risk, "bars_held": k, "reason": reason}


def _signals(close, high, low) -> list[tuple[int, dict]]:
    """Precompute actionable BUY signal bars once (the expensive indicator pass)."""
    out = []
    for i in range(_MIN_HISTORY, len(close) - 1):
        ind = _indicators_at(close, high, low, i)
        if ind is None:
            continue
        label, _d, cat = classify_setup(
            ind["price"], ind["sma50"], ind["sma200"], ind["rsi"], ind["mom3m"],
            ind["bb_pct"], ind["zscore"], ind["williams_r"], ind["rsi2"],
        )
        if label not in ACTIONABLE_BUY_SETUPS:
            continue
        # Connors rule: MR only above the 200-SMA.
        if cat == "mean_reversion" and not (ind["price"] > ind["sma200"]):
            continue
        ts = trade_suggestion(label, ind["price"], ind["sma50"], ind["sma200"],
                              ind["bb_upper"], ind["bb_mid"], ind["bb_lower"],
                              ind["rsi"], ind["mom3m"], ind["atr"])
        if ts.get("action") != "BUY":
            continue
        ind = dict(ind); ind["_label"] = label
        out.append((i, ind))
    return out


def _pool(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "pf": 0.0, "exp_r": 0.0, "win": 0.0}
    gw = sum(t["ret_pct"] for t in trades if t["ret_pct"] > 0)
    gl = abs(sum(t["ret_pct"] for t in trades if t["ret_pct"] <= 0))
    pf = (gw / gl) if gl > 0 else (99.0 if gw > 0 else 0.0)
    return {"n": len(trades), "pf": round(pf, 3),
            "exp_r": round(float(np.mean([t["r_mult"] for t in trades])), 3),
            "win": round(sum(t["win"] for t in trades) / len(trades) * 100, 1)}


def optimize(universe_size: int = 40, days: int = 600,
             cost_pct: float = 0.36, train_frac: float = 0.7) -> dict:
    """
    Sweep management configs. Returns configs ranked by out-of-sample (test) PF.
    """
    tickers = get_top_crypto(universe_size)
    data = get_ohlcv_batch(tickers, timeframe="1d", limit=days)

    # Precompute signals + train/test split index per coin.
    prepared = []
    for sym, df in data.items():
        if len(df) < _MIN_HISTORY + 20:
            continue
        close, high, low = df["close"], df["high"], df["low"]
        sigs = _signals(close, high, low)
        split = int(len(close) * train_frac)
        prepared.append((close, high, low, sigs, split))

    results = []
    for cfg in CONFIGS:
        train, test = [], []
        for close, high, low, sigs, split in prepared:
            for i, ind in sigs:
                t = _simulate(close, high, low, i, ind, cfg)
                if t is None:
                    continue
                (train if i < split else test).append(t)
        train = _apply_costs(train, cost_pct)
        test = _apply_costs(test, cost_pct)
        results.append({"config": cfg, "train": _pool(train), "test": _pool(test)})

    results.sort(key=lambda r: -r["test"]["pf"])
    log.info("optimize: best test PF %.2f (%s)", results[0]["test"]["pf"], results[0]["config"]["name"])
    return {"results": results, "meta": {"coins": len(prepared),
            "days": days, "cost_pct": cost_pct, "train_frac": train_frac}}


def apply_config(cfg: dict, universe_size: int = 40, days: int = 600,
                 cost_pct: float = 0.36, min_n: int = 25) -> dict:
    """
    Re-run full validation under `cfg` (all history), per setup, and SAVE it so
    the scanner's edge gate uses the optimized management. Returns the validation.
    """
    tickers = get_top_crypto(universe_size)
    data = get_ohlcv_batch(tickers, timeframe="1d", limit=days)
    trades = []
    for sym, df in data.items():
        if len(df) < _MIN_HISTORY + 20:
            continue
        close, high, low = df["close"], df["high"], df["low"]
        for i, ind in _signals(close, high, low):
            t = _simulate(close, high, low, i, ind, cfg)
            if t is not None:
                trades.append(t)
    trades = _apply_costs(trades, cost_pct)
    stats = _aggregate(trades)
    res = {
        "stats": stats,
        "recommended": recommend_base_scores(stats, min_n=min_n),
        "validated": sorted(validated_setups(stats, min_n=min_n)),
        "meta": {"universe_requested": len(tickers), "coins_with_data": len(data),
                 "total_trades": len(trades),
                 "params": {"days": days, "cost_pct": cost_pct, "management": cfg}},
    }
    save_validation(res)
    return res
