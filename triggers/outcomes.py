"""
Live outcome tracking — what every fired signal actually did afterwards.

Freqtrade's dry-run idea, signal-only: each fired trigger is followed as a paper
trade under the SAME management the backtest used for its setup (breakouts trail
a stop from the peak, mean-reversion takes a fixed target), until it exits on
target / stop / trail / time. The result is stored as an R-multiple on the
trigger row, so live win rate and profit factor per setup can be compared with
the backtest — the only honest test of whether an edge is real.

Runs inside the monitor pass (ccxt OHLC only). Conservative fills: if a bar
touches both the stop and the target, the stop is assumed to hit first; a gap
through the stop fills at the open.
"""
from __future__ import annotations
import datetime
import pandas as pd
from triggers import db as tdb
from utils import exchange, telegram
from utils.logger import get_logger

log = get_logger(__name__)

_MIN_N_FOR_VERDICT = 10   # below this many closed trades, live stats are "early"


def _mgmt(label: str | None) -> dict:
    try:
        from triggers.scan import _management_params
        m = _management_params(label)
        if m:
            return m
    except Exception:                               # noqa: BLE001
        pass
    return {"trailing": False, "max_hold": 15, "target_r": 3.0}


def _simulate(t: dict, df: pd.DataFrame) -> dict | None:
    """Walk daily bars after the fire date. Returns outcome patch (outcome None = open)."""
    entry, stop = t.get("fired_price"), t.get("stop")
    if not entry or stop is None or not t.get("fired_at"):
        return None
    short = (t.get("direction") == "short")
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    m = _mgmt(t.get("setup_label"))
    trailing = bool(m.get("trailing")) and not t.get("target")
    target = t.get("target")
    max_hold = int(m.get("max_hold") or 15)

    fire_day = pd.Timestamp(t["fired_at"][:10])
    bars = df[df.index > fire_day]
    peak = entry
    trail = stop
    held = 0
    for ts, b in bars.iterrows():
        o, h, l, c = b["open"], b["high"], b["low"], b["close"]
        # 1) stop / trail (checked first — conservative)
        if (not short and l <= trail) or (short and h >= trail):
            px = (min(o, trail) if not short else max(o, trail))
            moved = (trail > stop) if not short else (trail < stop)
            return _closed(t, "trail" if moved else "stop", px, ts, entry, risk, short, peak, trail, held + 1)
        # 2) fixed target
        if target and ((not short and h >= target) or (short and l <= target)):
            return _closed(t, "target", target, ts, entry, risk, short, peak, trail, held + 1)
        held += 1
        # 3) ratchet the trailing stop off the new extreme
        if trailing:
            peak = max(peak, h) if not short else min(peak, l)
            trail = max(trail, peak - risk) if not short else min(trail, peak + risk)
        # 4) time exit on a completed bar
        if held >= max_hold and ts.date() < datetime.datetime.utcnow().date():
            return _closed(t, "time", c, ts, entry, risk, short, peak, trail, held)
    return {"outcome": None, "peak_price": float(peak), "trail_stop": float(trail),
            "bars_held": held}


def _closed(t, outcome, px, ts, entry, risk, short, peak, trail, held) -> dict:
    r = ((entry - px) if short else (px - entry)) / risk
    return {"outcome": outcome, "exit_price": float(px), "exit_at": ts.isoformat(),
            "r_multiple": round(float(r), 3), "peak_price": float(peak),
            "trail_stop": float(trail), "bars_held": int(held)}


