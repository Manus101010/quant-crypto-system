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
st.caption("Scan liquid pairs → rank setups (all types compete) → arm a diversified set of "
           "triggers → monitor alerts your phone. *Signal only; you execute.*")

from utils import telegram
tg_ok = telegram.is_configured()
st.markdown(
    f"**Telegram:** {'🟢 connected' if tg_ok else '🔴 not configured — set TELEGRAM_* in .env'}"
)

# ── BTC regime gate banner (advisory; direction-aware stamp on alerts) ──────────
try:
    from utils import btc_regime
    _reg = btc_regime.get_btc_regime()
    _colors = {"RISK-ON": "#16c784", "NEUTRAL": "#c9a227", "RISK-OFF": "#ea3943"}
    _c = _colors.get(_reg["label"], "#8a8f98")
    st.markdown(
        f"<div style='border:1px solid #262b38;border-left:5px solid {_c};"
        f"border-radius:10px;padding:10px 14px;margin:6px 0;background:#161a25'>"
        f"<span style='font-size:13px;color:#8a8f98'>BTC REGIME</span> &nbsp; "
        f"<span style='font-size:17px;font-weight:700;color:{_c}'>{_reg['label']}</span>"
        f"<span style='color:#a9adb8;font-size:13px'> &nbsp;— {_reg.get('detail','')}</span>"
        f"<div style='font-size:12px;color:#8a8f98;margin-top:4px'>"
        f"Longs: RISK-OFF is caution. Shorts: RISK-ON is caution. "
        f"Advisory only — alerts are stamped, not blocked.</div></div>",
        unsafe_allow_html=True,
    )
