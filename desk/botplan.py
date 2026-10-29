"""On demand Bybit futures grid plan for any coin: /bot SOL [investment].

Reads 15m, 1h, 4h and daily structure, picks short grid, long grid or "no bot",
and sizes the least bad configuration from the grid backtest (docs/night/grid_backtest.md:
20 grids, 3x, range about 30 ATR(1h) with price a third from the edge, stop just past
the edge, close after 72h), then fits it to the trader's rules with guard.check_grid.

Honest status: grids broke even at best in the backtest, so every plan is labelled
"not edge tested" and stored for scoring. Neutral grids tested worst and are never
suggested.
"""
from __future__ import annotations
import json
import datetime as _dt
from utils.logger import get_logger

log = get_logger(__name__)
GRIDS = 20
LEVERAGE = 3
NEAR_K, FAR_K = 10.0, 20.0     # ATR(1h) multiples: stop side edge, profit side edge
MAX_HOLD_H = 72
EXTENDED_ATR = 4.0             # 4h distance from EMA50, in ATR, that counts as stretched


def _p(x: float) -> str:
    """Bybit enterable price text: 5 significant digits, no scientific notation."""
    if x is None:
        return "n/a"
    s = f"{x:.5g}"
    if "e" in s:
        s = f"{x:.10f}".rstrip("0").rstrip(".")
    return s


def classify(t15: dict | None, t1: dict | None, t4: dict | None, td: dict | None,
             btc4: dict | None, longs_allowed: bool) -> dict:
    """Pure decision from timeframe reads. Returns {mode, reason, warnings}."""
    warn: list[str] = []
    if not (t1 and t4):
        return {"mode": None, "reason": "not enough 1h/4h data for this coin", "warnings": warn}
    ext = t4.get("dist_from_ema50_atr") or 0.0
    up4 = t4.get("ema_stack") == "bull" and (t4.get("ema50_slope_pct_10bars") or 0) > 0
    dn4 = t4.get("ema_stack") == "bear" and (t4.get("ema50_slope_pct_10bars") or 0) < 0
    roll1 = t1["close"] < t1["ema20"] and (t1.get("change_pct_10bars") or 0) < 0
    reclaim1 = t1["close"] > t1["ema20"] and (t1.get("change_pct_10bars") or 0) > 0
    btc_down = bool(btc4) and btc4["close"] < btc4["ema50"]

    if ext >= EXTENDED_ATR and roll1:
        mode, why = "short", (f"stretched {ext:.1f} ATR above the 4h EMA50 and the 1h has rolled "
                              "over (close below 1h EMA20)")
    elif ext >= EXTENDED_ATR:
        return {"mode": None, "warnings": warn,
                "reason": (f"stretched {ext:.1f} ATR above the 4h EMA50 but still ripping. "
                           "Wait for a 1h close below the 1h EMA20 before a short grid")}
    elif dn4:
        mode, why = "short", "4h downtrend (bear EMA stack, EMA50 falling)"
    elif up4 and ext < 3 and longs_allowed:
        mode, why = "long", "4h uptrend and not stretched"
        warn.append("Long grids failed walk forward in the backtest; keep this one small")
    elif up4 and not longs_allowed:
        return {"mode": None, "warnings": warn,
                "reason": "4h uptrend, but the long gate is shut (BTC below its 50 day). No long bots"}
    elif ext <= -EXTENDED_ATR and reclaim1:
        return {"mode": None, "warnings": warn,
                "reason": "capitulation bounce. Bounce longs tested negative (PF 0.75); no bot"}
    else:
        return {"mode": None, "warnings": warn,
                "reason": "no clear 4h trend (ranging). Neutral grids tested worst of all; no bot"}
    if mode == "short" and not btc_down:
        warn.append("BTC is above its 4h EMA50; short grids did best with BTC below it. Consider half size")
    if mode == "short" and td and td.get("ema_stack") == "bull":
        warn.append("Daily trend is still up; this is a counter trend short")
    if t15 and mode == "short" and t15["close"] > t15["ema20"]:
        warn.append("15m is bouncing right now; a better fill may come on the next 15m rollover")
    return {"mode": mode, "reason": why, "warnings": warn}


def fit(mode: str, price: float, atr1: float, swing_hi: float | None, swing_lo: float | None,
        investment: float, mmr: float) -> dict:
    """Least bad grid geometry, tightened until it passes the 25% rule at 3x."""
    from guard import preflight as pf
    short = mode == "short"
    last = None
    for scale in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3, 0.2):
        near, far = NEAR_K * scale * atr1, FAR_K * atr1
        if short:
            hi = price + near
            if scale == 1.0 and swing_hi and swing_hi * 1.003 > hi:
                hi = swing_hi * 1.003            # stop above the recent high where possible
            lo = max(price - far, price * 0.3)
            stop = hi * 1.002
        else:
            lo = price - near
            if scale == 1.0 and swing_lo and swing_lo * 0.997 < lo:
                lo = swing_lo * 0.997
            hi = price + far
            stop = lo * 0.998
        if lo <= 0:
            continue
        v = pf.check_grid(mode, lo, hi, GRIDS, LEVERAGE, investment, stop, price, mmr=mmr)
        last = {"lo": lo, "hi": hi, "stop": stop, "verdict": v, "scale": scale}
        if v.ok:
            break
    return last or {}


