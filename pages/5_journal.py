"""
Page 5: Trading Journal
Log trades, ideas, and reviews. Track P&L and deployment context.
"""
import streamlit as st
import plotly.express as px
import pandas as pd
from config import DARK_THEME_CSS
from journal.db import add_entry, get_entries, delete_entry, update_entry

st.set_page_config(page_title="Journal", layout="wide")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

st.title("📓 Trading Journal")
st.caption("Log trades · ideas · reviews · Track P&L in context of macro regime")
st.divider()

# ── Add entry form ─────────────────────────────────────────────────────────────
with st.expander("➕ New Entry", expanded=False):
    with st.form("new_entry"):
        c1, c2, c3 = st.columns(3)
        with c1:
            entry_type = st.selectbox("Type", ["trade", "idea", "note", "review"])
            ticker     = st.text_input("Ticker (optional)").upper()
            direction  = st.selectbox("Direction", ["", "long", "short", "flat"])
        with c2:
            entry_price = st.number_input("Entry Price", min_value=0.0, step=0.01)
            exit_price  = st.number_input("Exit Price",  min_value=0.0, step=0.01)
            size_pct    = st.number_input("Position Size %", min_value=0.0, max_value=100.0, step=0.5)
        with c3:
            tags = st.text_input("Tags (comma-separated)", placeholder="momentum, earnings")
            mr = st.session_state.get("macro_result", {})
            deploy_score = st.number_input(
                "Deployment Score",
                value=float(mr.get("deployment_score", 50.0)),
                step=0.1,
            )
            regime = st.text_input("Regime", value=mr.get("regime", ""))

        rationale = st.text_area("Rationale / Thesis", height=80)
        outcome   = st.text_area("Outcome / Notes (fill after close)", height=50)

        if st.form_submit_button("💾 Save Entry"):
            pnl = None
            if entry_price > 0 and exit_price > 0:
                pnl = (exit_price - entry_price) / entry_price * 100
                if direction == "short":
                    pnl = -pnl

            eid = add_entry(
                entry_type=entry_type,
                ticker=ticker or None,
                direction=direction or None,
                entry_price=entry_price or None,
                exit_price=exit_price or None,
                size_pct=size_pct or None,
                pnl_pct=pnl,
                tags=tags or None,
                deploy_score=deploy_score,
                regime=regime or None,
                rationale=rationale or None,
                outcome=outcome or None,
            )
            st.success(f"Entry #{eid} saved!")
            st.rerun()

# ── Filters ────────────────────────────────────────────────────────────────────
fc1, fc2 = st.columns(2)
with fc1:
    filter_type   = st.selectbox("Filter by type", ["all", "trade", "idea", "note", "review"])
with fc2:
    filter_ticker = st.text_input("Filter by ticker", "").upper()

etype  = None if filter_type == "all" else filter_type
etick  = filter_ticker or None
entries = get_entries(entry_type=etype, ticker=etick, limit=200)

# ── Metrics ────────────────────────────────────────────────────────────────────
trades = [e for e in entries if e["entry_type"] == "trade" and e["pnl_pct"] is not None]
if trades:
    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Trades Logged", len(trades))
    m2.metric("Win Rate", f"{len(wins)/len(pnls)*100:.0f}%")
    m3.metric("Avg P&L", f"{sum(pnls)/len(pnls):.2f}%")
    m4.metric("Total P&L", f"{sum(pnls):.2f}%")
    st.divider()

# ── Entry list ─────────────────────────────────────────────────────────────────
if not entries:
    st.info("No journal entries yet. Add one above.")
else:
    for entry in entries:
        pnl = entry.get("pnl_pct")
        pnl_color = "#4ade80" if (pnl or 0) > 0 else "#f87171" if (pnl or 0) < 0 else "#94a3b8"
        pnl_str   = f"{pnl:+.2f}%" if pnl is not None else ""

        ticker_str = f"**{entry['ticker']}**" if entry.get("ticker") else ""
        dir_str    = f"_{entry['direction']}_" if entry.get("direction") else ""
        type_badge = {
            "trade":  "🔵", "idea": "💡", "note": "📝", "review": "🔍"
        }.get(entry["entry_type"], "📌")

        with st.expander(
            f"{type_badge} {entry['entry_type'].upper()} | "
            f"{ticker_str} {dir_str} {pnl_str} — {entry['created_at'][:10]}"
        ):
            c1, c2, c3 = st.columns([2, 2, 1])
            with c1:
                st.markdown(f"**Ticker:** {entry.get('ticker','—')}")
                st.markdown(f"**Direction:** {entry.get('direction','—')}")
                st.markdown(f"**Entry:** {entry.get('entry_price','—')}  |  **Exit:** {entry.get('exit_price','—')}")
                if pnl is not None:
                    st.markdown(f"**P&L:** <span style='color:{pnl_color}'>{pnl_str}</span>",
                                unsafe_allow_html=True)
            with c2:
                st.markdown(f"**Regime:** {entry.get('regime','—')}")
                st.markdown(f"**Deploy Score:** {entry.get('deploy_score','—')}")
                st.markdown(f"**Tags:** {entry.get('tags','—')}")
            with c3:
                if st.button("🗑 Delete", key=f"del_{entry['id']}"):
                    delete_entry(entry["id"])
                    st.rerun()

            if entry.get("rationale"):
                st.markdown("**Rationale:**")
                st.markdown(entry["rationale"])
            if entry.get("outcome"):
                st.markdown("**Outcome:**")
                st.markdown(entry["outcome"])

# ── P&L chart ─────────────────────────────────────────────────────────────────
if len(trades) >= 3:
    st.divider()
    st.subheader("P&L History")
    trade_df = pd.DataFrame(trades)
    trade_df["created_at"] = pd.to_datetime(trade_df["created_at"])
    trade_df = trade_df.sort_values("created_at")
    trade_df["cumulative_pnl"] = trade_df["pnl_pct"].cumsum()

    fig = px.bar(
        trade_df, x="created_at", y="pnl_pct",
        color="pnl_pct",
        color_continuous_scale=["#f87171", "#facc15", "#4ade80"],
        labels={"pnl_pct": "P&L %", "created_at": "Date"},
        title="Trade P&L",
    )
    fig.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#161b22",
        font_color="#cbd5e1",
        xaxis=dict(gridcolor="#30363d"),
        yaxis=dict(gridcolor="#30363d"),
        coloraxis_showscale=False,
        height=300,
        margin=dict(l=40, r=20, t=40, b=30),
    )
    st.plotly_chart(fig, use_container_width=True)

    fig2 = px.line(
        trade_df, x="created_at", y="cumulative_pnl",
        title="Cumulative P&L %",
        labels={"cumulative_pnl": "Cumulative P&L %"},
    )
    fig2.update_traces(line_color="#4ade80")
    fig2.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#161b22",
        font_color="#cbd5e1",
        xaxis=dict(gridcolor="#30363d"),
        yaxis=dict(gridcolor="#30363d"),
        height=250,
        margin=dict(l=40, r=20, t=40, b=30),
    )
    st.plotly_chart(fig2, use_container_width=True)
