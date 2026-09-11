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
    st.markdown("## 📊 Quant Crypto System")
    st.caption("Macro Gate · Scanner · Journal")
    st.divider()
    st.markdown("**Navigation**")
    st.page_link("pages/1_macro_gate.py", label="🌐 Macro Gate", icon="🌐")
    st.page_link("pages/6_scanner.py",    label="🛰️ Scanner",     icon="🛰️")
    st.page_link("pages/5_journal.py",    label="📓 Journal",     icon="📓")
    st.divider()
    st.caption("Signal-only · you execute manually")

# ── Home splash ───────────────────────────────────────────────────────────────
st.title("Quant Crypto Trading System")
st.markdown("""
A **signal-only** crypto intelligence system — it scans, ranks, and alerts;
**you** execute every trade manually.

| Module | Description |
|--------|-------------|
| **🌐 Macro Gate** | 8-signal crypto deployment score — *is the regime risk-on right now?* |
| **🛰️ Scanner** | Screens liquid coins for mean-reversion & momentum setups, arms triggers |
| **📱 Monitor** | Standalone `monitor.py` watches triggers and pushes Telegram alerts |
| **📓 Journal** | Log your manual trades and ideas |

---

### Quick Start
1. **Macro Gate** — check the crypto regime.
2. **Scanner** — run a scan, arm the top setups as triggers.
3. Run the monitor on an always-on host (`python monitor.py`) for phone alerts.
4. Log fills in the **Journal**.

---
""")

col1, col2, col3 = st.columns(3)
with col1:
    st.info("**8 Crypto Macro Signals**\nBTC Momentum, Breadth, Total Mcap, M2, Funding, Fear & Greed, BTC.D, DXY")
with col2:
    st.info("**Mean-Reversion-Weighted Scanner**\nRSI/BB/z-score setups on the liquid ccxt universe, ranked by composite")
with col3:
    st.info("**Telegram Alerts**\nStandalone monitor fires phone alerts when a trigger condition is met — signal only")
