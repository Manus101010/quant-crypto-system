"""Build the desk's fact pack: the ONLY data the agents see.

Every number comes from code that already exists in this repo. Each section is
wrapped so a failing source becomes an entry in `missing`, never a crash.
"""
from __future__ import annotations
import datetime as _dt
from typing import Any
from utils.logger import get_logger

log = get_logger(__name__)
_TFS = (("15m", 300), ("1h", 300), ("4h", 300), ("1d", 300))


def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def technicals(df) -> dict | None:
    """Compact multi indicator read of one timeframe."""
    import pandas as pd
    if df is None or len(df) < 60:
        return None
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    e20, e50 = _ema(c, 20), _ema(c, 50)
    e200 = _ema(c, 200) if len(df) >= 200 else None
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    d = c.diff()
    up, dn = d.clip(lower=0).rolling(14).mean(), (-d.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, float("nan")))
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    bbw = (4 * sd / mid).dropna()
    px, a = float(c.iloc[-1]), float(atr.iloc[-1])
    stack = ("bull" if e20.iloc[-1] > e50.iloc[-1] and (e200 is None or e50.iloc[-1] > e200.iloc[-1])
             else "bear" if e20.iloc[-1] < e50.iloc[-1] and (e200 is None or e50.iloc[-1] < e200.iloc[-1])
             else "mixed")
    out = {
        "close": px,
        "ema20": float(e20.iloc[-1]), "ema50": float(e50.iloc[-1]),
        "ema200": float(e200.iloc[-1]) if e200 is not None else None,
        "ema_stack": stack,
        "ema50_slope_pct_10bars": float((e50.iloc[-1] / e50.iloc[-11] - 1) * 100),
        "atr14": a,
        "atr_change_pct_20bars": float((atr.iloc[-1] / atr.iloc[-21] - 1) * 100) if atr.iloc[-21] else None,
        "dist_from_ema50_atr": float((px - e50.iloc[-1]) / a) if a else None,
        "rsi14": float(rsi.iloc[-1]),
        "bb_width_pct_rank_100": float((bbw.iloc[-100:] <= bbw.iloc[-1]).mean() * 100) if len(bbw) else None,
        "swing_high_20": float(h.iloc[-20:].max()), "swing_low_20": float(l.iloc[-20:].min()),
        "volume_vs_20avg": float(v.iloc[-1] / v.iloc[-21:-1].mean()) if v.iloc[-21:-1].mean() else None,
        "change_pct_10bars": float((px / c.iloc[-11] - 1) * 100),
    }
    return {k: (round(x, 8) if isinstance(x, float) else x) for k, x in out.items()}


def _safe(pack: dict, key: str, fn) -> Any:
    try:
        val = fn()
        if val is None:
            pack["missing"].append(key)
        return val
    except Exception as exc:                          # noqa: BLE001
        log.debug("factpack %s failed: %s", key, exc)
        pack["missing"].append(key)
        return None


def _sizing(direction: str, entry: float, stop: float) -> dict:
    """The plain trade the alert would size: $50 margin, leverage so the stop loses <= 25%."""
    from config import (POSITION_MARGIN_USD, MAX_LOSS_PCT_OF_MARGIN, MAX_LEVERAGE,
                        ENTRY_MAX_SLIP_PCT, SIZING_FEE_PCT)
    # Same formula as monitor._sizing_line: worst case = stop distance + slip + fees.
    frac = abs(entry - stop) / entry + (ENTRY_MAX_SLIP_PCT + SIZING_FEE_PCT) / 100
    lev = int(min(MAX_LEVERAGE, (MAX_LOSS_PCT_OF_MARGIN / 100) / frac)) if frac else 1
    return {"margin": POSITION_MARGIN_USD, "leverage": max(1, lev)}


