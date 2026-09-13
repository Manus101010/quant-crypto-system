"""
Page 6: Crypto Scanner — the core of the refocused system.

On-demand scan of the liquid ccxt universe for mean-reversion (the edge) and
momentum setups, ranked by an MR-weighted composite. The top-N are armed as
triggers; the standalone monitor.py watches them and pushes Telegram alerts.
Signal only — you execute manually.
"""
import re
import streamlit as st
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
c1, c2, c3 = st.columns([1.4, 1, 1])
with c1:
    source_lbl = st.selectbox(
        "Universe",
        ["MEXC — all pairs", "Top by market cap"],
        index=0,
        help="MEXC scans every tradeable USDT spot pair on MEXC (thousands of "
             "coins). Slower — a few minutes — but the widest net.",
    )
    is_mexc = source_lbl.startswith("MEXC")
    universe = 100
    if not is_mexc:
        universe = st.selectbox("Top by mcap", [50, 100, 200, 300, 500], index=1)
with c2:
    top_n = st.slider("Arm top N", 3, 25, 10)
    min_vol_m = st.selectbox("Min 24h volume", [0.0, 0.5, 1.0, 5.0, 10.0], index=2,
                             format_func=lambda v: "off" if v == 0 else f"${v:g}M")
with c3:
    expiry = st.selectbox("Trigger expiry (h)", [24, 48, 72, 168], index=1)
    st.write("")
    run = st.button("🛰️ Run Scan & Arm", type="primary", use_container_width=True)

if is_mexc:
    st.caption("🌐 MEXC full-universe scan: thousands of pairs, candles pinned to MEXC. "
               "First run takes a few minutes; keep a volume floor on to stay tradeable.")

# Pull the latest macro deployment score to bias conviction by regime (if run).
regime_score = None
mr = st.session_state.get("macro_result")
if mr:
    regime_score = mr.get("deployment_score")

if run:
    spin = ("Scanning all MEXC pairs via ccxt … (this can take a few minutes)"
            if is_mexc else f"Scanning top {universe} coins via ccxt … (~20-40s)")
    with st.spinner(spin):
        from triggers.scan import run_scan_and_arm
        res = run_scan_and_arm(universe_size=universe, top_n=top_n,
                               regime_score=regime_score, expiry_hours=expiry,
                               min_vol_usd_m=min_vol_m,
                               source="mexc" if is_mexc else "top_mcap")
        st.session_state["scan_res"] = res
    if res.get("regime_blocked"):
        st.warning(f"⛔ Regime is risk-off (Deployment Score {res.get('regime_score'):.0f} < 45) — "
                   f"**nothing armed.** These setups only have edge in a risk-on regime. "
                   f"Showing candidates for reference; run the Macro Gate and wait for it to improve.")
    else:
        n = len(res["armed"])
        found = res.get("actionable", len(res["candidates"]))
        st.success(f"Found {found} valid setup{'s' if found != 1 else ''} in the universe "
                   f"today — armed the top {n} as triggers. "
                   f"The monitor will alert you when a condition is met.")
    if res.get("management"):
        st.info(f"📐 {res['management']}  (this is how the backtested edge was actually captured — "
                f"cut losers fast, let the few big winners run.)")
    if res.get("gated_out_setups"):
        st.caption("Excluded (no validated edge): " + ", ".join(res["gated_out_setups"]))

res = st.session_state.get("scan_res")

from triggers import db as tdb
import json as _json
import datetime as _dt

_LONG = "#16c784"
_SHORT = "#ea3943"
_MUTE = "#8a8f98"


# ── Formatting helpers ─────────────────────────────────────────────────────────
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
    if p is None or p == 0:
        return "—"
    if p < 0.01:    return f"${p:,.6f}"
    if p < 1:       return f"${p:,.4f}"
    if p < 100:     return f"${p:,.2f}"
    return f"${p:,.0f}"


def _tv_url(symbol: str) -> str:
    """TradingView chart link. 'ZEC-USD' → BASE 'ZEC' → USDT pair TV resolves to
    the most liquid listing. Opens the full chart in a new tab."""
    base = re.split(r"[-/]", str(symbol))[0].upper()
    return f"https://www.tradingview.com/chart/?symbol={base}USDT"


