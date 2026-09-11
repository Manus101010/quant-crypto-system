"""
Page 2: Analyst Rankings
Run Claude L3 analysis on a watchlist; show blended scores and dimension breakdowns.
"""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from config import DARK_THEME_CSS
from skills.scanner import DEFAULT_WATCHLIST

st.set_page_config(page_title="Analyst Rankings", layout="wide")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

st.title("🔬 Analyst Rankings")
st.caption("Claude L3 fundamental analysis · Chain-of-Thought · Peer benchmarking")
st.divider()

# ── Controls ──────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns([3, 1, 1])
with col1:
    tickers_raw = st.text_input(
        "Tickers (comma-separated)",
        value=", ".join(DEFAULT_WATCHLIST[:12]),
        help="Enter tickers to analyze. Claude API will be called for each.",
    )
with col2:
    force_refresh = st.checkbox("Force Re-analyze", value=False,
                                 help="Bypass cache and re-call Claude")
with col3:
    run_btn = st.button("🚀 Analyze", type="primary", use_container_width=True)

tickers = [t.strip().upper() for t in tickers_raw.split(",") if t.strip()]

# ── Dimension radar for a single ticker ──────────────────────────────────────
def radar_for_ticker(scores: dict, ticker: str) -> go.Figure:
    dims = list(scores.keys())
    vals = [scores[d] for d in dims]
    dims_plot = dims + [dims[0]]
    vals_plot  = vals + [vals[0]]
    fig = go.Figure(go.Scatterpolar(
        r=vals_plot, theta=dims_plot,
        fill="toself", fillcolor="rgba(96,165,250,0.15)",
        line=dict(color="#60a5fa", width=2),
        name=ticker,
    ))
    fig.add_trace(go.Scatterpolar(
        r=[5] * len(dims_plot), theta=dims_plot,
        line=dict(color="#475569", width=1, dash="dot"),
        name="Mid (5)",
    ))
    fig.update_layout(
        polar=dict(
            bgcolor="#161b22",
            radialaxis=dict(range=[0, 10], tickfont=dict(color="#475569"), gridcolor="#30363d"),
            angularaxis=dict(tickfont=dict(color="#cbd5e1", size=10), gridcolor="#30363d"),
        ),
        paper_bgcolor="#0e1117",
        font_color="#cbd5e1",
        showlegend=False,
        height=300,
        margin=dict(l=50, r=50, t=20, b=20),
    )
    return fig


def score_bar(score: float, max_val: float = 100) -> str:
    pct = min(score / max_val * 100, 100)
    color = "#4ade80" if pct >= 70 else "#facc15" if pct >= 40 else "#f87171"
    return (
        f'<div style="background:#1e293b;border-radius:4px;height:8px;width:100%">'
        f'<div style="background:{color};width:{pct:.0f}%;height:8px;border-radius:4px"></div>'
        f'</div>'
    )


# ── Run analysis ─────────────────────────────────────────────────────────────
if run_btn or "analyst_results" not in st.session_state:
    if not tickers:
        st.warning("Enter at least one ticker.")
        st.stop()

    results = []
    prog = st.progress(0, text="Fetching fundamentals …")

    from analyst.data_fetcher import fetch
    from analyst.peer_benchmarker import benchmark
    from analyst.analyzer import analyze
    from analyst.blender import blend_scores, compute_quant_score

    for i, ticker in enumerate(tickers):
        prog.progress((i + 0.3) / len(tickers), text=f"Fetching {ticker} …")
        try:
            fund = fetch(ticker, force=force_refresh)
            quant = compute_quant_score(fund)
            prog.progress((i + 0.6) / len(tickers), text=f"Benchmarking {ticker} …")
            peer = benchmark(fund)
            prog.progress((i + 0.9) / len(tickers), text=f"Analyzing {ticker} with Claude …")
            claude_res = analyze(ticker, fund, peer, force=force_refresh)
            results.append({
                "ticker": ticker,
                "name": fund.get("name", ticker),
                "sector": fund.get("sector", "Unknown"),
                "quant_score": quant,
                "claude_result": claude_res,
                "fundamentals": fund,
                "peer": peer,
                "prev_rank": st.session_state.get(f"prev_rank_{ticker}"),
            })
        except Exception as exc:
            st.warning(f"Failed for {ticker}: {exc}")

    prog.empty()

    blended = blend_scores(results)
    for c in blended:
        st.session_state[f"prev_rank_{c['ticker']}"] = c["rank"]
    st.session_state["analyst_results"] = blended

