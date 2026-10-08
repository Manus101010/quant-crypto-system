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
        ["Bybit — USDT perps", "MEXC — all pairs", "Top by market cap"],
        index=0,
        help="Bybit: every crypto USDT perpetual on Bybit — the venue you trade (native "
             "stop-loss, take-profit and trailing stops; longs and shorts).",
    )
    src = ("bybit_perps" if source_lbl.startswith("Bybit") else
           "mexc" if source_lbl.startswith("MEXC") else "top_mcap")
    is_mexc = src != "top_mcap"          # venue-wide scan (name kept for the UI below)
    universe = 100
    if src == "top_mcap":
        universe = st.selectbox("Top by mcap", [50, 100, 200, 300, 500], index=1)
with c2:
    top_n = st.slider("Arm top N", 3, 25, 10)
    min_vol_m = st.selectbox("Min 24h volume", [0.0, 0.5, 1.0, 5.0, 10.0], index=2,
                             format_func=lambda v: "off" if v == 0 else f"${v:g}M")
    risk_usd = st.number_input("Risk / trade ($)", min_value=0, max_value=100000,
                               value=st.session_state.get("risk_usd", __import__("config").RISK_PER_TRADE_USD), step=10,
                               help="Dollars you're willing to lose if the stop hits. "
                                    "Tiles show the position size that risks exactly this — "
                                    "the point of a wide ATR stop is a SMALL position.")
    st.session_state["risk_usd"] = risk_usd
with c3:
    expiry = st.selectbox("Trigger expiry (h)", [24, 48, 72, 168], index=1)
    max_stop_lbl = st.selectbox("Max stop distance", ["off", "25%", "40%", "60%"], index=2,
                                help="Don't arm setups whose stop is further than this from "
                                     "entry — a full-size position there is a huge single loss.")
    max_stop_pct = None if max_stop_lbl == "off" else float(max_stop_lbl.rstrip("%"))
    diversify = st.checkbox("Diversify setups", value=True,
                            help="Cap how many of any one setup can be armed so the "
                                 "watchlist is a spread across strategy types.")
    run = st.button("🛰️ Run Scan & Arm", type="primary", width="stretch")

if is_mexc:
    st.caption(f"🌐 {source_lbl}: candles pinned to that venue so levels match what you "
               "trade. Takes a minute or two; keep a volume floor on to stay tradeable.")

# Pull the latest macro deployment score to bias conviction by regime (if run).
regime_score = None
mr = st.session_state.get("macro_result")
if mr:
    regime_score = mr.get("deployment_score")

