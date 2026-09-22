"""
Page 5: Manual Trade Desk — a deep read on ONE coin you already have in mind,
before you place a manual trade. Distinct from the scanner (a wide net). On
demand only; NOT wired to the scanner or the monitor. Signal-only: it never
places or integrates an order — the grid parameters are a starting suggestion
you set on MEXC yourself.
"""
import streamlit as st
from config import DARK_THEME_CSS
from utils.exchange import get_ohlcv, to_ccxt_symbol, get_funding_rate
from utils import btc_regime
from desk import analysis as A

st.set_page_config(page_title="Trade Desk", layout="wide")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

_LONG, _SHORT, _MUTE, _BG = "#16c784", "#ea3943", "#8a8f98", "#0d1017"
_TF_BARS = {"1w": 80, "1d": 90, "4h": 120, "1h": 120}
_TF_LIMIT = {"1w": 260, "1d": 400, "4h": 500, "1h": 500}


def _fmt(v) -> str:
    if v is None:
        return "—"
    v = float(v)
    if v == 0:    return "—"
    if v < 0.01:  return f"${v:,.6f}"
    if v < 1:     return f"${v:,.4f}"
    if v < 100:   return f"${v:,.2f}"
    return f"${v:,.0f}"


@st.cache_data(ttl=180, show_spinner=False)
def _load(symbol: str, tf: str, limit: int):
    df = get_ohlcv(symbol, tf, limit)
    return df if (df is not None and not df.empty) else None


# ── SVG chart (matches the tile style) ────────────────────────────────────────
def _poly(vals, x_of, y_of, color, width=1.4, dash=""):
    pts, seg = [], []
    for i, v in enumerate(vals):
        if v is None:
            if len(seg) > 1:
                pts.append(seg)
            seg = []
        else:
            seg.append(f"{x_of(i):.1f},{y_of(v):.1f}")
    if len(seg) > 1:
        pts.append(seg)
    d = f"stroke-dasharray='{dash}'" if dash else ""
    return "".join(f"<polyline points='{' '.join(s)}' fill='none' stroke='{color}' "
                   f"stroke-width='{width}' {d}/>" for s in pts)


def _price_svg(cs: dict, levels: dict, w=720, h=300) -> str:
    candles = cs["candles"]
    if len(candles) < 3:
        return ""
    n = len(candles)
    highs = [c[1] for c in candles]; lows = [c[2] for c in candles]
    extra = [x for x in (cs["bb_up"] + cs["bb_lo"]) if x is not None]
    lv = [v for v in levels.values() if v]
    lo = min(min(lows), *(extra or [min(lows)]), *(lv or [min(lows)]))
    hi = max(max(highs), *(extra or [max(highs)]), *(lv or [max(highs)]))
    pad = (hi - lo) * 0.05 or hi * 0.02
    lo -= pad; hi += pad
    price_h = h * 0.78                       # top 78% price, bottom for volume
    vol_h = h - price_h
    span = hi - lo
    cw = w / n

    def x_of(i): return i * cw + cw / 2
    def y_of(p): return (hi - p) / span * price_h

    # volume bars (own scale, bottom strip)
    vmax = max((c[4] for c in candles), default=0) or 1
    vol = "".join(
        f"<rect x='{i*cw+cw*0.15:.1f}' y='{h - (c[4]/vmax*vol_h):.1f}' "
        f"width='{cw*0.7:.1f}' height='{c[4]/vmax*vol_h:.1f}' "
        f"fill='{_LONG if c[3] >= c[0] else _SHORT}' opacity='0.35'/>"
        for i, c in enumerate(candles))

    # candles
    body = []
    for i, (o, hh, ll, c, _v) in enumerate(candles):
        x = x_of(i); col = _LONG if c >= o else _SHORT
        body.append(f"<line x1='{x:.1f}' y1='{y_of(hh):.1f}' x2='{x:.1f}' "
                    f"y2='{y_of(ll):.1f}' stroke='{col}' stroke-width='1'/>")
        oy, cyy = y_of(o), y_of(c); top = min(oy, cyy); bh = max(abs(oy - cyy), 1)
        body.append(f"<rect x='{x-cw*0.3:.1f}' y='{top:.1f}' width='{cw*0.6:.1f}' "
                    f"height='{bh:.1f}' fill='{col}'/>")

    overlays = (
        _poly(cs["bb_up"], x_of, y_of, "#3d4657", 1, "3 3")
        + _poly(cs["bb_lo"], x_of, y_of, "#3d4657", 1, "3 3")
        + _poly(cs["sma20"], x_of, y_of, "#f5c518", 1.3)
        + _poly(cs["sma50"], x_of, y_of, "#4a9eff", 1.3)
        + _poly(cs["sma200"], x_of, y_of, "#c56cf0", 1.3)
    )

    def hline(p, col, label):
        y = y_of(p)
        return (f"<line x1='0' y1='{y:.1f}' x2='{w}' y2='{y:.1f}' stroke='{col}' "
                f"stroke-width='1' stroke-dasharray='5 3' opacity='0.85'/>"
                f"<rect x='0' y='{y-8:.1f}' width='42' height='11' fill='{col}' opacity='0.9'/>"
                f"<text x='2' y='{y:.1f}' fill='#0d1017' font-size='9' font-weight='700'>{label}</text>")
    lv_svg = ""
    if levels.get("range_hi"): lv_svg += hline(levels["range_hi"], "#8a8f98", "hi20")
    if levels.get("range_lo"): lv_svg += hline(levels["range_lo"], "#8a8f98", "lo20")
    return (f"<svg viewBox='0 0 {w} {h}' width='100%' height='{h}' preserveAspectRatio='none' "
            f"style='display:block;background:{_BG};border-radius:8px'>"
            f"{vol}{overlays}{''.join(body)}{lv_svg}</svg>")