ranked = st.session_state.get("analyst_results", [])
if not ranked:
    st.info("Click **Analyze** to run the analyst pipeline.")
    st.stop()

# ── Rankings table ────────────────────────────────────────────────────────────
st.subheader("Rankings (Blended Score = 60% Quant + 40% Claude)")

table_rows = []
for c in ranked:
    delta = c.get("rank_delta", 0)
    delta_str = f"▲{abs(delta)}" if delta > 0 else (f"▼{abs(delta)}" if delta < 0 else "—")
    table_rows.append({
        "Rank":     c["rank"],
        "Δ":        delta_str,
        "Ticker":   c["ticker"],
        "Name":     c.get("name", "")[:22],
        "Sector":   c.get("sector", "")[:18],
        "Blended":  c["blended_score"],
        "Quant":    c["quant_score"],
        "Claude":   round(c["claude_norm"], 1),
        "Consist.": c.get("consistency_rating", "N/A"),
    })

df_rank = pd.DataFrame(table_rows)


def color_blended(val):
    try:
        v = float(val)
        if v >= 70:
            return "color: #4ade80; font-weight:700"
        if v >= 50:
            return "color: #facc15"
        return "color: #f87171"
    except Exception:
        return ""


def color_delta(val):
    if "▲" in str(val):
        return "color: #4ade80; font-weight: 700"
    if "▼" in str(val):
        return "color: #f87171; font-weight: 700"
    return "color: #475569"


styled = (df_rank.style
          .applymap(color_blended, subset=["Blended"])
          .applymap(color_delta,   subset=["Δ"]))
st.dataframe(styled, use_container_width=True, hide_index=True)

# ── Detail view for selected ticker ──────────────────────────────────────────
st.divider()
st.subheader("Deep Dive")

ticker_choices = [c["ticker"] for c in ranked]
selected = st.selectbox("Select ticker for detail view", ticker_choices)

cand = next((c for c in ranked if c["ticker"] == selected), None)
if not cand:
    st.stop()

c1, c2 = st.columns([1, 2])

with c1:
    st.markdown(f"### {selected} — {cand.get('name','')[:30]}")
    st.markdown(f"**Sector:** {cand.get('sector','Unknown')}")
    st.markdown(f"**Blended Score:** `{cand['blended_score']}`")
    st.markdown(f"**Quant Score:** `{cand['quant_score']}`")
    st.markdown(f"**Claude Norm:** `{cand['claude_norm']}`")
    st.markdown(f"**Consistency:** `{cand.get('consistency_rating','—')}`")

    dim_scores = cand.get("dimension_scores", {})
    if dim_scores:
        st.markdown("**Dimension Scores (1–10)**")
        for dim, val in dim_scores.items():
            label = dim.replace("_", " ").title()
            bar_html = score_bar(val, 10)
            st.markdown(
                f'<div style="margin:4px 0"><span style="font-size:0.8rem;color:#94a3b8">{label}: {val}</span>'
                f'{bar_html}</div>',
                unsafe_allow_html=True,
            )

with c2:
    if dim_scores:
        st.plotly_chart(radar_for_ticker(dim_scores, selected), use_container_width=True)

st.divider()
col_bull, col_bear = st.columns(2)
with col_bull:
    st.markdown("**🟢 Bull Case**")
    st.info(cand.get("bull_case", "—"))
with col_bear:
    st.markdown("**🔴 Bear Case**")
    st.error(cand.get("bear_case", "—"))

risks = cand.get("key_risks", [])
if risks:
    st.markdown("**⚠️ Key Risks**")
    for r in risks:
        st.markdown(f"- {r}")

reasoning = cand.get("reasoning_summary")
if reasoning:
    with st.expander("Analyst Reasoning Summary"):
        st.markdown(reasoning)

# Peer benchmarks
peer = cand.get("peer", {})
rankings = peer.get("rankings", {})
if rankings:
    st.divider()
    st.subheader("Peer Benchmarks")
    peer_rows = []
    for metric, info in rankings.items():
        pct_rank = info.get("percentile_rank")
        peer_rows.append({
            "Metric":     metric.replace("_", " ").title(),
            "Value":      f"{info['value']*100:.1f}%" if info.get("value") else "N/A",
            "Peer Median": f"{info['peer_median']*100:.1f}%" if info.get("peer_median") else "N/A",
            "Pct Rank":   f"{pct_rank:.0f}th" if pct_rank is not None else "N/A",
        })
    st.dataframe(pd.DataFrame(peer_rows), use_container_width=True, hide_index=True)
