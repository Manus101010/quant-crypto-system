"""
Page 6: Crypto Scanner — the core of the refocused system.

On-demand scan of the liquid ccxt universe for mean-reversion (the edge) and
momentum setups, ranked by an MR-weighted composite. The top-N are armed as
triggers; the standalone monitor.py watches them and pushes Telegram alerts.
Signal only — you execute manually.
"""
import re
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
    if res.get("regime_blocked"):
        st.warning(f"⛔ Regime is risk-off (Deployment Score {res.get('regime_score'):.0f} < 45) — "
                   f"**nothing armed.** These setups only have edge in a risk-on regime. "
                   f"Showing candidates for reference; run the Macro Gate and wait for it to improve.")
    else:
        n = len(res["armed"])
        st.success(f"Armed {n} triggers from {len(res['candidates'])} actionable setups. "
                   f"The monitor will alert you when a condition is met.")
    if res.get("management"):
        st.info(f"📐 {res['management']}  (this is how the backtested edge was actually captured — "
                f"cut losers fast, let the few big winners run.)")
    if res.get("gated_out_setups"):
        st.caption("Excluded (no validated edge): " + ", ".join(res["gated_out_setups"]))

res = st.session_state.get("scan_res")

# ── Ranked candidates (cards) ──────────────────────────────────────────────────
def _price(s):
    """Pull the first dollar/number out of a trade string (e.g. 'Buy near $0.33 …')."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"[-+]?\d[\d,]*\.?\d*", str(s).replace("$", ""))
    return float(m.group().replace(",", "")) if m else None


def _fmt(p) -> str:
    """Compact price formatting that stays readable across crypto's huge range."""
    p = _price(p)
    if p is None:
        return "—"
    if p == 0:      return "—"
    if p < 0.01:    return f"${p:,.6f}"
    if p < 1:       return f"${p:,.4f}"
    if p < 100:     return f"${p:,.2f}"
    return f"${p:,.0f}"


def _setup_card(r: dict) -> str:
    t = r.get("trade") or {}
    action = t.get("action")
    is_long = action == "BUY"
    accent = "#16c784" if is_long else "#ea3943"        # green long / red short
    dir_lbl = "▲ LONG" if is_long else "▼ SHORT"
    cat = (r.get("setup_category") or "").replace("_", " ").title()
    comp = r.get("_composite")
    rr = t.get("rr")
    rr_txt = f"{rr}" if rr else "—"

    def leg(label, val, color="#e6e6e6"):
        return (f"<div style='flex:1;min-width:70px'>"
                f"<div style='font-size:11px;color:#8a8f98;text-transform:uppercase;"
                f"letter-spacing:.04em'>{label}</div>"
                f"<div style='font-size:15px;font-weight:600;color:{color}'>{val}</div></div>")

    legs = "".join([
        leg("Entry", _fmt(t.get("entry"))),
        leg("Target", _fmt(t.get("target")), "#16c784"),
        leg("Stop", _fmt(t.get("stop")), "#ea3943"),
        leg("R:R", rr_txt),
    ])

    return (
        f"<div style='border:1px solid #2a2e39;border-left:4px solid {accent};"
        f"border-radius:10px;padding:14px 16px;margin-bottom:12px;background:#161a25'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:2px'>"
        f"<span style='font-size:20px;font-weight:700;color:#fff'>{r['ticker']}</span>"
        f"<span style='background:{accent};color:#0d1017;font-weight:700;font-size:12px;"
        f"padding:3px 10px;border-radius:6px'>{dir_lbl}</span></div>"
        f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px'>"
        f"<span style='color:#c9ccd3;font-size:13px'>{r.get('setup_label','')}</span>"
        f"<span style='color:#8a8f98;font-size:12px'>{cat} · score {comp}</span></div>"
        f"<div style='display:flex;gap:10px'>{legs}</div>"
        f"</div>"
    )


if res and res["candidates"]:
    st.subheader(f"Ranked Setups ({len(res['candidates'])})")
    st.caption("Best setup at top. Green = long, red = short. The top ones get armed as triggers below.")
    cols = st.columns(2)
    for i, r in enumerate(res["candidates"]):
        with cols[i % 2]:
            st.markdown(_setup_card(r), unsafe_allow_html=True)

# ── Armed triggers ────────────────────────────────────────────────────────────
st.divider()
st.subheader("Active Triggers")
from triggers import db as tdb
import json as _json


def _cond_desc(t: dict) -> str:
    """Human-readable multi-factor condition."""
    try:
        c = _json.loads(t.get("condition_json") or "{}")
    except Exception:
        c = {}
    kind = c.get("kind")
    if kind == "mr_reversal":
        return (f"RSI2 turns up ≥{c.get('rsi2_level',12):.0f} + green bar + "
                f"price < mean ({c.get('mean',0):.4g}) + above stop")
    if kind == "breakout":
        return f"Close breaks > {c.get('level',0):.4g} + RSI14 < {c.get('rsi_max',80)} (invalidate < stop)"
    if kind == "breakdown":
        return f"Close breaks < {c.get('level',0):.4g} + RSI14 > {c.get('rsi_min',20)} (invalidate > stop)"
    return f"{t['condition_type']} @ {t['condition_value']}"


active = tdb.get_triggers("active")
if active:
    at = pd.DataFrame([{
        "ID": t["id"], "Symbol": t["symbol"], "Setup": t["setup_label"],
        "Dir": t["direction"], "Condition (all must hold)": _cond_desc(t),
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
