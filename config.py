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
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# Supabase (shared state for cloud/laptop). When both are set, the triggers/
# watchlist store uses Supabase instead of the local SQLite file — this is what
# lets GitHub Actions run the monitor 24/7 against the same data the app writes.
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

CLAUDE_MODEL = "claude-sonnet-4-6"

# Crypto macro-gate signal weights (normalised automatically by the aggregator).
# The deployment score answers: "should I deploy capital into crypto right now?"
# Primary trend/health signals weighted at 1.0; positioning/sentiment at 0.8;
# rotation and macro-backdrop at 0.6. Tunable via the What-If sliders on page 1.
SIGNAL_WEIGHTS = {
    "crypto_momentum": 1.00,   # BTC golden cross + 3M/12-1 momentum — trend backbone
    "crypto_breadth":  1.00,   # % of top coins above their 50-DMA — market health
    "total_mcap":      1.00,   # total market-cap trend vs its MA — expansion/contraction
    "m2_growth":       0.80,   # global M2 YoY (FRED) — liquidity, carried over
    "funding_regime":  0.80,   # perp funding across top coins — leverage / froth
    "fear_greed":      0.80,   # alternative.me Fear & Greed — sentiment (contrarian)
    "btc_dominance":   0.60,   # BTC vs alts rotation — risk appetite within crypto
    "dxy":             0.60,   # broad USD trend (FRED) — macro backdrop
}

# Deployment score thresholds
DEPLOY_THRESHOLDS = {
    "aggressive":  80,
    "moderate":    60,
    "cautious":    40,
    "avoid":        0,
}

# ── BTC regime veto hooks (v1 = WARNING only; both default off) ────────────────
# When flipped True later, the monitor will refuse to FIRE the relevant direction
# while BTC is in the adverse regime. Left off so the regime read is advisory.
BTC_REGIME_VETO      = False   # True → don't fire LONGS while BTC is RISK-OFF
SHORT_VETO_IN_RISK_ON = False  # True → don't fire SHORTS while BTC is RISK-ON

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
    /* Use the browser width: trim Streamlit's wide side-padding and cap content
       at a comfortable width so it fills large monitors without stretching. */
    .block-container, [data-testid="stMainBlockContainer"] {
        max-width: 1500px;
        padding-left: 2.5rem; padding-right: 2.5rem; padding-top: 2.5rem;
    }
</style>
"""