def _rsi_svg(vals, w=720, h=90) -> str:
    v = [x for x in vals if x is not None]
    if len(v) < 3:
        return ""
    n = len(vals); cw = w / n
    def x_of(i): return i * cw + cw / 2
    def y_of(p): return (100 - p) / 100 * h
    guides = "".join(
        f"<line x1='0' y1='{y_of(g):.1f}' x2='{w}' y2='{y_of(g):.1f}' stroke='#2a2e39' "
        f"stroke-width='1' stroke-dasharray='3 3'/>"
        f"<text x='3' y='{y_of(g)-2:.1f}' fill='#5a5f6a' font-size='8'>{g}</text>"
        for g in (30, 50, 70))
    return (f"<svg viewBox='0 0 {w} {h}' width='100%' height='{h}' preserveAspectRatio='none' "
            f"style='display:block;background:{_BG};border-radius:8px;margin-top:6px'>"
            f"{guides}{_poly(vals, x_of, y_of, '#4a9eff', 1.4)}</svg>")


def _macd_svg(cs, w=720, h=90) -> str:
    macd, sig, hist = cs["macd"], cs["macd_signal"], cs["macd_hist"]
    allv = [x for x in macd + sig + hist if x is not None]
    if len(allv) < 3:
        return ""
    lo, hi = min(allv), max(allv)
    if hi == lo: hi = lo + 1
    n = len(macd); cw = w / n
    def x_of(i): return i * cw + cw / 2
    def y_of(p): return (hi - p) / (hi - lo) * h
    zero = y_of(0)
    bars = "".join(
        f"<rect x='{i*cw+cw*0.2:.1f}' y='{min(zero, y_of(v)):.1f}' width='{cw*0.6:.1f}' "
        f"height='{abs(y_of(v)-zero):.1f}' fill='{_LONG if v >= 0 else _SHORT}' opacity='0.5'/>"
        for i, v in enumerate(hist) if v is not None)
    zl = f"<line x1='0' y1='{zero:.1f}' x2='{w}' y2='{zero:.1f}' stroke='#3d4657' stroke-width='1'/>"
    return (f"<svg viewBox='0 0 {w} {h}' width='100%' height='{h}' preserveAspectRatio='none' "
            f"style='display:block;background:{_BG};border-radius:8px;margin-top:6px'>"
            f"{bars}{zl}{_poly(macd, x_of, y_of, '#4a9eff', 1.3)}"
            f"{_poly(sig, x_of, y_of, '#f5c518', 1.3)}</svg>")


# ── Page ──────────────────────────────────────────────────────────────────────
st.title("🎯 Manual Trade Desk")
st.caption("Deep read on ONE coin before a manual trade. Raw ccxt OHLC, all indicators "
           "computed in code. *Signal-only — grid params are a starting suggestion you set "
           "on MEXC yourself; nothing here places or controls an order.*")

