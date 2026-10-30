"""
Page 3: Today's movers. The top gainers and losers on MEXC perps, each put into one of
the states he looks for by hand (rolling over, still running, still dumping, turning up,
stretched, chop) with a 0 to 100 fit score and the backtest verdict for that state.
Same engine as /movers in Telegram (desk/movers.py). Signal only.
"""
import pandas as pd
import streamlit as st

from config import DARK_THEME_CSS
from desk import movers

st.set_page_config(page_title="Movers", layout="wide")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)
st.title("📊 Today's movers")
st.caption("Top gainers and losers by 24h change, read on the 1h chart. Score = how cleanly "
           "the coin fits the state, not a profit forecast. Same as /movers in Telegram.")

n = st.slider("Coins per side", 3, 15, movers.TOP_N)
if st.button("🔎 Scan movers now", type="primary") or "movers_board" in st.session_state:
    if st.session_state.get("movers_n") != n or "movers_board" not in st.session_state:
        with st.spinner("Reading the movers..."):
            st.session_state["movers_board"] = movers.board(n)
            st.session_state["movers_n"] = n
    b = st.session_state["movers_board"]
    st.caption(f"Scanned {b['t']} UTC")
    for side, head in (("gainer", "🟢 Top gainers"), ("loser", "🔴 Top losers")):
        rows = [r for r in b["rows"] if r["side"] == side]
        if not rows:
            continue
        st.subheader(head)
        df = pd.DataFrame([{
            "Coin": r["base"], "24h %": round(r["pct"], 1), "State": r["state"].title(),
            "Score": r["score"], "Why": r.get("why", ""),
            "Backtest": movers.VERDICT.get(r["state"], ("", ""))[1],
        } for r in rows])
        st.dataframe(df, hide_index=True, use_container_width=True)
    st.markdown("**Next step:** open a coin in the Trade Desk page (or `/bot COIN` in "
                "Telegram) for the grid plan, range, leverage and stop.")
else:
    st.info("Press **Scan movers now**. Needs internet access to MEXC.")