if run:
    spin = (f"Scanning {source_lbl} via ccxt … (a minute or two)"
            if is_mexc else f"Scanning top {universe} coins via ccxt … (~20-40s)")
    with st.spinner(spin):
        from triggers.scan import run_scan_and_arm
        res = run_scan_and_arm(universe_size=universe, top_n=top_n,
                               regime_score=regime_score, expiry_hours=expiry,
                               min_vol_usd_m=min_vol_m,
                               source=src,
                               max_per_setup=(max(2, top_n // 3) if diversify else None),
                               max_stop_pct=max_stop_pct)
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
    if res.get("wide_stop_excluded"):
        st.caption("🛡️ Excluded (stop too wide to risk): " + ", ".join(res["wide_stop_excluded"]))
    if res.get("held_excluded"):
        st.caption("📌 Not re-armed (already an open trade — still ranked below): "
                   + ", ".join(res["held_excluded"]))
    if res.get("crowded_excluded"):
        st.caption("🐑 Skipped (crowded side — extreme funding): " + ", ".join(res["crowded_excluded"]))

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
    # Prefer a $-prefixed number: text like "Buy the 55-day breakout near $190"
    # must parse as 190, not the 55 in "55-day".
    m = re.search(r"\$\s*([-+]?\d[\d,]*\.?\d*)", str(s))
    if m:
        return float(m.group(1).replace(",", ""))
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
    return f"https://www.tradingview.com/chart/?symbol=BYBIT:{base}USDT.P"   # Bybit perp chart


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
    if kind == "mr_reversal_short":
        return (f"the bounce rolls over — RSI(2) turns back down through "
                f"{c.get('rsi2_level',88):.0f} on a red bar while price is still above "
                f"the {_fmt(c.get('mean'))} mean")
    if kind == "breakout":
        return f"price closes above {_fmt(c.get('level'))} (invalidates below stop)"
    if kind == "breakdown":
        return f"price closes below {_fmt(c.get('level'))} (invalidates above stop)"
    return f"{t.get('condition_type')} @ {t.get('condition_value')}"


_WIDE_STOP_PCT = 25.0     # stops beyond this = size down hard or skip


def _stop_pct(entry, stop) -> float | None:
    e, s = _price(entry), _price(stop)
    if not e or not s or e == 0:
        return None
    return abs(e - s) / e * 100


def _mgmt(label):
    try:
        from triggers.scan import _management_params
        return _management_params(label) or {}
    except Exception:                               # noqa: BLE001
        return {}


def _exit_text(entry, stop, target, label, direction="long") -> tuple[str, str]:
    """(TARGET cell, R:R cell) in plain words: fixed target, or '½ at $X' then trail."""
    t = _price(target)
    if t is not None:
        return _fmt(t), None
    m = _mgmt(label)
    part = m.get("partial") or {}
    e, sp = _price(entry), _price(stop)
    if part.get("at_r") and e and sp:
        d = abs(e - sp)
        px = e + part["at_r"] * d if direction == "long" else e - part["at_r"] * d
        return f"½ at {_fmt(px)}", "then trail"
    return "trail ↑", "no cap"


def _bot_hint(direction, entry, stop, target, label, risk_usd) -> str:
    """The same trade as a Bybit futures grid bot (desk/gridplan.py)."""
    try:
        from desk.gridplan import grid_for_signal
        e, sp = _price(entry), _price(stop)
        if not e or not sp or not risk_usd:
            return ""
        atr = abs(e - sp) / float(_mgmt(label).get("stop_mult") or 3.0)
        g = grid_for_signal(direction, e, sp, _price(target), atr, float(risk_usd))
        if not g.get("ok"):
            return (f"<div style='margin-top:6px;font-size:12px;color:#8a8f98'>🤖 Grid bot: "
                    f"not suggested ({g.get('note', '')})</div>")
        tp = f" · TP {_fmt(g['take_profit'])}" if g.get("take_profit") else ""
        return (f"<div style='margin-top:6px;font-size:12px;color:#c9ccd3'>🤖 <b>Grid bot:</b> "
                f"{g['mode']} {g['leverage']}× · {_fmt(g['lower'])}–{_fmt(g['upper'])} · "
                f"{g['grids']} grids · invest ~${g['margin']:,.0f} · "
                f"<b>stop-loss {_fmt(g['stop_loss'])}</b>{tp}</div>")
    except Exception:                               # noqa: BLE001
        return ""


def _size_hint(entry, stop, risk_usd) -> str:
    """Position size that risks exactly `risk_usd` given this stop distance —
    the whole point of a wide ATR stop is a correspondingly SMALL position."""
    sp = _stop_pct(entry, stop)
    if not sp or sp <= 0 or not risk_usd:
        return ""
    pos_usd = risk_usd / (sp / 100)
    e = _price(entry)
    units = pos_usd / e if e else None
    if units is None:
        unit_txt = ""
    elif units >= 1000:
        unit_txt = f" ≈ {units:,.0f} coins"
    elif units >= 1:
        unit_txt = f" ≈ {units:,.1f} coins"
    else:
        unit_txt = f" ≈ {units:.4g} coins"
    return (f"<div style='margin-top:8px;font-size:12px;color:#c9ccd3'>"
            f"💰 Risk ${risk_usd:g} → position <b>${pos_usd:,.0f}</b>{unit_txt} "
            f"<span style='color:#8a8f98'>(stop −{sp:.0f}%)</span></div>")


def _legs(entry, target, stop, rr) -> str:
    def leg(label, val, color="#e6e6e6", sub=""):
        sub_html = (f"<div style='font-size:10px;color:{_MUTE};margin-top:1px'>{sub}</div>"
                    if sub else "")
        return (f"<div style='flex:1;min-width:64px'>"
                f"<div style='font-size:10px;color:{_MUTE};text-transform:uppercase;"
                f"letter-spacing:.05em'>{label}</div>"
                f"<div style='font-size:15px;font-weight:600;color:{color}'>{val}</div>"
                f"{sub_html}</div>")
    # Trailing setups have no fixed target — say so instead of showing a bogus R:R.
    worded = isinstance(target, str) and not target.strip().startswith("$") \
        and not target.strip()[:1].isdigit()
    trailing = worded or _price(target) is None
    if worded:
        tgt_txt = target                          # plain-words exit ("½ at $X", "trail ↑")
    else:
        tgt_txt = "trail" if trailing else _fmt(target)
    if isinstance(rr, str) and _price(rr) is None:
        rr_txt = rr
    else:
        rr_txt = "—" if trailing else (str(rr) if rr else "—")
    sp = _stop_pct(entry, stop)
    stop_sub = f"−{sp:.0f}%" if sp is not None else ""
    stop_color = "#f59e0b" if (sp is not None and sp >= _WIDE_STOP_PCT) else _SHORT
    return ("<div style='display:flex;gap:8px;margin-top:10px'>"
            + leg("Entry", _fmt(entry))
            + leg("Target", tgt_txt, _LONG)
            + leg("Stop", _fmt(stop), stop_color, stop_sub)
            + leg("R:R", rr_txt)
            + "</div>")


@st.cache_data(ttl=300, show_spinner=False)
def _candles_for(symbols: tuple[str, ...], bars: int = 45) -> dict:
    """Recent daily candles for the displayed symbols (cached 5m). Read-only ccxt."""
    if not symbols:
        return {}
    from utils import exchange
    out = {}
    # Pin to MEXC: the watched coins come from the MEXC scan and many are MEXC-only
    # microcaps the default fallback chain can't resolve (blank tiles otherwise).
    data = exchange.get_ohlcv_batch(list(symbols), timeframe="1d", limit=bars + 5,
                                    exchange=__import__("config").CANDLE_VENUE)
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


@st.cache_data(ttl=3600, show_spinner=False)
def _unlock_soon(symbol: str) -> bool:
    try:
        from utils import events
        return bool(events.unlocks_for(symbol, 7))
    except Exception:                               # noqa: BLE001
        return False


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
    with st.expander(f"🎯 Candidates — not armed unless badged 📡 · {n_found} valid setup"
                     f"{'s' if n_found != 1 else ''} (showing {len(res['candidates'])})", expanded=True):
        st.caption("Every coin that passed the edge gate this scan, best first. These are NOT "
                   "trades. Only 📡 armed ones are being watched — see **Watching now** below; an "
                   "alert fires when their trigger level is hit. Each tile shows the exact plan it "
                   "would be armed with (backtested stop, and a fixed target or a trailing stop).")
        hs = res.get("held_status") or {}
        if hs:
            _v = {"valid": "✅ still a valid setup", "gone": "⚠️ setup gone — review",
                  "not_scanned": "· not in this scan's universe"}
            st.markdown("**📌 Your open trades vs this scan:** " + " · ".join(
                f"{sym} {_v.get(x['verdict'], x['verdict'])}"
                + (f" ({x['setup']})" if x['verdict'] == 'valid' else "")
                for sym, x in sorted(hs.items(), key=lambda kv: kv[1]["verdict"] != "gone")))
        cand_candles = _candles_for(tuple(r["ticker"] for r in res["candidates"]))
        _risk = st.session_state.get("risk_usd", __import__("config").RISK_PER_TRADE_USD)
        cards = []
        _badge = {"armed": "📡 armed", "held": "📌 in trade", "wide_stop": "🛡️ stop too wide",
                  "crowded": "🐑 crowded (funding)", "not_selected": "⏭️ not selected",
                  "bad_plan": "⚠️ no usable stop", "btc_downtrend": "⛔ market trend gate"}
        for r in res["candidates"]:
            t = r.get("trade") or {}
            p = r.get("_plan") or {}
            is_long = (p.get("direction") or ("long" if t.get("action") == "BUY" else "short")) == "long"
            e, sp, tg = p.get("entry", t.get("entry")), p.get("stop", t.get("stop")), p.get("target")
            _dir = "long" if is_long else "short"
            tg_disp, rr_txt = _exit_text(e, sp, tg if p else t.get("target"), r.get("setup_label"), _dir)
            rr_disp = rr_txt or (p.get("rr") if p else t.get("rr"))
            cards.append(_card(
                r["ticker"], is_long, r.get("setup_label", ""),
                f"<b>{_badge.get(r.get('_status'), '')}</b>"
                + (" · 🔓 unlock soon" if _unlock_soon(r["ticker"]) else "")
                + f" · score {r.get('_composite')}",
                _legs(e, tg_disp, sp, rr_disp),
                footer=_size_hint(e, sp, _risk)
                       + (_bot_hint(_dir, e, sp, tg, r.get("setup_label"), _risk)
                          if r.get("_status") in ("armed", "not_selected", "held") else ""),
                chart_svg=_svg_chart(cand_candles.get(r["ticker"]), e, sp, tg, is_long),
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
    if active and st.button("Cancel all", width="stretch"):
        n = tdb.clear_active()
        st.toast(f"Cancelled {n} triggers.")
        st.rerun()

if active:
    st.caption(f"{len(active)} live trigger{'s' if len(active) != 1 else ''} — the monitor "
               f"alerts your phone the moment one fires.")
    act_candles = _candles_for(tuple(t["symbol"] for t in active))
    _risk = st.session_state.get("risk_usd", __import__("config").RISK_PER_TRADE_USD)
    cards = []
    for t in active:
        is_long = t["direction"] == "long"
        _tg, _rr = _exit_text(t.get("entry"), t.get("stop"), t.get("target"),
                              t.get("setup_label"), t["direction"])
        cards.append(_card(
            t["symbol"], is_long, t.get("setup_label", ""),
            f"👁 {_expires_in(t.get('expires_at'))}",
            _legs(t.get("entry"), _tg, t.get("stop"), _rr or t.get("rr")),
            footer=f"<b style='color:#c9ccd3'>Fires when</b> {_cond_plain(t)}"
                   + _size_hint(t.get("entry"), t.get("stop"), _risk)
                   + _bot_hint(t["direction"], t.get("entry"), t.get("stop"), t.get("target"),
                               t.get("setup_label"), _risk),
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

# ── Live track record: what fired signals actually did (vs backtest) ──────────
st.subheader("📒 Live track record")
st.caption("Every fired signal is followed as a paper trade under its backtested exit "
           "rules until target / stop / trail / time. R = profit in units of the risk "
           "taken (+1R = made what the stop would have lost). Needs ~30 trades to mean much.")
try:
    from triggers import outcomes as _oc
    _ls = _oc.live_stats()
    _tot = _ls["total"]
    _h = _oc.portfolio_heat(risk_per_trade=float(st.session_state.get("risk_usd", __import__("config").RISK_PER_TRADE_USD)))
    _pct = min(1.0, _h["open_risk"] / _h["cap"]) if _h["cap"] else 0
    _col = "#f87171" if _h["left"] <= 0 else ("#facc15" if _pct > 0.7 else "#4ade80")
    st.markdown(
        f"<div style='border-left:4px solid {_col};padding:8px 12px;background:#161b22;"
        f"border-radius:6px;margin-bottom:10px'>🔥 <b>Portfolio heat</b> — "
        f"<b style='color:{_col}'>${_h['open_risk']:.0f}</b> of ${_h['cap']:.0f} at risk across "
        f"{_h['n_open']} trade(s) you took ({_h['n_long']} long / {_h['n_short']} short)"
        + (f" — correlation-adjusted from ${_h['gross_risk']:.0f} (hedges offset, same-way "
           f"trades counted as moving together). " if abs(_h['gross_risk'] - _h['open_risk']) >= 1
           else ". ")
        + ("<b>Full — new alerts will say skip.</b>" if _h["left"] <= 0 else
           f"Next trade can risk <b>${_h['next_risk']:.0f}</b>.")
        + "<br><span style='color:#8b949e;font-size:0.85em'>Real money only — tick "
          f"<b>Took it</b> below for trades you actually entered ({_h['n_paper']} paper-tracked "
          f"open). Each counts ${_h['risk_per_trade']:.0f} until its trailing stop passes "
          "entry. Cap = MAX_PORTFOLIO_RISK_USD.</span></div>",
        unsafe_allow_html=True)
    @st.cache_data(ttl=900, show_spinner=False)
    def _marks(_ids: tuple) -> dict:
        return _oc.open_marks()
    _mk = _marks(tuple(t["id"] for t in _ls["open"])) if _ls["open"] else {}
    _ur = sum(_mk.values())
    o1, o2, o3 = st.columns(3)
    o1.metric("Signals fired", _tot["n"] + len(_ls["open"]))
    o2.metric("Still open", len(_ls["open"]),
              help="Fired but not yet at stop / target / time limit — no final result yet.")
    o3.metric("Open P&L now", f"{_ur:+.2f}R" if _mk else "—",
              help="Paper profit/loss of the open trades at the latest price, in R.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Closed trades", _tot["n"])
    c2.metric("Win rate", f"{_tot['win_rate']*100:.0f}%" if _tot["win_rate"] is not None else "—")
    c3.metric("Total R", f"{_tot['total_r']:+.2f}R" if _tot["n"] else "—")
    _pfv = _tot["pf"]
    c4.metric("Profit factor", "—" if _pfv is None else ("∞" if _pfv == float("inf") else f"{_pfv:.2f}"))
    _ys = _oc.live_stats(taken_only=True)
    _yt = _ys["total"]
    st.caption("🙋 Your trades only (ticked \"Took it\"). Compare with the row above: "
               "if yours trail the system, the gap is execution or selection, not the edge.")
    y1, y2, y3, y4 = st.columns(4)
    y1.metric("Your closed", _yt["n"], help=f"{len(_ys['open'])} still open")
    y2.metric("Your win rate", f"{_yt['win_rate']*100:.0f}%" if _yt["win_rate"] is not None else "—")
    from config import RISK_PER_TRADE_USD as _rpt
    y3.metric("Your total", f"{_yt['total_r']:+.2f}R (${_yt['total_r']*_rpt:+.2f})" if _yt["n"] else "—")
    _ypf = _yt["pf"]
    y4.metric("Your profit factor", "—" if _ypf is None else ("∞" if _ypf == float("inf") else f"{_ypf:.2f}"))
    if _ls["by_setup"]:
        import pandas as _pd
        _vcol = {"early": "⏳ early", "holding up": "✅ holding up",
                 "lagging backtest": "⚠️ lagging backtest", "no edge live": "❌ no edge live"}
        st.dataframe(_pd.DataFrame([{
            "Setup": r["setup"], "Trades": r["n"], "Win %": f"{r['win_rate']*100:.0f}%",
            "Avg R": f"{r['avg_r']:+.2f}", "Total R": f"{r['total_r']:+.2f}",
            "Live PF": "∞" if r["pf"] == float("inf") else ("—" if r["pf"] is None else f"{r['pf']:.2f}"),
            "Backtest PF": "—" if r["bt_pf"] is None else f"{r['bt_pf']:.2f}",
            "Verdict": _vcol.get(r["verdict"], r["verdict"]),
        } for r in _ls["by_setup"]]), hide_index=True, width="stretch")
    if _ls["open"]:
        import pandas as _pd2
        st.markdown("**Open trades** — every alert is paper-tracked; tick **Took it** for the "
                    "ones you really entered so heat counts real risk.")
        _odf = _pd2.DataFrame([{
            "id": t["id"], "Took it": bool(t.get("taken")), "Coin": t["symbol"],
            "Setup": t.get("setup_label") or "", "Fired": (t.get("fired_at") or "")[:10],
            "Entry": t.get("fired_price"), "Stop now": t.get("trail_stop") or t.get("stop"),
            "Days": t.get("bars_held") or 0,
            "R now": _mk.get(t["id"]),
        } for t in _ls["open"]])
        _ed = st.data_editor(_odf, hide_index=True, width="stretch",
                             disabled=[c for c in _odf.columns if c != "Took it"],
                             column_config={"id": None}, key="open_trades_editor")
        _chg = _ed[_ed["Took it"] != _odf["Took it"]]
        if len(_chg):
            for _, _row in _chg.iterrows():
                tdb.set_outcome(int(_row["id"]), {"taken": bool(_row["Took it"])})
            st.rerun()
except Exception as _e:                            # noqa: BLE001
    st.caption(f"Track record unavailable ({_e}).")

st.divider()
st.caption("Alerts run 24/7 in the cloud (GitHub Actions, every 15 min) — this page "
           "and the monitor share one Supabase database. Signal only; no trading.")