def plan(symbol: str, investment: float | None = None, *, data=None) -> dict:
    """Build the plan. `data` = optional {tf: technicals dict} for tests."""
    from desk.agents.factpack import technicals
    if investment is None:
        try:
            from config import POSITION_MARGIN_USD as investment
        except Exception:                          # noqa: BLE001
            investment = 50.0
    base = symbol.upper().replace("-USD", "").replace("USDT", "")
    sym_usd = f"{base}-USD"
    if data is None:
        from utils import exchange
        try:
            from config import CANDLE_VENUE as venue
        except Exception:                          # noqa: BLE001
            venue = None
        data = {}
        for tf in ("15m", "1h", "4h", "1d"):
            try:
                data[tf] = technicals(exchange.get_ohlcv(sym_usd, tf, 300, exchange=venue))
            except Exception:                      # noqa: BLE001
                data[tf] = None
        try:
            data["btc4"] = technicals(exchange.get_ohlcv("BTC-USD", "4h", 300, exchange=venue))
        except Exception:                          # noqa: BLE001
            data["btc4"] = None
    try:
        from utils.breadth import long_gate
        longs_allowed = bool(long_gate()[0])
    except Exception:                              # noqa: BLE001
        longs_allowed = False
    c = classify(data.get("15m"), data.get("1h"), data.get("4h"), data.get("1d"),
                 data.get("btc4"), longs_allowed)
    out = {"symbol": f"{base}USDT", "investment": investment, **c, "reads": {
        tf: {k: (data.get(tf) or {}).get(k) for k in ("close", "ema_stack", "dist_from_ema50_atr", "rsi14")}
        for tf in ("15m", "1h", "4h", "1d")}}
    if not c["mode"]:
        return out
    t1 = data["1h"]
    try:
        from config import GUARD_SMALLCAP_MMR as mmr
    except Exception:                              # noqa: BLE001
        mmr = 0.05
    f = fit(c["mode"], t1["close"], t1["atr14"], t1.get("swing_high_20"), t1.get("swing_low_20"),
            investment, mmr)
    if not f or not f["verdict"].ok:
        out.update({"mode": None, "reason": out["reason"] + ". But no range fits your 25% rule at 3x "
                    "(too volatile right now); no bot"})
        return out
    m = f["verdict"].metrics
    out["grid"] = {"mode": c["mode"], "lo": f["lo"], "hi": f["hi"], "grids": GRIDS, "leverage": LEVERAGE,
                   "investment": investment, "stop": f["stop"], "entry": t1["close"],
                   "worst_loss": m.get("loss_at_stop"), "liq": m.get("liq") or m.get("liq_full"),
                   "max_hold_h": MAX_HOLD_H, "tightened": f["scale"] < 1.0}
    if f["scale"] < 1.0:
        out["warnings"].append("Range tightened to fit your 25% rule, so the stop is closer than ideal")
    try:
        from triggers import db
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
        db.set_state(f"botplan:{stamp}:{base}", json.dumps(out, default=str))
    except Exception as exc:                       # noqa: BLE001
        log.debug("botplan store failed: %s", exc)
    return out


def text(p: dict) -> str:
    sym = p["symbol"]
    rd = p.get("reads", {})
    tf_line = " · ".join(f"{tf} {(rd.get(tf) or {}).get('ema_stack') or 'n/a'}" for tf in ("15m", "1h", "4h", "1d"))
    if not p.get("mode"):
        return (f"🤖 <b>{sym}: no bot right now</b>\n{p['reason']}.\nTrend: {tf_line}"
                + "".join(f"\n⚠️ {w}" for w in p.get("warnings", [])))
    g = p["grid"]
    side = "Short" if g["mode"] == "short" else "Long"
    lines = [
        f"🤖 <b>{sym}: {side} grid</b>",
        f"Why: {p['reason']}.",
        f"Trend: {tf_line}",
        "",
        "<b>Futures Grid (Pionex or Bybit), manual setup:</b>",
        f"• Mode: <b>{side}</b>, Arithmetic, <b>{g['grids']} grids</b>",
        f"• Price range: <b>{_p(g['lo'])}</b> to <b>{_p(g['hi'])}</b>",
        f"• Leverage: <b>{g['leverage']}x</b> · Investment: <b>${g['investment']:,.2f}</b>",
        f"• Stop loss price: <b>{_p(g['stop'])}</b> (set it in TP/SL)",
        f"• Close it after {g['max_hold_h']}h if neither the stop nor your exit has hit",
        f"Worst case (every grid filled, then stopped): about ${g['worst_loss']:.2f}"
        + (f" · Liquidation about {_p(g['liq'])}" if g.get("liq") else ""),
    ]
    lines += [f"⚠️ {w}" for w in p.get("warnings", [])]
    lines.append("<i>Not edge tested: the best grid setup broke even in the backtest. "
                 "If you launch it, send /addbot BOTID " + sym.replace("USDT", "") + " so it gets scored.</i>")
    return "\n".join(lines)
