"""
Page 1: Macro Gate Dashboard
Shows 7 signal scores, blended deployment score, and regime classification.
"""
import time
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from config import DARK_THEME_CSS, SIGNAL_WEIGHTS

st.set_page_config(page_title="Macro Gate", layout="wide")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

# ── helpers ───────────────────────────────────────────────────────────────────
def score_color_hex(score: float) -> str:
    if score >= 70:
        return "#4ade80"
    if score >= 40:
        return "#facc15"
    return "#f87171"


def regime_badge(regime: str) -> str:
    colors = {
        "Aggressive Deploy": ("#4ade80", "#0f2e1a"),
        "Moderate Deploy":   ("#facc15", "#2e2900"),
        "Cautious Deploy":   ("#fb923c", "#2e1500"),
        "Avoid / Reduce":    ("#f87171", "#2e0f0f"),
    }
    fg, bg = colors.get(regime, ("#94a3b8", "#1a1a2e"))
    return (
        f'<div style="display:inline-block;background:{bg};border:1.5px solid {fg};'
        f'border-radius:8px;padding:10px 24px;font-size:1.3rem;font-weight:700;color:{fg}">'
        f'{regime}</div>'
    )


def gauge_chart(score: float, title: str) -> go.Figure:
    color = score_color_hex(score)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        title={"text": title, "font": {"color": "#cbd5e1", "size": 13}},
        number={"font": {"color": color, "size": 28}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#475569", "tickfont": {"color": "#475569"}},
            "bar": {"color": color, "thickness": 0.3},
            "bgcolor": "#1e293b",
            "bordercolor": "#334155",
            "steps": [
                {"range": [0, 40],   "color": "#3b1111"},
                {"range": [40, 70],  "color": "#3b2e11"},
                {"range": [70, 100], "color": "#0f3b1a"},
            ],
            "threshold": {
                "line": {"color": "#94a3b8", "width": 2},
                "thickness": 0.75,
                "value": 60,
            },
        },
    ))
    fig.update_layout(
        height=200, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return fig


def radar_chart(signal_results: dict) -> go.Figure:
    labels = [v["name"] for v in signal_results.values()]
    values = [v["score"] for v in signal_results.values()]
    labels.append(labels[0])
    values.append(values[0])

    fig = go.Figure(go.Scatterpolar(
        r=values,
        theta=labels,
        fill="toself",
        fillcolor="rgba(74,222,128,0.15)",
        line=dict(color="#4ade80", width=2),
        name="Signal Scores",
    ))
    fig.add_trace(go.Scatterpolar(
        r=[60] * len(labels),
        theta=labels,
        line=dict(color="#475569", width=1, dash="dot"),
        name="Threshold (60)",
    ))
    fig.update_layout(
        polar=dict(
            bgcolor="#161b22",
            radialaxis=dict(range=[0, 100], tickfont=dict(color="#475569"), gridcolor="#30363d"),
            angularaxis=dict(tickfont=dict(color="#cbd5e1"), gridcolor="#30363d"),
        ),
        paper_bgcolor="#0e1117",
        font_color="#cbd5e1",
        legend=dict(bgcolor="#161b22", bordercolor="#30363d"),
        height=380,
        margin=dict(l=60, r=60, t=40, b=40),
    )
    return fig


def history_chart(raw: list, label: str, color: str = "#4ade80") -> go.Figure:
    if not raw:
        return go.Figure()
    fig = go.Figure(go.Scatter(
        y=raw, mode="lines",
        line=dict(color=color, width=1.5),
        name=label,
    ))
    fig.update_layout(
        height=120,
        paper_bgcolor="#0e1117", plot_bgcolor="#161b22",
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False),
        yaxis=dict(tickfont=dict(color="#475569", size=9), gridcolor="#30363d"),
        showlegend=False,
    )
    return fig


# ── Page ──────────────────────────────────────────────────────────────────────
st.title("🌐 Macro Deployment Gate")
st.caption("8-signal crypto macro regime scanner · Answers: *Should I deploy capital into crypto right now?*")
st.divider()

run_col, info_col = st.columns([1, 3])
with run_col:
    run_btn = st.button("⚡ Refresh Signals", type="primary", use_container_width=True)
with info_col:
    st.caption("Pulls live market data · ~5-10 second refresh · Signals run in parallel")

