from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env", override=True)
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "trading.db"
CACHE_PATH = DATA_DIR / "analyst_cache.db"

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")

CLAUDE_MODEL = "claude-sonnet-4-6"

# Macro signal relative weights (normalised automatically by aggregator).
# Methodology: equal weighting as base, with correlated signals down-weighted.
# VIX level + term structure are correlated → each weighted at 0.8 of base.
# Yield curve has long lead times (12-24 months) → 0.8 of base.
# Monthly signals (M2) → 0.8 of base due to data lag.
# Inflation breakeven is a regime classifier more than a timing signal → 0.6.
# Sources: AQR multi-factor framework, IMF FCI equal-weighting research (2022).
SIGNAL_WEIGHTS = {
    # Original 7 signals (rebalanced)
    "vix_level":          0.80,   # high correlation with term structure → reduced
    "vix_term_structure": 0.80,   # high correlation with vix_level → reduced
    "breadth":            1.00,
    "credit_spreads":     1.00,
    "put_call":           1.00,   # improved with VIX9D component
    "yield_curve":        0.80,   # strong but long lead time → reduced
    "momentum":           1.00,
    # New institutional signals (FRED)
    "nfci":               1.00,   # Chicago Fed Financial Conditions — composite, daily
    "m2_growth":          0.80,   # M2 money supply YoY — monthly lag
    "inflation":          0.60,   # 10Y TIPS breakeven — regime signal, not timing
}

# Deployment score thresholds
DEPLOY_THRESHOLDS = {
    "aggressive":  80,
    "moderate":    60,
    "cautious":    40,
    "avoid":        0,
}

# Analyst blender weights
QUANT_WEIGHT = 0.60
CLAUDE_WEIGHT = 0.40

# Lookback for signal calculations
LOOKBACK_DAYS = 252          # 1 trading year
LOOKBACK_DAYS_SHORT = 63     # 1 quarter

# Analyst quarters
ANALYST_QUARTERS = 8
TTM_LABEL = "TTM"

# Peer groups by sector (representative tickers)
PEER_GROUPS: dict[str, list[str]] = {
    "Technology":          ["AAPL", "MSFT", "GOOGL", "META", "NVDA"],
    "Financials":          ["JPM", "BAC", "GS", "MS", "WFC"],
    "Healthcare":          ["JNJ", "UNH", "PFE", "MRK", "ABBV"],
    "Consumer Discretionary": ["AMZN", "TSLA", "HD", "MCD", "NKE"],
    "Industrials":         ["CAT", "HON", "UPS", "MMM", "GE"],
    "Energy":              ["XOM", "CVX", "COP", "SLB", "EOG"],
    "Consumer Staples":    ["PG", "KO", "PEP", "COST", "WMT"],
    "Utilities":           ["NEE", "DUK", "SO", "D", "AEP"],
    "Real Estate":         ["AMT", "PLD", "CCI", "EQIX", "SPG"],
    "Materials":           ["LIN", "APD", "SHW", "FCX", "NEM"],
    "Communication":       ["GOOGL", "META", "NFLX", "DIS", "CMCSA"],
}

DARK_THEME_CSS = """
<style>
    [data-testid="stAppViewContainer"] { background-color: #0e1117; }
    [data-testid="stSidebar"] { background-color: #161b22; }
    .metric-card {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 16px;
        text-align: center;
    }
    .score-pill {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 0.85rem;
    }
    .score-green  { background: #1a4731; color: #4ade80; }
    .score-yellow { background: #3d3500; color: #facc15; }
    .score-red    { background: #4a1515; color: #f87171; }
    .rank-up   { color: #4ade80; font-weight: 700; }
    .rank-down { color: #f87171; font-weight: 700; }
    .rank-flat { color: #94a3b8; }
    hr { border-color: #30363d; }
</style>
"""
