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
    save_validation, load_validation, _MIN_EDGE_PF, _MIN_EDGE_N,
)
from backtesting.crypto_optimize import validate_per_setup
from triggers import db as tdb

_PROVISIONAL_MAX = 50   # 25 ≤ n < 50 = provisional (watched every revalidation)


def _band(n) -> str:
    n = n or 0
    if n < _MIN_EDGE_N:
        return "below floor"
    return "provisional" if n < _PROVISIONAL_MAX else "established"

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
    with st.spinner(f"Backtesting setups over {where}, {days}d, per-setup management … "
                    f"({'a few minutes' if is_mexc else '~30-60s'})"):
        # validate_per_setup simulates each setup under its own validated exits
        # (breakouts trail; mean-reversion/momentum take a fixed target) and saves
        # the per-setup management map the scanner arms from.
        res = validate_per_setup(universe_size=universe, days=days, cost_pct=cost,
                                 source="mexc" if is_mexc else "top_mcap")
        st.session_state["val_res"] = res
    st.success(f"Validated {res['meta']['total_trades']} trades across "
               f"{res['meta']['coins_with_data']} coins. Scanner will now only arm the "
               f"setups that passed.")

# ── Revalidation (decay check) — separate from the baseline above ──────────────
st.divider()
rc1, rc2 = st.columns([3, 1])
with rc1:
    st.markdown("**🔁 Revalidation (edge-decay watch)** — re-checks the *armed* setups "
                "and auto-deactivates any whose edge has decayed (PF < 1.0). Provisional "
                "setups (n 25–49) are disarmed on the first failing run, established ones "
                "(n ≥ 50) after two. Newly-passing setups are flagged for your review, "
                "never auto-armed. Runs weekly via `run_revalidate.sh`; this button runs "
                "it now, off the monitor path.")
with rc2:
    st.write("")
    reval = st.button("🔁 Revalidate now", use_container_width=True)

if reval:
    with st.spinner("Revalidating armed setups on the MEXC universe … (a few minutes)"):
        from revalidate import run_revalidation
        out = run_revalidation()
    nd, nr = len(out["deactivated"]), len(out["review"])
    if nd:
        st.error(f"Auto-deactivated {nd} setup(s): "
                 + ", ".join(f"{d['setup']} (PF {d['pf']:.2f}, n {d['n']})" for d in out["deactivated"]))
    if nr:
        st.warning(f"{nr} newly-passing setup(s) for review (not armed): "
                   + ", ".join(f"{r['setup']} (PF {r['pf']:.2f}, n {r['n']})" for r in out["review"]))
    if not nd and not nr:
        st.success(f"All {len(out['checked'])} armed setups still hold their edge. Nothing changed.")

# ── Auto-deactivated setups (manual reactivation) ─────────────────────────────
deacts = tdb.get_deactivations()
if deacts:
    st.markdown("**⛔ Auto-deactivated setups** (edge decayed — not arming new triggers):")
    for d in deacts:
        dc1, dc2 = st.columns([4, 1])
        with dc1:
            st.caption(f"**{d['setup_label']}** — {d.get('reason','')} "
                       f"(disabled {(d.get('deactivated_at') or '')[:10]})")
        with dc2:
            if st.button("Reactivate", key=f"react_{d['setup_label']}", use_container_width=True):
                tdb.reactivate_setup(d["setup_label"])
                st.toast(f"Reactivated {d['setup_label']} — will arm again if it's in the validated set.")
                st.rerun()

res = st.session_state.get("val_res") or load_validation()

if not res:
    st.info("No validation yet. Run one — until then the scanner arms all setups ungated.")
    st.stop()

stats = res["stats"]
validated = set(res.get("validated", []))
mgmt_map = res.get("management_by_setup", {})
deactivated = tdb.get_deactivated()

st.divider()
st.subheader("Per-Setup Edge (net of cost)")
rows = []
for label, s in sorted(stats.items(), key=lambda x: -(x[1].get("n") or 0)):
    pf = s.get("profit_factor")
    m = mgmt_map.get(label, {})
    mgmt_txt = ("trail (let run)" if m.get("trailing")
                else f"{m.get('target_r')}R target" if m else "—")
    if label in deactivated:
        status = "⛔ deactivated"
    elif label in validated:
        status = "✅ yes"
    else:
        status = "❌ no edge"
    band = _band(s.get("n")) if label in validated else "—"
    rows.append({
        "Setup": label,
        "Trades": s["n"],
        "Win %": round(s["win_rate"] * 100, 0),
        "Profit Factor": pf if pf is not None else "∞",
        "Expectancy (R)": s["expectancy_r"],
        "Band": band,
        "Exit (if tradeable)": mgmt_txt,
        "Tradeable": status,
    })
df = pd.DataFrame(rows)


def _mark(v):
    s = str(v)
    if "✅" in s: return "color:#4ade80"
    if "⛔" in s: return "color:#f59e0b"
    if "❌" in s: return "color:#f87171"
    return ""

st.dataframe(df.style.applymap(_mark, subset=["Tradeable"]),
             use_container_width=True, hide_index=True)

arming = sorted(validated - deactivated)
passed = ", ".join(arming) or "— none arming —"
st.markdown(f"**Arming triggers now:** {passed}"
            + (f"  ·  ⛔ deactivated: {', '.join(sorted(validated & deactivated))}"
               if (validated & deactivated) else ""))
st.caption(f"Backtest: {res['meta']['coins_with_data']} coins · "
           f"{res['meta']['total_trades']} trades · {res['meta']['params']}")
st.info("Setups marked ❌ are **excluded from the scanner** until they prove an edge. "
        "This is deliberate — trading a setup with negative expectancy loses money net of costs.")