except Exception as _e:
    st.caption(f"BTC regime unavailable: {_e}")

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
    diversify = st.checkbox("Diversify setups", value=True,
                            help="Cap how many of any one setup can be armed so the "
                                 "watchlist is a spread across strategy types, not 10 "
                                 "of whatever setup is most common today.")
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
                               source="mexc" if is_mexc else "top_mcap",
                               max_per_setup=(max(2, top_n // 3) if diversify else None))
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


@st.cache_data(ttl=300, show_spinner=False)
def _candles_for(symbols: tuple[str, ...], bars: int = 45) -> dict:
    """Recent daily candles for the displayed symbols (cached 5m). Read-only ccxt."""
    if not symbols:
        return {}
    from utils import exchange
    out = {}
    data = exchange.get_ohlcv_batch(list(symbols), timeframe="1d", limit=bars + 5)
    for sym, df in data.items():
        d = df.tail(bars)
        out[sym] = [(float(o), float(h), float(l), float(c))
                    for o, h, l, c in zip(d["open"], d["high"], d["low"], d["close"])]
    return out


def _svg_chart(candles, entry, stop, target, is_long, w=300, h=120) -> str:
    """Inline candlestick chart with entry/stop/target mapped as horizontal lines."""
    if not candles or len(candles) < 3:
        return ""
    entry, stop, target = _price(entry), _price(stop), _price(target)
    highs = [c[1] for c in candles]
    lows  = [c[2] for c in candles]
    levels = [x for x in (entry, stop, target) if x]
    lo = min(min(lows), *levels) if levels else min(lows)
    hi = max(max(highs), *levels) if levels else max(highs)
    if hi <= lo:
        return ""
    pad = (hi - lo) * 0.06
    lo -= pad; hi += pad
    span = hi - lo

    def y(p): return h - (p - lo) / span * h
    n = len(candles)
    cw = w / n
    parts = []
    for i, (o, hh, ll, c) in enumerate(candles):
        x = i * cw + cw / 2
        col = "#16c784" if c >= o else "#ea3943"
        parts.append(f"<line x1='{x:.1f}' y1='{y(hh):.1f}' x2='{x:.1f}' y2='{y(ll):.1f}' "
                     f"stroke='{col}' stroke-width='1'/>")
        oy, cy = y(o), y(c)
        top, bh = min(oy, cy), max(abs(oy - cy), 1)
        parts.append(f"<rect x='{x - cw*0.3:.1f}' y='{top:.1f}' width='{cw*0.6:.1f}' "
                     f"height='{bh:.1f}' fill='{col}'/>")

    def hline(p, col, label):
        yy = y(p)
        return (f"<line x1='0' y1='{yy:.1f}' x2='{w}' y2='{yy:.1f}' stroke='{col}' "
                f"stroke-width='1' stroke-dasharray='4 3' opacity='0.9'/>"
                f"<rect x='0' y='{yy-8:.1f}' width='30' height='11' fill='{col}' opacity='0.85'/>"
                f"<text x='2' y='{yy:.1f}' fill='#0d1017' font-size='9' font-weight='700'>{label}</text>")
    over = ""
    if entry:  over += hline(entry, "#e6e6e6", "entry")
    if target: over += hline(target, _LONG, "tgt")
    if stop:   over += hline(stop, _SHORT, "stop")
    return (f"<svg viewBox='0 0 {w} {h}' width='100%' height='{h}' preserveAspectRatio='none' "
            f"style='display:block;margin:10px 0 2px;background:#0d1017;border-radius:6px'>"
            f"{''.join(parts)}{over}</svg>")


def _card(symbol, is_long, setup, meta_right, legs_html="", footer="", chart_svg="") -> str:
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
        f"border-radius:12px;padding:14px 16px;background:#161a25'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center'>"
        f"{sym_link}"
        f"<span style='background:{accent};color:#0d1017;font-weight:700;font-size:11px;"
        f"padding:3px 9px;border-radius:6px'>{dir_lbl}</span></div>"
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;margin-top:3px'>"
        f"<span style='color:#c9ccd3;font-size:13px'>{setup}</span>"
        f"<span style='color:{_MUTE};font-size:11px'>{meta_right}</span></div>"
        f"{chart_svg}{legs_html}{foot}</div>"
    )


def _grid(cards: list[str], minpx: int = 300) -> None:
    """Responsive grid: as many columns as fit the browser (min card width minpx)."""
    if not cards:
        return
    st.markdown(
        f"<div style='display:grid;gap:12px;"
        f"grid-template-columns:repeat(auto-fill,minmax({minpx}px,1fr))'>"
        + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


# ── Post-scan: full ranked candidate list (ephemeral) ──────────────────────────
if res and res.get("candidates"):
    n_found = res.get("actionable", len(res["candidates"]))
    with st.expander(f"🎯 Last scan — {n_found} valid setup{'s' if n_found != 1 else ''} "
                     f"(showing {len(res['candidates'])})", expanded=True):
        st.caption("Every setup that passed the edge gate today, best first — only a handful of "
                   "coins are ever in a valid, tradeable setup at once. The top ones are armed as "
                   "live triggers below.")
        cand_candles = _candles_for(tuple(r["ticker"] for r in res["candidates"]))
        cards = []
        for r in res["candidates"]:
            t = r.get("trade") or {}
            is_long = t.get("action") == "BUY"
            cards.append(_card(
                r["ticker"], is_long, r.get("setup_label", ""),
                f"{(r.get('setup_category') or '').replace('_',' ').title()} · score {r.get('_composite')}",
                _legs(t.get("entry"), t.get("target"), t.get("stop"), t.get("rr")),
                chart_svg=_svg_chart(cand_candles.get(r["ticker"]), t.get("entry"),
                                     t.get("stop"), t.get("target"), is_long),
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
    act_candles = _candles_for(tuple(t["symbol"] for t in active))
    cards = []
    for t in active:
        is_long = t["direction"] == "long"
        cards.append(_card(
            t["symbol"], is_long, t.get("setup_label", ""),
            f"👁 {_expires_in(t.get('expires_at'))}",
            _legs(t.get("entry"), t.get("target"), t.get("stop"), t.get("rr")),
            footer=f"<b style='color:#c9ccd3'>Fires when</b> {_cond_plain(t)}",
            chart_svg=_svg_chart(act_candles.get(t["symbol"]), t.get("entry"),
                                 t.get("stop"), t.get("target"), is_long),
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
    _grid(cards, minpx=260)

st.divider()
st.caption("Run the monitor on an always-on host: `python monitor.py --interval 120` "
           "(tmux/systemd). It evaluates these triggers and alerts Telegram — no trading.")