if run_btn or "macro_result" not in st.session_state:
    with st.spinner("Fetching macro signals …"):
        from signals.aggregator import run_all
        st.session_state["macro_result"] = run_all(parallel=True)
        st.session_state["macro_ts"] = time.strftime("%H:%M:%S")

result = st.session_state.get("macro_result", {})
ts = st.session_state.get("macro_ts", "—")

if not result:
    st.warning("No data yet. Click **Refresh Signals**.")
    st.stop()

deploy_score = result["deployment_score"]
regime       = result["regime"]
signals      = result["signals"]
elapsed      = result.get("elapsed_s", 0)

# ── Top metrics row ───────────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center;padding:20px 0 10px 0;">
    <div style="font-size:0.9rem;color:#94a3b8;margin-bottom:6px;">DEPLOYMENT SCORE</div>
    <div style="font-size:4rem;font-weight:800;color:{score_color_hex(deploy_score)};line-height:1">
        {deploy_score:.1f}
    </div>
    <div style="margin-top:12px">{regime_badge(regime)}</div>
    <div style="font-size:0.75rem;color:#475569;margin-top:10px">
        Updated {ts} · {elapsed}s fetch
    </div>
</div>
""", unsafe_allow_html=True)

st.divider()

# ── Radar chart + signal gauges ───────────────────────────────────────────────
c_radar, c_gauges = st.columns([1, 2])

with c_radar:
    st.plotly_chart(radar_chart(signals), use_container_width=True)

with c_gauges:
    g_cols = st.columns(3)
    for i, (key, sig) in enumerate(signals.items()):
        with g_cols[i % 3]:
            st.plotly_chart(
                gauge_chart(sig["score"], sig["name"]),
                use_container_width=True,
            )

st.divider()

# ── Signal detail table ───────────────────────────────────────────────────────
st.subheader("Signal Details")

rows = []
for key, sig in signals.items():
    score = sig["score"]
    val = sig.get("value")
    val_str = f"{val:.3f} {sig.get('unit','')}" if val is not None else "—"
    rows.append({
        "Signal":  sig["name"],
        "Score":   round(score, 1),
        "Value":   val_str,
        "Weight":  f"{SIGNAL_WEIGHTS[key]*100:.0f}%",
        "Detail":  sig.get("detail", ""),
    })

df = pd.DataFrame(rows)


def color_score(val):
    try:
        v = float(val)
        if v >= 70:
            return "color: #4ade80"
        if v >= 40:
            return "color: #facc15"
        return "color: #f87171"
    except Exception:
        return ""

styled = df.style.applymap(color_score, subset=["Score"])
st.dataframe(styled, use_container_width=True, hide_index=True)

# ── Signal history sparklines ─────────────────────────────────────────────────
st.divider()
st.subheader("Signal History (1 Year)")
colors = ["#4ade80","#facc15","#60a5fa","#fb923c","#c084fc","#34d399","#f472b6"]
sp_cols = st.columns(len(signals))
for i, (key, sig) in enumerate(signals.items()):
    with sp_cols[i]:
        st.caption(sig["name"])
        raw = sig.get("raw", [])
        if raw:
            st.plotly_chart(
                history_chart(raw, sig["name"], colors[i % len(colors)]),
                use_container_width=True,
            )
        else:
            st.markdown('<div style="color:#475569;font-size:0.75rem">No history</div>',
                        unsafe_allow_html=True)

# ── What-if slider ────────────────────────────────────────────────────────────
st.divider()
st.subheader("What-If: Adjust Signal Scores")
st.caption("Slide to explore how changes in individual signals affect the deployment score.")
manual_scores = {}
adj_cols = st.columns(len(signals))
for i, (key, sig) in enumerate(signals.items()):
    with adj_cols[i]:
        manual_scores[key] = st.slider(
            sig["name"][:12], 0, 100,
            int(sig["score"]), step=5, key=f"whatif_{key}",
        )

total_w = sum(SIGNAL_WEIGHTS.values())
what_if_score = sum(manual_scores[k] * SIGNAL_WEIGHTS[k] / total_w for k in manual_scores)
what_if_score = round(what_if_score, 1)
color = score_color_hex(what_if_score)
st.markdown(
    f'<div style="text-align:center;font-size:1.6rem;font-weight:700;color:{color}">'
    f'What-If Deployment Score: {what_if_score}</div>',
    unsafe_allow_html=True,
)
