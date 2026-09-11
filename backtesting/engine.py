"""
Backtesting engine using vectorbt.
Supports simple momentum + macro-gated strategies.
Returns price chart data (SMAs + entry/exit signals) for visualisation.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
import yfinance as yf

try:
    import vectorbt as vbt
    VBT_AVAILABLE = True
except ImportError:
    VBT_AVAILABLE = False

from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class BacktestConfig:
    ticker: str = "SPY"
    start: str = "2020-01-01"
    end: str = "2024-12-31"
    init_cash: float = 100_000.0
    fees: float = 0.001          # 0.1% per trade
    strategy: str = "sma_cross"  # sma_cross | macro_gated
    fast_window: int = 50
    slow_window: int = 200
    # For macro_gated: deployment score threshold to be in market
    min_deploy_score: float = 50.0
    deploy_scores: list[tuple[str, float]] = field(default_factory=list)


def run_backtest(cfg: BacktestConfig) -> dict:
    if not VBT_AVAILABLE:
        return {"error": "vectorbt not installed. Run: pip install vectorbt"}

    log.info("Running backtest: %s %s → %s [%s]", cfg.ticker, cfg.start, cfg.end, cfg.strategy)

    df = yf.download(cfg.ticker, start=cfg.start, end=cfg.end,
                     interval="1d", progress=False, auto_adjust=True)
    if df.empty:
        return {"error": f"No price data for {cfg.ticker}"}

    # yfinance ≥1.4 returns MultiIndex columns — squeeze to Series
    price = df["Close"].squeeze().dropna()

    # Compute SMAs at top level so we can return them for charting
    sma_fast = price.rolling(cfg.fast_window).mean()
    sma_slow = price.rolling(cfg.slow_window).mean()

    if cfg.strategy == "sma_cross":
        entries, exits = _sma_cross_signals(sma_fast, sma_slow)
    elif cfg.strategy == "macro_gated":
        entries, exits = _macro_gated_signals(
            price, sma_fast, sma_slow,
            cfg.deploy_scores, cfg.min_deploy_score,
        )
    else:
        return {"error": f"Unknown strategy: {cfg.strategy}"}

    pf = vbt.Portfolio.from_signals(
        price,
        entries=entries,
        exits=exits,
        init_cash=cfg.init_cash,
        fees=cfg.fees,
        freq="D",
    )

    stats       = pf.stats()
    equity_curve = pf.value()
    drawdown    = pf.drawdown()

    # Buy & Hold benchmark
    bh      = vbt.Portfolio.from_holding(price, init_cash=cfg.init_cash, fees=cfg.fees)
    bh_stats = bh.stats()

    # ── Extract entry / exit points for chart markers ─────────────────────────
    entry_mask = entries.fillna(False)
    exit_mask  = exits.fillna(False)

    def _ts_key(ts):
        """Convert Timestamp → YYYY-MM-DD string."""
        return str(ts.date()) if hasattr(ts, "date") else str(ts)[:10]

    entry_dates  = [_ts_key(d) for d in price.index[entry_mask]]
    entry_prices = [float(v) for v in price[entry_mask]]
    exit_dates   = [_ts_key(d) for d in price.index[exit_mask]]
    exit_prices  = [float(v) for v in price[exit_mask]]

    # ── Serialise time series ─────────────────────────────────────────────────
    def _ser(s: pd.Series) -> dict:
        return {_ts_key(k): (None if pd.isna(v) else float(v)) for k, v in s.items()}

    return {
        "ticker":           cfg.ticker,
        "strategy":         cfg.strategy,
        "period":           f"{cfg.start} → {cfg.end}",
        "fast_window":      cfg.fast_window,
        "slow_window":      cfg.slow_window,
        "stats":            _stats_dict(stats),
        "bh_stats":         _stats_dict(bh_stats),
        "equity_curve":     _ser(equity_curve),
        "drawdown":         _ser(drawdown),
        "price":            _ser(price),
        "sma_fast":         _ser(sma_fast),
        "sma_slow":         _ser(sma_slow),
        "entry_dates":      entry_dates,
        "entry_prices":     entry_prices,
        "exit_dates":       exit_dates,
        "exit_prices":      exit_prices,
        "n_trades":         int(pf.trades.count()),
        "sharpe":           _safe_float(stats.get("Sharpe Ratio", np.nan)),
        "max_dd":           _safe_float(stats.get("Max Drawdown [%]", np.nan)),
        "total_return_pct": _safe_float(stats.get("Total Return [%]", np.nan)),
        "bh_return_pct":    _safe_float(bh_stats.get("Total Return [%]", np.nan)),
        "alpha":            _safe_float(stats.get("Total Return [%]", 0) - bh_stats.get("Total Return [%]", 0)),
    }


# ── Signal generators ─────────────────────────────────────────────────────────

def _sma_cross_signals(sma_fast: pd.Series, sma_slow: pd.Series):
    entries = (sma_fast > sma_slow) & (sma_fast.shift(1) <= sma_slow.shift(1))
    exits   = (sma_fast < sma_slow) & (sma_fast.shift(1) >= sma_slow.shift(1))
    return entries, exits


def _macro_gated_signals(price: pd.Series, sma_fast: pd.Series, sma_slow: pd.Series,
                          deploy_scores: list[tuple[str, float]], threshold: float):
    entries_raw, exits_raw = _sma_cross_signals(sma_fast, sma_slow)

    if not deploy_scores:
        return entries_raw, exits_raw

    score_series = pd.Series(
        {pd.Timestamp(d): s for d, s in deploy_scores},
        name="deploy",
    ).reindex(price.index, method="ffill")

    gate    = score_series >= threshold
    entries = entries_raw & gate
    exits   = exits_raw | (~gate)
    return entries, exits


def _safe_float(v) -> float | None:
    """Convert numeric to float, returning None for NaN/Inf (not JSON-safe)."""
    try:
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _stats_dict(stats) -> dict:
    if hasattr(stats, "to_dict"):
        d = stats.to_dict()
    elif isinstance(stats, dict):
        d = stats
    else:
        return {}
    out = {}
    for k, v in d.items():
        if isinstance(v, (int, float, np.number)):
            out[k] = _safe_float(v)
        else:
            out[k] = str(v)
    return out
