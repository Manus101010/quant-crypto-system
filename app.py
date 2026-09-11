"""
Main Streamlit entry point.
Renders the home / Macro Gate page and sets global config.
Navigate via the sidebar to other pages.
"""
import streamlit as st
from config import DARK_THEME_CSS

st.set_page_config(
    page_title="Quant AI Trading System",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

# ── Sidebar branding ──────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📊 Quant AI System")
    st.caption("Macro Gate · Analyst Rankings · Backtests · Journal")
    st.divider()
    st.markdown("**Navigation**")
    st.page_link("pages/1_macro_gate.py",       label="🌐 Macro Gate",        icon="🌐")
    st.page_link("pages/6_scanner.py",          label="🛰️ Scanner",           icon="🛰️")
    st.page_link("pages/2_analyst_rankings.py", label="🔬 Analyst Rankings",  icon="🔬")
    st.page_link("pages/3_rank_deltas.py",      label="📈 Rank Deltas",       icon="📈")
    st.page_link("pages/4_backtests.py",        label="⏱  Backtests",         icon="⏱")
    st.page_link("pages/5_journal.py",          label="📓 Journal",           icon="📓")
    st.divider()
    st.caption("Powered by Claude + yfinance")

# ── Home splash ───────────────────────────────────────────────────────────────
st.title("Quant AI Trading System")
st.markdown("""
A professional two-layer trading intelligence system:

| Layer | Module | Description |
|-------|--------|-------------|
| **L1** | Macro Gate | 7-signal deployment scoring — *should I be in the market right now?* |
| **L3** | Claude Analyst | AI-powered fundamental analysis — *which stocks deserve capital?* |

---

### Quick Start
1. Go to **Macro Gate** to check current market conditions.
2. Run **Analyst Rankings** to score your watchlist.
3. Review **Rank Deltas** for upgrades / downgrades.
4. Use **Backtests** to validate strategy ideas.
5. Log trades and ideas in the **Journal**.

---
""")

col1, col2, col3 = st.columns(3)
with col1:
    st.info("**7 Macro Signals**\nVIX, Term Structure, Breadth, Credit, Sentiment, Yield Curve, Momentum")
with col2:
    st.info("**Claude L3 Analyst**\n7 scoring dimensions with chain-of-thought, self-critique & peer benchmarks")
with col3:
    st.info("**vectorbt Backtests**\nSMA cross & macro-gated strategies with full equity curves")
