"""
Paper Trades — Transaction-cost model.

Implements the execution-realism fix from docs/INSTITUTIONAL_ROADMAP.md §4.
The roadmap's recommended fill model is:

    fill = midprice + half-spread + commission + square-root market impact

A frictionless paper P&L systematically inflates returns AND biases the
reward signal the conviction-learning loop trains on. This module charges a
realistic round-trip cost (entry side + exit side) on every closed trade so
the learning loop sees NET returns.

We deliberately keep the model asset-class + price aware (not live-volume
aware), because the originating scan's `vol_usd_m` is not persisted on the
trade row. The √-impact term from the roadmap requires order-size / ADV,
which we don't have here, so it is folded into a conservative flat slippage
allowance per asset class. Numbers are module-level constants for easy tuning.

All costs are expressed in basis points (1 bp = 0.01%). A "round trip" is
both the entry fill and the exit fill, so per-side costs are doubled.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Cost constants (basis points PER SIDE). 1 bp = 0.01% of notional.
# ---------------------------------------------------------------------------

# Stocks / ETFs (liquid US equities via a retail/IBKR-style fee schedule):
#   commission ~1 bp/side + half-spread slippage ~3 bps/side = 4 bps/side
#   → ~8 bps round trip (0.08%).
STOCK_COMMISSION_BPS = 1.0      # per side
STOCK_SLIPPAGE_BPS   = 3.0      # per side (half-spread + minor impact)

# Sub-$5 / penny names have far wider spreads — bump the slippage allowance.
PENNY_PRICE_THRESHOLD = 5.0     # USD
PENNY_SLIPPAGE_BPS    = 25.0    # per side (replaces STOCK_SLIPPAGE_BPS)

# Crypto (Bybit taker schedule + chunkier spreads):
#   taker fee ~10 bps/side + slippage ~8 bps/side = 18 bps/side
#   → ~36 bps round trip (0.36%).
CRYPTO_FEE_BPS      = 10.0      # per side (taker)
CRYPTO_SLIPPAGE_BPS = 8.0       # per side (half-spread + impact)

_BPS_TO_PCT = 0.01              # 1 bp = 0.01%


def classify_asset(ticker: str) -> str:
    """Return "crypto" or "stock" for a ticker.

    Crypto if the symbol contains "-USD" (e.g. "BTC-USD") or ends in "USDT"
    (e.g. "BTCUSDT"). Everything else is treated as a stock/ETF.
    """
    t = (ticker or "").upper()
    if "-USD" in t or t.endswith("USDT"):
        return "crypto"
    return "stock"


def round_trip_cost_pct(ticker: str, entry_price: float) -> float:
    """Total round-trip transaction cost as a percentage of notional.

    Includes the entry side and the exit side (commission/fee + slippage).
    Returns a positive percentage to be SUBTRACTED from gross P&L.

    Examples:
        round_trip_cost_pct("AAPL", 150)     -> 0.08   (8 bps)
        round_trip_cost_pct("BTC-USD", 60000)-> 0.36   (36 bps)
    """
    asset = classify_asset(ticker)

    if asset == "crypto":
        per_side_bps = CRYPTO_FEE_BPS + CRYPTO_SLIPPAGE_BPS
    else:
        slippage = STOCK_SLIPPAGE_BPS
        # Penny-stock spreads dominate cost for sub-$5 names.
        if entry_price is not None and entry_price < PENNY_PRICE_THRESHOLD:
            slippage = PENNY_SLIPPAGE_BPS
        per_side_bps = STOCK_COMMISSION_BPS + slippage

    round_trip_bps = per_side_bps * 2.0
    return round_trip_bps * _BPS_TO_PCT