c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    raw = st.text_input("Coin symbol (MEXC)", value="", placeholder="e.g. SOL, WIF, PEPE").strip()
with c2:
    st.write("")
    go = st.button("🔎 Read", type="primary", use_container_width=True)
with c3:
    st.write("")
    watch = st.button("⭐ Watch", use_container_width=True,
                      help="Add this coin to the Morning Brief watchlist")

if not raw:
    st.info("Enter a coin symbol to run the desk read.")
    st.stop()

symbol = raw.upper()
if "/" not in symbol and not symbol.endswith("-USD"):
    symbol = f"{symbol}-USD"

from triggers import db as tdb
if watch:
    tdb.add_watch(symbol)
    st.toast(f"⭐ {symbol} added to the Morning Brief watchlist.")

# Watchlist manager (drives morning_brief.py).
_wl = [w["symbol"] for w in tdb.get_watchlist()]
with st.expander(f"⭐ Watchlist ({len(_wl)}) — drives the daily Morning Brief", expanded=False):
    if _wl:
        for sym_w in _wl:
            wc1, wc2 = st.columns([4, 1])
            wc1.caption(sym_w)
            if wc2.button("Remove", key=f"rm_{sym_w}", use_container_width=True):
                tdb.remove_watch(sym_w)
                st.rerun()
    else:
        st.caption("Empty. Use ⭐ Watch above to add the coin you're reading.")
    st.caption("The brief (`morning_brief.py`, daily via `run_morning_brief.sh`) reads these each "
               "morning: price, 24h, and a flag when one is within 3% of its 20-day high/low.")

daily = _load(symbol, "1d", _TF_LIMIT["1d"])
if daily is None:
    st.error(f"No OHLC for **{symbol}** on any venue — check the ticker (it must trade on MEXC/ccxt).")
    st.stop()

# Multi-timeframe indicator reads + structure.
tf_reads, frames = {}, {}
for tf in A.TIMEFRAMES:
    df = _load(symbol, tf, _TF_LIMIT[tf])
    frames[tf] = df
    tf_reads[tf] = A.compute_tf(df) if df is not None else None

struct = A.structure(daily)
price = struct["price"]

# 24h change from 1h candles (fallback to daily).
h1 = frames.get("1h")
chg_24h = None
if h1 is not None and len(h1) >= 25:
    chg_24h = (price / float(h1["close"].iloc[-25]) - 1) * 100
elif len(daily) >= 2:
    chg_24h = (price / float(daily["close"].iloc[-2]) - 1) * 100

funding = get_funding_rate(symbol)
btc = btc_regime.get_btc_regime()

# ── Header strip ──────────────────────────────────────────────────────────────
chg_col = _LONG if (chg_24h or 0) >= 0 else _SHORT
fr_txt = (f"{funding['rate']*100:+.3f}%/8h" if funding and funding.get("rate") is not None else "n/a")
rng_pos = ("—" if not struct["range_hi20"] or not struct["range_lo20"] else
           f"{(price - struct['range_lo20'])/(struct['range_hi20']-struct['range_lo20'])*100:.0f}%"
           if struct["range_hi20"] > struct["range_lo20"] else "—")
st.markdown(
    f"<div style='display:flex;gap:24px;flex-wrap:wrap;align-items:baseline;"
    f"border:1px solid #262b38;border-radius:10px;padding:12px 16px;background:#161a25'>"
    f"<span style='font-size:22px;font-weight:800;color:#fff'>{symbol}</span>"
    f"<span style='font-size:18px;color:#e6e6e6'>{_fmt(price)}</span>"
    f"<span style='color:{chg_col};font-weight:700'>{(chg_24h or 0):+.1f}% 24h</span>"
    f"<span style='color:{_MUTE}'>funding <b style='color:#e6e6e6'>{fr_txt}</b></span>"
    f"<span style='color:{_MUTE}'>in 20-day range <b style='color:#e6e6e6'>{rng_pos}</b></span>"
    f"</div>", unsafe_allow_html=True)

