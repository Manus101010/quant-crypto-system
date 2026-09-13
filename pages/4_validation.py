"""
Page 4: Setup Validation — the institutional-grade honesty check.

Walk-forward backtests the scanner's OWN setups over the liquid crypto universe
(net of realistic costs) to measure each setup's REAL edge. Only setups that
pass (profit factor > 1 with enough trades) are allowed to arm triggers.
Re-run periodically; the scanner reads the saved result to gate what it arms.
"""
import streamlit as st
import pandas as pd
from config import DARK_THEME_CSS
from backtesting.crypto_validation import (
    run_crypto_validation, save_validation, load_validation,
    _MIN_EDGE_PF, _MIN_EDGE_N,
)

st.set_page_config(page_title="Validation", layout="wide")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

st.title("🔬 Setup Validation")
st.caption("Walk-forward backtest of the scanner's setups on crypto, net of fees + slippage. "
           f"A setup is *tradeable* only if profit factor > {_MIN_EDGE_PF} over ≥ {_MIN_EDGE_N} trades.")

c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1.4])
with c1:
    src_lbl = st.selectbox("Universe", ["MEXC — all pairs", "Top by market cap"], index=0,
                           help="Validate on the same universe you scan. MEXC uses the real "
                                "MEXC spot population (capped for runtime); top-by-mcap uses "
                                "the largest coins only.")
    is_mexc = src_lbl.startswith("MEXC")
    universe = 40
    if not is_mexc:
        universe = st.selectbox("Top by mcap", [20, 40, 60, 100], index=1)
with c2:
    days = st.selectbox("History (days)", [400, 600, 800, 1000], index=1)
with c3:
    cost = st.number_input("Round-trip cost %", 0.0, 2.0, 0.36, 0.05)
with c4:
    st.write("")
    run = st.button("🔬 Run Validation", type="primary", use_container_width=True)

if run:
    where = "the MEXC universe" if is_mexc else f"top {universe} coins"
    with st.spinner(f"Backtesting setups over {where}, {days}d … "
                    f"({'a few minutes' if is_mexc else '~30-60s'})"):
        res = run_crypto_validation(universe_size=universe, days=days, cost_pct=cost,
                                    source="mexc" if is_mexc else "top_mcap")
        save_validation(res)            # persist → the scanner's edge gate reads this
        st.session_state["val_res"] = res
    st.success(f"Validated {res['meta']['total_trades']} trades across "
               f"{res['meta']['coins_with_data']} coins. Scanner will now only arm the "
               f"setups that passed.")

res = st.session_state.get("val_res") or load_validation()

if not res:
    st.info("No validation yet. Run one — until then the scanner arms all setups ungated.")
    st.stop()

stats = res["stats"]
validated = set(res.get("validated", []))

st.divider()
st.subheader("Per-Setup Edge (net of cost)")
rows = []
for label, s in sorted(stats.items(), key=lambda x: -(x[1].get("n") or 0)):
    pf = s.get("profit_factor")
    rows.append({
        "Setup": label,
        "Trades": s["n"],
        "Win %": round(s["win_rate"] * 100, 0),
        "Profit Factor": pf if pf is not None else "∞",
        "Expectancy (R)": s["expectancy_r"],
        "Avg Win %": s["avg_win"],
        "Avg Loss %": s["avg_loss"],
        "Tradeable": "✅ yes" if label in validated else "❌ no edge",
    })
df = pd.DataFrame(rows)


def _mark(v):
    return "color:#4ade80" if "✅" in str(v) else ("color:#f87171" if "❌" in str(v) else "")

st.dataframe(df.style.applymap(_mark, subset=["Tradeable"]),
             use_container_width=True, hide_index=True)

passed = ", ".join(sorted(validated)) or "— none passed —"
st.markdown(f"**Tradeable setups (arm triggers):** {passed}")
st.caption(f"Backtest: {res['meta']['coins_with_data']} coins · "
           f"{res['meta']['total_trades']} trades · {res['meta']['params']}")
st.info("Setups marked ❌ are **excluded from the scanner** until they prove an edge. "
        "This is deliberate — trading a setup with negative expectancy loses money net of costs.")
