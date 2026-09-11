"""
Page 4: Backtests
vectorbt-powered strategy backtesting with equity curve visualization.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from config import DARK_THEME_CSS

st.set_page_config(page_title="Backtests", layout="wide")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

st.title("⏱ Backtests")
st.caption("vectorbt strategy engine · SMA Cross · Macro-Gated · Buy & Hold comparison")
st.divider()

try:
    import vectorbt as vbt
    vbt_ok = True
except ImportError:
    vbt_ok = False
    st.warning(
        "**vectorbt not installed.** Run: `pip install vectorbt` then restart the app.\n\n"
        "The backtest engine will be disabled until then.",
        icon="⚠️",
    )

from backtesting.engine import BacktestConfig, run_backtest

# ── Config form ───────────────────────────────────────────────────────────────
with st.form("backtest_form"):
    c1, c2, c3 = st.columns(3)
    with c1:
        ticker    = st.text_input("Ticker", "SPY")
        start     = st.date_input("Start", pd.Timestamp("2020-01-01"))
        end       = st.date_input("End",   pd.Timestamp("2024-12-31"))
    with c2:
        strategy  = st.selectbox("Strategy", ["sma_cross", "macro_gated"])
        fast_w    = st.number_input("Fast SMA", min_value=5,  max_value=100,  value=50)
        slow_w    = st.number_input("Slow SMA", min_value=50, max_value=500,  value=200)
    with c3:
        init_cash = st.number_input("Initial Cash ($)", value=100_000, step=10_000)
        fees      = st.number_input("Fees (fraction)", value=0.001, step=0.0005, format="%.4f")
        if strategy == "macro_gated":
            min_score = st.slider("Min Deployment Score", 0, 100, 50)
        else:
            min_score = 50.0

    submitted = st.form_submit_button("▶ Run Backtest", type="primary")

if submitted:
    if not vbt_ok:
        st.error("Cannot run backtest: vectorbt not installed.")
        st.stop()

    deploy_scores = []
    if strategy == "macro_gated":
        mr = st.session_state.get("macro_result")
        if mr:
            import time
            deploy_scores = [(time.strftime("%Y-%m-%d"), mr["deployment_score"])]
            st.info(f"Using current deployment score {mr['deployment_score']:.1f} for macro gate.")
        else:
            st.warning("No macro result found — run Macro Gate first for full macro-gated test.")

    cfg = BacktestConfig(
        ticker=ticker.upper(),
        start=str(start),
        end=str(end),
        init_cash=float(init_cash),
        fees=float(fees),
        strategy=strategy,
        fast_window=int(fast_w),
        slow_window=int(slow_w),
        min_deploy_score=float(min_score),
        deploy_scores=deploy_scores,
    )

    with st.spinner("Running backtest …"):
        result = run_backtest(cfg)

    if "error" in result:
        st.error(f"Backtest error: {result['error']}")
    else:
        st.session_state["backtest_result"] = result

bt = st.session_state.get("backtest_result")
if not bt:
    st.info("Configure and run a backtest above.")
    st.stop()

if "error" in bt:
    st.error(bt["error"])
    st.stop()

# ── Key metrics ───────────────────────────────────────────────────────────────
st.divider()
st.subheader(f"Results — {bt['ticker']} · {bt['strategy']} · {bt['period']}")

stats = bt.get("stats", {})
bh_stats = bt.get("bh_stats", {})

m_cols = st.columns(5)
metrics = [
    ("Total Return", f"{bt.get('total_return_pct', 0):.1f}%",
     f"vs B&H {bt.get('bh_return_pct', 0):.1f}%"),
    ("Alpha", f"{bt.get('alpha', 0):.1f}%", None),
    ("Sharpe Ratio", f"{bt.get('sharpe', 0):.2f}", None),
    ("Max Drawdown", f"{bt.get('max_dd', 0):.1f}%", None),
    ("# Trades", str(bt.get("n_trades", 0)), None),
]
for i, (label, val, delta) in enumerate(metrics):
    with m_cols[i]:
        st.metric(label, val, delta=delta)

# ── Equity curve ─────────────────────────────────────────────────────────────
equity = bt.get("equity_curve", {})
price  = bt.get("price", {})

if equity and price:
    eq_s  = pd.Series(equity)
    pr_s  = pd.Series(price)

    # Normalize to 100
    eq_norm = eq_s / eq_s.iloc[0] * 100
    pr_norm = pr_s / pr_s.iloc[0] * 100

    fig = go.Figure()
    fig.add_scatter(
        x=eq_norm.index, y=eq_norm.values,
        name=f"{bt['strategy']} ({bt['ticker']})",
        line=dict(color="#4ade80", width=2),
    )
    fig.add_scatter(
        x=pr_norm.index, y=pr_norm.values,
        name="Buy & Hold",
        line=dict(color="#60a5fa", width=1.5, dash="dot"),
    )
    fig.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#161b22",
        font_color="#cbd5e1",
        xaxis=dict(gridcolor="#30363d"),
        yaxis=dict(gridcolor="#30363d", title="Normalized Value (base 100)"),
        legend=dict(bgcolor="#161b22", bordercolor="#30363d"),
        height=420,
        margin=dict(l=50, r=20, t=20, b=40),
        title="Equity Curve (Normalized to 100)",
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Drawdown ──────────────────────────────────────────────────────────────────
dd = bt.get("drawdown", {})
if dd:
    dd_s = pd.Series(dd) * 100
    fig2 = go.Figure(go.Scatter(
        x=dd_s.index, y=dd_s.values,
        fill="tozeroy", fillcolor="rgba(248,113,113,0.2)",
        line=dict(color="#f87171", width=1),
        name="Drawdown %",
    ))
    fig2.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#161b22",
        font_color="#cbd5e1",
        xaxis=dict(gridcolor="#30363d"),
        yaxis=dict(gridcolor="#30363d", title="Drawdown %", autorange="reversed"),
        height=220,
        margin=dict(l=50, r=20, t=20, b=30),
        showlegend=False,
        title="Drawdown",
    )
    st.plotly_chart(fig2, use_container_width=True)

# ── Full stats table ──────────────────────────────────────────────────────────
with st.expander("Full Statistics"):
    stat_rows = []
    for k in stats:
        stat_rows.append({
            "Metric": k,
            "Strategy": stats.get(k, "—"),
            "Buy & Hold": bh_stats.get(k, "—"),
        })
    st.dataframe(pd.DataFrame(stat_rows), use_container_width=True, hide_index=True)