def update_open_trades(notify: bool = True) -> dict:
    """Advance every open fired trade; close the ones that hit an exit."""
    open_trades = tdb.get_fired_trades(open_only=True)
    if not open_trades:
        return {"open": 0, "closed": 0}
    syms = sorted({t["symbol"] for t in open_trades})
    candles = exchange.get_ohlcv_batch(syms, timeframe="1d", limit=120, exchange="mexc")
    missing = [s for s in syms if s not in candles]
    if missing:   # not on MEXC → default chain
        candles.update(exchange.get_ohlcv_batch(missing, timeframe="1d", limit=120))
    closed = 0
    for t in open_trades:
        df = candles.get(t["symbol"])
        if df is None or df.empty:
            continue
        patch = _simulate(t, df)
        if patch is None:
            continue
        tdb.set_outcome(t["id"], patch)
        if patch.get("outcome"):
            closed += 1
            log.info("CLOSED #%d %s — %s %+.2fR", t["id"], t["symbol"],
                     patch["outcome"], patch["r_multiple"])
            if notify:
                telegram.send_message(_close_text(t, patch))
        elif notify and t.get("taken"):
            _maybe_nudge_trail(t, patch)
    return {"open": len(open_trades) - closed, "closed": closed}


_EXIT_PLAIN = {"target": "hit the take-profit 🎯", "stop": "hit the stop loss",
               "trail": "trailing stop was hit", "time": "time limit reached — closed at market"}


def _close_text(t: dict, p: dict) -> str:
    from config import RISK_PER_TRADE_USD
    r = p["r_multiple"]
    icon = "✅" if r > 0 else "❌"
    coin = t["symbol"].replace("-USD", "")
    usd = r * RISK_PER_TRADE_USD
    kind = "your trade" if t.get("taken") else "paper trade"
    return (f"{icon} <b>{coin} {kind} closed</b> — {_EXIT_PLAIN.get(p['outcome'], p['outcome'])}\n"
            f"Result: <b>{r:+.2f}R</b> — {'made' if r > 0 else 'lost'} {abs(r):.2f}× the amount risked "
            f"(≈ {'+' if usd >= 0 else '−'}${abs(usd):.0f} on a ${RISK_PER_TRADE_USD:.0f} risk) "
            f"after {p['bars_held']} day(s).\n<i>{t.get('setup_label','')}</i>")


def _maybe_nudge_trail(t: dict, p: dict) -> None:
    """For trades you TOOK: tell you when the trailing stop has moved enough to
    be worth raising (≥ 0.25 of the original risk since the last nudge)."""
    new, stop0, entry = p.get("trail_stop"), t.get("stop"), t.get("fired_price")
    if new is None or stop0 is None or not entry:
        return
    r0 = abs(entry - stop0)
    key = f"trail:{t['id']}"
    last = float(tdb.get_state(key) or stop0)
    short = t.get("direction") == "short"
    moved = (last - new) if short else (new - last)
    if r0 and moved >= 0.25 * r0:
        tdb.set_state(key, str(new))
        coin = t["symbol"].replace("-USD", "")
        safe = (new <= entry) if short else (new >= entry)
        telegram.send_message(
            f"⬆️ <b>Raise your {coin} stop to {new:.6g}</b>\n"
            f"The price has moved your way, so the trailing stop moves up with it."
            + ("\n🔒 That's past your entry — this trade can no longer lose money." if safe else ""))


# ── Stats: live track record vs backtest ──────────────────────────────────────
def _pf(rs: list[float]) -> float | None:
    gains = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def live_stats() -> dict:
    """Per-setup live record (closed trades) + backtest PF + drift verdict."""
    try:
        from backtesting.crypto_validation import load_validation
        bt = (load_validation() or {}).get("stats", {})
    except Exception:                               # noqa: BLE001
        bt = {}
    trades = tdb.get_fired_trades()
    closed = [t for t in trades if t.get("outcome")]
    by: dict[str, list[float]] = {}
    for t in closed:
        by.setdefault(t.get("setup_label") or "?", []).append(t["r_multiple"])
    rows = []
    for label, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        pf = _pf(rs)
        bt_pf = (bt.get(label) or {}).get("profit_factor")
        if len(rs) < _MIN_N_FOR_VERDICT:
            verdict = "early"
        elif pf is not None and pf < 1.0 and (bt_pf or 0) >= 1.0:
            verdict = "lagging backtest"
        elif pf is not None and pf >= 1.0:
            verdict = "holding up"
        else:
            verdict = "no edge live"
        rows.append({"setup": label, "n": len(rs),
                     "win_rate": sum(r > 0 for r in rs) / len(rs),
                     "avg_r": sum(rs) / len(rs), "total_r": sum(rs),
                     "pf": pf, "bt_pf": bt_pf, "verdict": verdict})
    all_r = [t["r_multiple"] for t in closed]
    total = {"n": len(all_r),
             "win_rate": (sum(r > 0 for r in all_r) / len(all_r)) if all_r else None,
             "total_r": sum(all_r), "pf": _pf(all_r) if all_r else None}
    open_ = [t for t in trades if not t.get("outcome")]
    return {"by_setup": rows, "total": total, "open": open_}


