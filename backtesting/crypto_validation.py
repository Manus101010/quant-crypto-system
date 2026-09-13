"""
Crypto Setup Validation — the institutional-grade honesty check.

Runs a walk-forward backtest of the scanner's OWN setups over the liquid crypto
universe (ccxt data) to measure each setup's REAL historical edge — win rate,
profit factor, expectancy — net of realistic crypto transaction costs. This
replaces heuristic base-conviction priors with numbers measured on crypto.

No look-ahead: at each bar the scanner's indicators are computed on data up to
that bar only; the trade is then simulated forward. Reuses the (data-source
agnostic) walk/aggregate/recommend engine from setup_validation.py.
"""
from __future__ import annotations
import copy
import json
from backtesting.setup_validation import (
    _walk_ticker, _aggregate, recommend_base_scores, _MIN_HISTORY,
)
from config import DATA_DIR
from utils.exchange import get_ohlcv_batch
from utils.crypto_universe import get_top_crypto
from utils.logger import get_logger

log = get_logger(__name__)

_SAVE_PATH = DATA_DIR / "crypto_validation.json"
_MIN_EDGE_PF = 1.0     # only setups with PF above this (net of cost) are tradeable
_MIN_EDGE_N  = 25      # ...and at least this many backtested trades to be trusted

# Round-trip crypto cost: taker fee (~10bps/side) + slippage (~8bps/side) ≈ 0.36%.
_COST_PCT = 0.36


def _apply_costs(trades: list[dict], cost_pct: float) -> list[dict]:
    """Deduct a round-trip cost from each trade so P&L is honest (recompute win)."""
    out = []
    for t in trades:
        t = copy.copy(t)
        gross = t["ret_pct"]
        net = gross - cost_pct
        # Scale the R-multiple by the same proportion (guard near-zero gross).
        if abs(gross) > 1e-9:
            t["r_mult"] = t["r_mult"] * (net / gross)
        else:
            t["r_mult"] = t["r_mult"] - cost_pct / 5.0
        t["ret_pct"] = net
        t["win"] = net > 0
        out.append(t)
    return out


def run_crypto_validation(universe_size: int = 40, days: int = 600,
                          max_hold: int = 20, step: int = 1, cooldown: int = 5,
                          cost_pct: float = _COST_PCT, min_n: int = 30,
                          source: str = "top_mcap", max_coins: int = 500) -> dict:
    """
    Walk-forward validate the scanner setups over the chosen universe.
    `source`: "top_mcap" (top-`universe_size` by market cap) or "mexc" (the real
    MEXC USDT spot universe, capped at `max_coins`). Stats are NET of `cost_pct`.
    """
    if source == "mexc":
        from utils.exchange import list_spot_symbols
        tickers, exchange = list_spot_symbols("mexc")[:max_coins], "mexc"
    else:
        tickers, exchange = get_top_crypto(universe_size), None
    data = get_ohlcv_batch(tickers, timeframe="1d", limit=days, exchange=exchange)

    all_trades: list[dict] = []
    used = 0
    for sym, df in data.items():
        if len(df) < _MIN_HISTORY + 5:
            continue
        used += 1
        vol = df["volume"] if "volume" in df.columns else None
        trades = _walk_ticker(df["close"], df["high"], df["low"], max_hold, step, cooldown, vol)
        all_trades.extend(_apply_costs(trades, cost_pct))

    stats = _aggregate(all_trades)
    recommended = recommend_base_scores(stats, min_n=min_n)
    log.info("crypto_validation: %d coins, %d trades, %d setups",
             used, len(all_trades), len(stats))
    res = {
        "stats": stats,
        "recommended": recommended,
        "validated": sorted(validated_setups(stats)),
        "meta": {
            "universe_requested": len(tickers),
            "coins_with_data": used,
            "total_trades": len(all_trades),
            "source": source,
            "params": {"days": days, "max_hold": max_hold, "step": step,
                       "cooldown": cooldown, "cost_pct": cost_pct},
        },
    }
    return res


# ── Edge gate: which setups are actually tradeable ────────────────────────────
def validated_setups(stats: dict[str, dict],
                      min_pf: float = _MIN_EDGE_PF, min_n: int = _MIN_EDGE_N) -> set[str]:
    """Setups with a measured positive edge (PF>min_pf, net of cost) and enough trades."""
    out = set()
    for label, s in stats.items():
        pf = s.get("profit_factor")
        if pf is None:                       # inf PF (no losers) → treat as strong
            pf = 99.0
        if pf > min_pf and (s.get("n") or 0) >= min_n:
            out.add(label)
    return out


def save_validation(res: dict) -> None:
    try:
        _SAVE_PATH.write_text(json.dumps(res, indent=2, default=str))
    except Exception as exc:                 # noqa: BLE001
        log.warning("crypto_validation: save failed — %s", exc)


def load_validation() -> dict | None:
    try:
        if _SAVE_PATH.exists():
            return json.loads(_SAVE_PATH.read_text())
    except Exception:                        # noqa: BLE001
        pass
    return None


def validated_labels() -> set[str] | None:
    """Load the saved set of tradeable setups, or None if no validation has run."""
    v = load_validation()
    if not v:
        return None
    return set(v.get("validated", []))