# ── BTC regime banner (direction-aware) ──────────────────────────────────────
_bc = {"RISK-ON": _LONG, "NEUTRAL": "#c9a227", "RISK-OFF": _SHORT}.get(btc["label"], _MUTE)
st.markdown(
    f"<div style='border-left:5px solid {_bc};border:1px solid #262b38;border-radius:10px;"
    f"padding:8px 14px;margin:8px 0;background:#161a25'>"
    f"<b style='color:{_bc}'>BTC {btc['label']}</b>"
    f"<span style='color:#a9adb8;font-size:13px'> — {btc.get('detail','')}</span></div>",
    unsafe_allow_html=True)

# ── The Call ──────────────────────────────────────────────────────────────────
call = A.build_call(tf_reads, struct, funding, btc, chg_24h)
_dir = call["direction"]
_dc = {"long": _LONG, "short": _SHORT, "neutral": "#c9a227"}[_dir]
_dlabel = {"long": "▲ LONG", "short": "▼ SHORT", "neutral": "● NEUTRAL"}[_dir]
reasons_html = "".join(f"<li style='margin:2px 0'>{r}</li>" for r in call["reasons"])
st.markdown(
    f"<div style='border:1px solid #262b38;border-left:5px solid {_dc};border-radius:12px;"
    f"padding:14px 18px;margin:10px 0;background:#161a25'>"
    f"<div style='display:flex;justify-content:space-between;align-items:center'>"
    f"<span style='font-size:20px;font-weight:800;color:{_dc}'>{_dlabel}</span>"
    f"<span style='color:{_MUTE};font-size:13px'>{call['confidence']}</span></div>"
    f"<div style='color:#8a8f98;font-size:12px;margin-top:6px'>Why this call:</div>"
    f"<ul style='color:#c9ccd3;font-size:13px;margin:4px 0 0 0;padding-left:18px'>{reasons_html}</ul>"
    f"</div>", unsafe_allow_html=True)

# ── Chart (TF selector) ───────────────────────────────────────────────────────
st.subheader("Chart & indicators")
tf = st.radio("Timeframe", A.TIMEFRAMES, index=1, horizontal=True)
cframe = frames.get(tf)
if cframe is not None and len(cframe) >= 20:
    cs = A.chart_series(cframe, _TF_BARS[tf])
    levels = {"range_hi": struct["range_hi20"], "range_lo": struct["range_lo20"]} if tf == "1d" else {}
    st.markdown(_price_svg(cs, levels), unsafe_allow_html=True)
    st.caption("Candles · Bollinger(20,2) dashed · SMA20 🟡 · SMA50 🔵 · SMA200 🟣 · volume · "
               "20-day range levels (1d). Below: RSI(14) and MACD(12,26,9).")
    st.markdown(_rsi_svg(cs["rsi"]), unsafe_allow_html=True)
    st.markdown(_macd_svg(cs), unsafe_allow_html=True)
else:
    st.caption(f"Not enough {tf} history to chart.")

# ── Multi-timeframe alignment table ──────────────────────────────────────────
st.subheader("Multi-timeframe alignment")
import pandas as pd
rows = []
for tfk in A.TIMEFRAMES:
    r = tf_reads.get(tfk)
    if not r:
        rows.append({"TF": tfk, "Trend": "—", "RSI": "—", "MACD": "—", "BB %": "—", "ATR": "—"})
        continue
    rows.append({
        "TF": tfk,
        "Trend": {"up": "▲ up", "down": "▼ down", "mixed": "· mixed"}[r["trend"]],
        "RSI": round(r["rsi"], 0) if r.get("rsi") is not None else "—",
        "MACD": r["macd_state"],
        "BB %": round(r["bb_pct"], 2) if r.get("bb_pct") is not None else "—",
        "ATR": _fmt(r["atr"]) if r.get("atr") else "—",
    })
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ── Grid bot parameters ───────────────────────────────────────────────────────
st.subheader("Grid bot parameters — starting suggestion")
atr_d = (tf_reads.get("1d") or {}).get("atr")
grid = A.grid_params(_dir, price, atr_d, struct.get("realized_vol_d"), struct, chg_24h)
if not grid.get("ok"):
    st.warning(grid.get("note", "Grid parameters unavailable."))