# ── Portfolio heat: total $ still at risk across open trades ──────────────────
def _open_risk_frac(t: dict) -> float:
    """Fraction of the original 1R still at risk (0 once the stop is at/through
    entry — a trail that has locked in profit no longer counts as heat)."""
    entry, stop0 = t.get("fired_price"), t.get("stop")
    cur = t.get("trail_stop") or stop0
    if not entry or stop0 is None or cur is None:
        return 1.0
    r0 = abs(entry - stop0)
    if r0 <= 0:
        return 0.0
    left = (cur - entry) if t.get("direction") == "short" else (entry - cur)
    return max(0.0, min(1.0, left / r0))


def portfolio_heat(risk_per_trade: float | None = None,
                   cap: float | None = None) -> dict:
    """Counts open trades you marked taken, each at `risk_per_trade`. Returns open $ risk,
    remaining budget, and what a NEW trade should risk to stay under the cap."""
    from config import RISK_PER_TRADE_USD, MAX_PORTFOLIO_RISK_USD
    rpt = risk_per_trade if risk_per_trade is not None else RISK_PER_TRADE_USD
    cap = cap if cap is not None else MAX_PORTFOLIO_RISK_USD
    # Heat is REAL risk: only trades you marked as taken. Paper-tracked signals
    # (everything else) feed the track record but carry no money at risk.
    paper = tdb.get_fired_trades(open_only=True)
    open_ = [t for t in paper if t.get("taken")]
    at_risk = sum(_open_risk_frac(t) * rpt for t in open_)
    n_long = sum(1 for t in open_ if t.get("direction") != "short")
    left = max(0.0, cap - at_risk)
    return {"open_risk": round(at_risk, 2), "cap": cap, "left": round(left, 2),
            "n_open": len(open_), "n_long": n_long, "n_short": len(open_) - n_long,
            "next_risk": round(min(rpt, left), 2), "risk_per_trade": rpt,
            "n_paper": len(paper)}


def open_marks(trades: list[dict] | None = None) -> dict:
    """Mark-to-market for open trades: {trigger_id: R now} from the latest price
    (paper P&L so far, in units of the initial risk). Network: ccxt last close."""
    trades = trades if trades is not None else tdb.get_fired_trades(open_only=True)
    if not trades:
        return {}
    syms = sorted({t["symbol"] for t in trades})
    px = {}
    got = exchange.get_ohlcv_batch(syms, timeframe="1d", limit=2, exchange="mexc")
    missing = [s for s in syms if s not in got]
    if missing:
        got.update(exchange.get_ohlcv_batch(missing, timeframe="1d", limit=2))
    for s, df in got.items():
        if df is not None and not df.empty:
            px[s] = float(df["close"].iloc[-1])
    out = {}
    for t in trades:
        e, s0, p = t.get("fired_price"), t.get("stop"), px.get(t["symbol"])
        if not e or s0 is None or p is None or e == s0:
            continue
        risk = abs(e - s0)
        out[t["id"]] = round(((e - p) if t.get("direction") == "short" else (p - e)) / risk, 2)
    return out
