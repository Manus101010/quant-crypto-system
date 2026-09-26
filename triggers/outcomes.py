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
                icon = "✅" if patch["r_multiple"] > 0 else "❌"
                telegram.send_message(
                    f"{icon} <b>{t['symbol']}</b> closed — {t.get('setup_label','')}\n"
                    f"Exit: {patch['outcome']} at {patch['exit_price']:.6g} → "
                    f"<b>{patch['r_multiple']:+.2f}R</b> after {patch['bars_held']}d")
    return {"open": len(open_trades) - closed, "closed": closed}


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