else:
    gd = {"long": "Long grid", "short": "Short grid", "neutral": "Neutral grid"}[_dir]
    lev = grid["leverage"]
    lev_txt = (f"<b style='color:#e6e6e6'>{lev}×</b>" if lev else
               "<b style='color:#ea3943'>none</b>")
    caps = (" · capped: " + ", ".join(grid["leverage_caps"])) if grid["leverage_caps"] else ""
    st.markdown(
        f"<div style='border:1px solid #262b38;border-radius:12px;padding:14px 18px;background:#161a25'>"
        f"<div style='display:flex;gap:26px;flex-wrap:wrap'>"
        f"<div><div style='font-size:11px;color:{_MUTE};text-transform:uppercase'>Direction</div>"
        f"<div style='font-size:16px;font-weight:700;color:{_dc}'>{gd}</div></div>"
        f"<div><div style='font-size:11px;color:{_MUTE};text-transform:uppercase'>Range low</div>"
        f"<div style='font-size:16px;font-weight:700;color:{_SHORT}'>{_fmt(grid['range_low'])}</div></div>"
        f"<div><div style='font-size:11px;color:{_MUTE};text-transform:uppercase'>Range high</div>"
        f"<div style='font-size:16px;font-weight:700;color:{_LONG}'>{_fmt(grid['range_high'])}</div></div>"
        f"<div><div style='font-size:11px;color:{_MUTE};text-transform:uppercase'>Grids</div>"
        f"<div style='font-size:16px;font-weight:700;color:#e6e6e6'>{grid['grid_count']}</div></div>"
        f"<div><div style='font-size:11px;color:{_MUTE};text-transform:uppercase'>Leverage</div>"
        f"<div style='font-size:16px;font-weight:700'>{lev_txt}</div></div>"
        f"</div></div>", unsafe_allow_html=True)

    st.caption(
        f"**Range** — {grid['basis']} → width {grid['width_pct']:.1f}% of price.  \n"
        f"**Grids** — {grid['grid_count']} rungs at ~{grid['step_pct']:.2f}% each "
        f"(≈0.5×ATR, so each rung is a real swing, not noise).  \n"
        f"**Leverage** — a break out of the range against you ≈ {grid['adverse_pct']:.1f}% "
        f"(half-range + 1×ATR); that hits liquidation at ~{grid['lev_liq']:.1f}×, so travelling "
        f"only ⅓ of the way suggests **{(str(lev)+'×') if lev else 'no leverage'}**{caps}.")
    if grid.get("too_volatile"):
        st.warning("📛 " + grid["note"])
    st.caption("⚠️ Signal only — set this on MEXC yourself. Not wired to place anything.")

# ── Fundamentals (light Claude + live web search) ────────────────────────────
st.subheader("Fundamentals — fast read")
if st.button("🧠 Run FA read (Claude + web search)"):
    with st.spinner("Reading project, tokenomics, and searching recent catalysts …"):
        from desk.fundamentals import fa_read
        st.session_state[f"fa_{symbol}"] = fa_read(symbol)

fa = st.session_state.get(f"fa_{symbol}")
if fa:
    if not fa.get("ok"):
        st.info(fa.get("note", "FA read unavailable."))
    else:
        if fa.get("project"):
            st.markdown(f"**Project** — {fa['project']}")
        if fa.get("tokenomics"):
            st.markdown(f"**Tokenomics** — {fa['tokenomics']}")
        st.markdown("**Recent catalysts**")
        cats = fa.get("catalysts") or []
        if fa.get("nothing_recent") or not cats:
            st.caption("No genuinely recent catalysts found in the search — nothing to report "
                       "(not padding with stale background).")
        else:
            for c in cats:
                src = c.get("source", "?"); dt = c.get("date", "?")
                url = c.get("url", "")
                head = f"[{c.get('headline','(untitled)')}]({url})" if url else c.get("headline", "(untitled)")
                st.markdown(f"- {head}  \n  <span style='color:#8a8f98;font-size:12px'>"
                            f"{src} · {dt}</span>", unsafe_allow_html=True)
        if fa.get("read"):
            st.caption(f"Backdrop: {fa['read']}")
        st.caption(f"FA via {fa.get('model','Claude')} · {(fa.get('fetched_at') or '')[:16]}")
else:
    st.caption("On-demand — click to run the light fundamentals pass.")

# Deferred (v1): a per-coin sentiment meter and deeper on-chain/coin metrics slot
# in here — see desk/fundamentals.py (_sentiment, _onchain) for the seams.