def build(symbol: str, direction: str, *, entry: float | None = None, stop: float | None = None,
          target: float | None = None, setup_label: str | None = None,
          trigger_id: int | None = None, position: dict | None = None) -> dict:
    """Fact pack for one signal (or one open position when `position` is given).
    `symbol` in either form: SOL-USD or SOLUSDT."""
    from utils import exchange
    base = symbol.upper().replace("-USD", "").replace("USDT", "")
    sym_usd, sym_perp = f"{base}-USD", f"{base}USDT"
    now = _dt.datetime.now(_dt.timezone.utc)
    pack: dict = {"meta": {"symbol": sym_perp, "direction": direction, "setup_label": setup_label,
                           "trigger_id": trigger_id, "built_utc": now.isoformat(timespec="seconds"),
                           "now_sydney": now.astimezone(_dt.timezone(_dt.timedelta(hours=11)))
                           .strftime("%a %d %b %H:%M AEDT")},
                  "missing": []}

    try:
        from config import CANDLE_VENUE as venue
    except Exception:                                 # noqa: BLE001
        venue = None
    tech = {}
    for tf, n in _TFS:
        tech[tf] = _safe(pack, f"technicals.{tf}",
                         lambda tf=tf, n=n: technicals(exchange.get_ohlcv(sym_usd, tf, n, exchange=venue)))
    pack["technicals"] = tech
    price = (tech.get("15m") or tech.get("1h") or {}).get("close") if any(tech.values()) else None
    entry = entry or price
    pack["trade"] = {"entry": entry, "stop": stop, "target": target, "price_now": price}

    def _feat():
        from features.snapshot import snapshot
        s = snapshot(sym_perp, direction)
        return {k: v for k, v in s.items() if not str(k).startswith("_")}
    pack["features"] = _safe(pack, "features", _feat)

    def _btc():
        from utils.btc_regime import get_btc_regime
        r = get_btc_regime()
        return {"label": r.get("label"), "detail": r.get("detail")}
    btc_tf = {}
    for tf in ("1h", "4h"):
        btc_tf[tf] = _safe(pack, f"market.btc_{tf}",
                           lambda tf=tf: technicals(exchange.get_ohlcv("BTC-USD", tf, 300, exchange=venue)))
    pack["market"] = {"btc_regime": _safe(pack, "market.btc_regime", _btc),
                      "btc_1h": btc_tf.get("1h"), "btc_4h": btc_tf.get("4h")}

    def _breadth():
        from utils.breadth import alt_breadth
        return alt_breadth()
    pack["market"]["breadth"] = _safe(pack, "market.breadth", _breadth)

    def _events_macro():
        from utils.events import macro_events
        return macro_events(3)

    def _events_coin():
        from utils.events import unlocks_for, catalysts_for
        return {"unlocks_7d": unlocks_for(sym_usd, 7), "catalysts_7d": catalysts_for(sym_usd, 7)}
    pack["events"] = {"macro": _safe(pack, "events.macro", _events_macro),
                      "coin": _safe(pack, "events.coin", _events_coin)}

    # Portfolio and ledger: open trades you took, heat, daily P&L, lock, revenge tags.
    def _heat():
        from triggers.outcomes import portfolio_heat
        h = portfolio_heat()
        return {k: h.get(k) for k in ("open_risk", "cap", "next_risk")}

    def _open():
        from triggers import db
        return [{k: t.get(k) for k in ("symbol", "direction", "setup_label", "entry", "stop", "fired_at")}
                for t in db.get_fired_trades(open_only=True) if t.get("taken")]

    def _ledger():
        from guard.ledger import Ledger
        led = Ledger()
        d = led.day()
        return {"realised_today": d.get("realised"), "stopouts_today": d.get("stopouts", 0),
                "cap_hit": d.get("cap_hit"), "lock_1r": bool(led.lock()),
                "unissued_positions_tagged": len(led.unissued() or {})}
    pack["portfolio"] = {"heat": _safe(pack, "portfolio.heat", _heat),
                         "open_trades": _safe(pack, "portfolio.open_trades", _open),
                         "ledger": _safe(pack, "portfolio.ledger", _ledger)}

    # Guard verdict and the only trade options the Trader may pick from.
    def _guard():
        from guard import preflight as pf
        if not (entry and stop):
            return None
        sz = _sizing(direction, entry, stop)
        v = pf.check_plain(direction, entry, stop, sz["leverage"], sz["margin"])
        return {"verdict": v.verdict, "failures": [f["rule"] for f in v.failures],
                "metrics": v.metrics, "plain": {"id": "plain", **sz, "entry": entry, "stop": stop,
                                                "target": target}}
    g = _safe(pack, "guard", _guard)
    pack["guard"] = {"verdict": g["verdict"], "failures": g["failures"], "metrics": g["metrics"]} if g else None
    options: dict = {"plain": g["plain"]} if g else {}

    def _grid():
        from guard import preflight as pf
        a = (tech.get("1h") or {}).get("atr14")
        if not (entry and stop and a):
            return None
        p = pf.propose_grid(direction, entry, a, stop=stop, target=target)
        return {"id": "grid", "edge_tested": False, **(p.get("plan") or {})} if p.get("ok") else None
    grid = _safe(pack, "guard_options.grid", _grid)
    if grid:
        options["grid"] = grid
    if position:
        options["tighten"] = position.get("tighten_options") or []
    pack["guard_options"] = options

    def _live():
        from triggers.outcomes import live_stats
        rows = live_stats().get("by_setup", [])
        return next((r for r in rows if r.get("setup") == setup_label), None) if setup_label else None
    pack["setup_live_stats"] = _safe(pack, "setup_live_stats", _live) if setup_label else None

    def _mem():
        from desk.agents import store
        return store.memory_for(setup_label, limit=5)
    pack["desk_memory"] = _safe(pack, "desk_memory", _mem) if setup_label else None

    if position:
        pack["position"] = position
    return pack


def flat_keys(obj: Any, prefix: str = "") -> set[str]:
    """Every dotted key path in the pack (for checking agents' citations)."""
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            keys.add(p)
            keys |= flat_keys(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            keys |= flat_keys(v, f"{prefix}.{i}")
    return keys