def _expires_in(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        exp = _dt.datetime.fromisoformat(iso)
        secs = (exp - _dt.datetime.utcnow()).total_seconds()
    except Exception:
        return ""
    if secs <= 0:
        return "expired"
    h = int(secs // 3600)
    return f"expires in {h}h" if h else f"expires in {int(secs // 60)}m"


def _cond_plain(t: dict) -> str:
    """Plain-English 'fires when' description of a trigger's condition."""
    try:
        c = _json.loads(t.get("condition_json") or "{}")
    except Exception:
        c = {}
    kind = c.get("kind")
    if kind == "mr_reversal":
        return (f"the bounce confirms — RSI(2) turns back up through "
                f"{c.get('rsi2_level',12):.0f} on a green bar while price is still below "
                f"the {_fmt(c.get('mean'))} mean")
    if kind == "breakout":
        return f"price closes above {_fmt(c.get('level'))} (invalidates below stop)"
    if kind == "breakdown":
        return f"price closes below {_fmt(c.get('level'))} (invalidates above stop)"
    return f"{t.get('condition_type')} @ {t.get('condition_value')}"


def _legs(entry, target, stop, rr) -> str:
    def leg(label, val, color="#e6e6e6"):
        return (f"<div style='flex:1;min-width:64px'>"
                f"<div style='font-size:10px;color:{_MUTE};text-transform:uppercase;"
                f"letter-spacing:.05em'>{label}</div>"
                f"<div style='font-size:15px;font-weight:600;color:{color}'>{val}</div></div>")
    # Trailing setups have no fixed target — say so instead of showing a bogus R:R.
    trailing = _price(target) is None
    tgt_txt = "trail" if trailing else _fmt(target)
    rr_txt = "—" if trailing else (str(rr) if rr else "—")
    return ("<div style='display:flex;gap:8px;margin-top:10px'>"
            + leg("Entry", _fmt(entry))
            + leg("Target", tgt_txt, _LONG)
            + leg("Stop", _fmt(stop), _SHORT)
            + leg("R:R", rr_txt)
            + "</div>")


def _card(symbol, is_long, setup, meta_right, legs_html="", footer="") -> str:
    accent = _LONG if is_long else _SHORT
    dir_lbl = "▲ LONG" if is_long else "▼ SHORT"
    foot = (f"<div style='margin-top:10px;padding-top:9px;"
            f"border-top:1px solid #262b38;font-size:12px;color:#a9adb8;line-height:1.45'>"
            f"{footer}</div>") if footer else ""
    sym_link = (f"<a href='{_tv_url(symbol)}' target='_blank' style='font-size:19px;"
                f"font-weight:700;color:#fff;text-decoration:none' "
                f"title='Open {symbol} on TradingView'>{symbol}"
                f"<span style='font-size:12px;color:{_MUTE};font-weight:500'> chart ↗</span></a>")
    return (
        f"<div style='border:1px solid #262b38;border-left:4px solid {accent};"
        f"border-radius:12px;padding:14px 16px;margin-bottom:12px;background:#161a25'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center'>"
        f"{sym_link}"
        f"<span style='background:{accent};color:#0d1017;font-weight:700;font-size:11px;"
        f"padding:3px 9px;border-radius:6px'>{dir_lbl}</span></div>"
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;margin-top:3px'>"
        f"<span style='color:#c9ccd3;font-size:13px'>{setup}</span>"
        f"<span style='color:{_MUTE};font-size:11px'>{meta_right}</span></div>"
        f"{legs_html}{foot}</div>"
    )


def _grid(cards: list[str], ncol: int = 2) -> None:
    cols = st.columns(ncol)
    for i, html in enumerate(cards):
        with cols[i % ncol]:
            st.markdown(html, unsafe_allow_html=True)


# ── Post-scan: full ranked candidate list (ephemeral) ──────────────────────────
if res and res.get("candidates"):
    n_found = res.get("actionable", len(res["candidates"]))
    with st.expander(f"🎯 Last scan — {n_found} valid setup{'s' if n_found != 1 else ''} "
                     f"(showing {len(res['candidates'])})", expanded=True):
        st.caption("Every setup that passed the edge gate today, best first — only a handful of "
                   "coins are ever in a valid, tradeable setup at once. The top ones are armed as "
                   "live triggers below.")
        cards = []
        for r in res["candidates"]:
            t = r.get("trade") or {}
            cards.append(_card(
                r["ticker"], t.get("action") == "BUY", r.get("setup_label", ""),
                f"{(r.get('setup_category') or '').replace('_',' ').title()} · score {r.get('_composite')}",
                _legs(t.get("entry"), t.get("target"), t.get("stop"), t.get("rr")),
            ))
        _grid(cards)

# ── Watching now (persisted — the hero section) ────────────────────────────────
st.divider()
active = tdb.get_triggers("active")
fired = tdb.get_triggers("fired")[:12]

hcol1, hcol2 = st.columns([3, 1])
with hcol1:
    st.subheader("📡 Watching now")
with hcol2:
    if active and st.button("Cancel all", use_container_width=True):
        n = tdb.clear_active()
        st.toast(f"Cancelled {n} triggers.")
        st.rerun()

if active:
    st.caption(f"{len(active)} live trigger{'s' if len(active) != 1 else ''} — the monitor "
               f"alerts your phone the moment one fires.")
    cards = []
    for t in active:
        is_long = t["direction"] == "long"
        cards.append(_card(
            t["symbol"], is_long, t.get("setup_label", ""),
            f"👁 {_expires_in(t.get('expires_at'))}",
            _legs(t.get("entry"), t.get("target"), t.get("stop"), t.get("rr")),
            footer=f"<b style='color:#c9ccd3'>Fires when</b> {_cond_plain(t)}",
        ))
    _grid(cards)
else:
    st.info("Nothing armed yet. Run a scan above to arm your best setups as live triggers.")

# ── Recently fired (compact cards) ─────────────────────────────────────────────
if fired:
    st.divider()
    st.subheader("✅ Recently fired")
    cards = []
    for t in fired:
        is_long = t["direction"] == "long"
        when = (t.get("fired_at") or "")[:16].replace("T", " ")
        cards.append(_card(
            t["symbol"], is_long, t.get("setup_label", ""),
            when,
            footer=f"Fired at <b style='color:#e6e6e6'>{_fmt(t.get('fired_price'))}</b> — "
                   f"{t.get('note') or 'condition met'}",
        ))
    _grid(cards, ncol=3)

st.divider()
st.caption("Run the monitor on an always-on host: `python monitor.py --interval 120` "
           "(tmux/systemd). It evaluates these triggers and alerts Telegram — no trading.")
