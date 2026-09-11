"""
Page 6: Crypto Scanner — the core of the refocused system.

On-demand scan of the liquid ccxt universe for mean-reversion (the edge) and
momentum setups, ranked by an MR-weighted composite. The top-N are armed as
triggers; the standalone monitor.py watches them and pushes Telegram alerts.
Signal only — you execute manually.
"""
import streamlit as st
import pandas as pd
from config import DARK_THEME_CSS

st.set_page_config(page_title="Scanner", layout="wide")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

st.title("🛰️ Crypto Scanner")
st.caption("Scan liquid pairs → rank setups (mean-reversion weighted) → arm triggers → "
           "monitor alerts your phone. *Signal only; you execute.*")

from utils import telegram
tg_ok = telegram.is_configured()
st.markdown(
    f"**Telegram:** {'🟢 connected' if tg_ok else '🔴 not configured — set TELEGRAM_* in .env'}"
)
st.divider()

# ── Controls ──────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns([1, 1, 1, 1.4])
with c1:
    universe = st.selectbox("Universe (top by mcap)", [50, 100, 200, 300, 500], index=1)
with c2:
    top_n = st.slider("Arm top N", 3, 25, 10)
with c3:
    expiry = st.selectbox("Trigger expiry (h)", [24, 48, 72, 168], index=1)
with c4:
    st.write("")
    run = st.button("🛰️ Run Scan & Arm Triggers", type="primary", use_container_width=True)

# Pull the latest macro deployment score to bias conviction by regime (if run).
regime_score = None
mr = st.session_state.get("macro_result")
if mr:
    regime_score = mr.get("deployment_score")

if run:
    with st.spinner(f"Scanning top {universe} coins via ccxt … (~20-40s)"):
        from triggers.scan import run_scan_and_arm
        res = run_scan_and_arm(universe_size=universe, top_n=top_n,
                               regime_score=regime_score, expiry_hours=expiry)
        st.session_state["scan_res"] = res
    n = len(res["armed"])
    st.success(f"Armed {n} triggers from {len(res['candidates'])} actionable setups. "
               f"The monitor will alert you when a condition is met.")

res = st.session_state.get("scan_res")

# ── Ranked candidates ─────────────────────────────────────────────────────────
if res and res["candidates"]:
    st.subheader("Ranked Setups")
    rows = []
    for r in res["candidates"]:
        t = r.get("trade") or {}
        rows.append({
            "Symbol": r["ticker"],
            "Setup": r.get("setup_label"),
            "Type": (r.get("setup_category") or "").replace("_", " "),
            "Composite": r.get("_composite"),
            "Action": t.get("action"),
            "Entry": t.get("entry"),
            "Target": t.get("target"),
            "Stop": t.get("stop"),
            "R:R": t.get("rr"),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ── Armed triggers ────────────────────────────────────────────────────────────
st.divider()
st.subheader("Active Triggers")
from triggers import db as tdb
active = tdb.get_triggers("active")
if active:
    at = pd.DataFrame([{
        "ID": t["id"], "Symbol": t["symbol"], "Setup": t["setup_label"],
        "Dir": t["direction"], "Condition": f"{t['condition_type']} @ {t['condition_value']}",
        "Composite": t["composite"], "Expires": (t.get("expires_at") or "")[:16],
    } for t in active])
    st.dataframe(at, use_container_width=True, hide_index=True)
    if st.button("Cancel all active triggers"):
        n = tdb.clear_active()
        st.warning(f"Cancelled {n} triggers.")
        st.rerun()
else:
    st.info("No active triggers. Run a scan to arm some.")

# ── Recently fired ────────────────────────────────────────────────────────────
fired = tdb.get_triggers("fired")[:15]
if fired:
    st.divider()
    st.subheader("Recently Fired")
    ft = pd.DataFrame([{
        "Symbol": t["symbol"], "Setup": t["setup_label"], "Dir": t["direction"],
        "Fired": (t.get("fired_at") or "")[:16], "At": t.get("fired_price"),
        "Reason": t.get("note"),
    } for t in fired])
    st.dataframe(ft, use_container_width=True, hide_index=True)

st.divider()
st.caption("Run the monitor on an always-on host: `python monitor.py --interval 120` "
           "(tmux/systemd). It evaluates these triggers and alerts Telegram — no trading.")
