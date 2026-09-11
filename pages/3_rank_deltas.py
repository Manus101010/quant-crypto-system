"""
Page 3: Rank Deltas
Shows movers: which stocks were upgraded/downgraded by 3+ positions.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from config import DARK_THEME_CSS

st.set_page_config(page_title="Rank Deltas", layout="wide")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

st.title("📈 Rank Deltas")
st.caption("Rank changes of ≥3 positions between analysis runs")
st.divider()

ranked = st.session_state.get("analyst_results", [])
if not ranked:
    st.info("Run **Analyst Rankings** first to see rank delta data.")
    st.stop()

# ── Delta summary ─────────────────────────────────────────────────────────────
upgrades   = [c for c in ranked if c.get("rank_delta", 0) >= 3]
downgrades = [c for c in ranked if c.get("rank_delta", 0) <= -3]
unchanged  = [c for c in ranked if abs(c.get("rank_delta", 0)) < 3]

m1, m2, m3 = st.columns(3)
m1.metric("Upgrades (≥3)", len(upgrades),   delta=None)
m2.metric("Downgrades (≥3)", len(downgrades), delta=None)
m3.metric("Unchanged (<3)", len(unchanged),  delta=None)

st.divider()

col_up, col_dn = st.columns(2)

with col_up:
    st.markdown("### 🟢 Upgraded")
    if not upgrades:
        st.caption("No significant upgrades this run.")
    for c in sorted(upgrades, key=lambda x: x.get("rank_delta", 0), reverse=True):
        delta = c["rank_delta"]
        prev  = c.get("prev_rank")
        curr  = c["rank"]
        with st.container():
            st.markdown(
                f'<div style="background:#0f2e1a;border:1px solid #4ade80;border-radius:8px;'
                f'padding:12px;margin:6px 0">'
                f'<span style="font-size:1.1rem;font-weight:700;color:#4ade80">{c["ticker"]}</span>'
                f'<span style="color:#94a3b8;font-size:0.85rem"> · {c.get("name","")[:20]}</span><br>'
                f'<span style="color:#4ade80;font-weight:700">▲{delta} positions</span> '
                f'<span style="color:#475569;font-size:0.8rem">#{prev} → #{curr}</span><br>'
                f'<span style="color:#cbd5e1;font-size:0.85rem">Score: {c["blended_score"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

with col_dn:
    st.markdown("### 🔴 Downgraded")
    if not downgrades:
        st.caption("No significant downgrades this run.")
    for c in sorted(downgrades, key=lambda x: x.get("rank_delta", 0)):
        delta = c["rank_delta"]
        prev  = c.get("prev_rank")
        curr  = c["rank"]
        with st.container():
            st.markdown(
                f'<div style="background:#2e0f0f;border:1px solid #f87171;border-radius:8px;'
                f'padding:12px;margin:6px 0">'
                f'<span style="font-size:1.1rem;font-weight:700;color:#f87171">{c["ticker"]}</span>'
                f'<span style="color:#94a3b8;font-size:0.85rem"> · {c.get("name","")[:20]}</span><br>'
                f'<span style="color:#f87171;font-weight:700">▼{abs(delta)} positions</span> '
                f'<span style="color:#475569;font-size:0.8rem">#{prev} → #{curr}</span><br>'
                f'<span style="color:#cbd5e1;font-size:0.85rem">Score: {c["blended_score"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

# ── Full delta table ──────────────────────────────────────────────────────────
st.divider()
st.subheader("Full Delta Table")

rows = []
for c in ranked:
    d = c.get("rank_delta", 0)
    rows.append({
        "Rank":    c["rank"],
        "Ticker":  c["ticker"],
        "Score":   c["blended_score"],
        "Δ Rank":  d,
        "Prev":    c.get("prev_rank", "—"),
        "Flag":    "⚑" if c.get("rank_flag") else "",
        "Sector":  c.get("sector", "")[:18],
    })

df = pd.DataFrame(rows)

def color_delta(val):
    try:
        v = float(val)
        if v >= 3:
            return "color: #4ade80; font-weight:700"
        if v <= -3:
            return "color: #f87171; font-weight:700"
        return "color: #94a3b8"
    except Exception:
        return ""

styled = df.style.applymap(color_delta, subset=["Δ Rank"])
st.dataframe(styled, use_container_width=True, hide_index=True)

# ── Waterfall chart ───────────────────────────────────────────────────────────
st.divider()
st.subheader("Score Comparison: Quant vs Claude")

tickers = [c["ticker"] for c in ranked]
quant   = [c["quant_score"] for c in ranked]
claude  = [c["claude_norm"]  for c in ranked]
blended = [c["blended_score"] for c in ranked]

fig = go.Figure()
fig.add_bar(name="Quant (60%)",  x=tickers, y=quant,   marker_color="#60a5fa", opacity=0.8)
fig.add_bar(name="Claude (40%)", x=tickers, y=claude,  marker_color="#c084fc", opacity=0.8)
fig.add_scatter(name="Blended", x=tickers, y=blended,
                mode="lines+markers",
                marker=dict(color="#4ade80", size=8),
                line=dict(color="#4ade80", width=2))
fig.update_layout(
    barmode="group",
    paper_bgcolor="#0e1117", plot_bgcolor="#161b22",
    font_color="#cbd5e1",
    xaxis=dict(gridcolor="#30363d"),
    yaxis=dict(gridcolor="#30363d", range=[0, 110]),
    legend=dict(bgcolor="#161b22", bordercolor="#30363d"),
    height=380,
    margin=dict(l=40, r=20, t=20, b=40),
)
st.plotly_chart(fig, use_container_width=True)
