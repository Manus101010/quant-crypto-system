#!/usr/bin/env python3
"""
QuantCore Monitor — standalone always-on trigger watcher.

Runs OUTSIDE Streamlit (tmux / systemd on a cheap always-on host). On each poll
it evaluates every active trigger armed by the scanner and, when a condition is
met, pushes a Telegram alert to the user's phone and marks the trigger fired.

SIGNAL ONLY: this process reads public market data (ccxt, read-only) and sends
notifications. It never places orders, holds keys, or touches an account.

Usage:
    python monitor.py                 # default 180s poll
    python monitor.py --interval 60   # 1-minute poll
    python monitor.py --once          # single pass then exit (for testing/cron)

Rate limits: symbols are batched per poll (one price fetch for all price
triggers; grouped candle fetches for indicator triggers). ccxt paces each venue.
"""
from __future__ import annotations
import time
import argparse
import datetime
import numpy as np
import pandas as pd

from triggers import db as tdb
from utils import exchange
from utils import telegram
from utils.logger import get_logger

log = get_logger("monitor")

_MIN_INTERVAL = 60          # respect exchange rate limits
_CANDLE_LIMIT = 120


def _rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _fmt_price(p) -> str:
    if p is None:
        return "—"
    p = float(p)
    if p < 0.01:  return f"${p:.6f}"
    if p < 1:     return f"${p:.4f}"
    if p < 100:   return f"${p:.2f}"
    return f"${p:,.2f}"


def _alert_text(trg: dict, price: float, reason: str) -> str:
    direction = trg.get("direction") or "long"
    if direction == "short":
        arrow = "🔴 SHORT  (MEXC futures/perp)"
    else:
        arrow = "🟢 LONG  (spot)"
    cat = (trg.get("setup_category") or "").replace("_", " ")
    lines = [
        f"⚡ <b>{trg['symbol']}</b> — {trg.get('setup_label','setup')}",
        f"{arrow}  ·  {cat}",
        f"<b>Trigger met:</b> {reason}",
        f"Price now: <b>{_fmt_price(price)}</b>",
    ]
    if trg.get("entry"):  lines.append(f"Entry: {_fmt_price(trg['entry'])}")
    if trg.get("target"): lines.append(f"Target: {_fmt_price(trg['target'])}")
    if trg.get("stop"):   lines.append(f"Stop: {_fmt_price(trg['stop'])}")
    if trg.get("rr"):     lines.append(f"R:R: {trg['rr']}")
    lines.append(f"📐 {_management_note(trg.get('setup_label'))}")
    # Direction-aware BTC regime stamp (WARNING, never a veto in v1).
    try:
        from utils import btc_regime
        reg = btc_regime.get_btc_regime()
        stamp = btc_regime.stamp_for(reg["label"], direction)
        lines.append(f"🧭 BTC {reg['label']} — {reg.get('detail','')}  {stamp}")
    except Exception as exc:                       # noqa: BLE001 — never block an alert
        log.debug("btc_regime stamp failed: %s", exc)
    lines.append("\n<i>Signal only — review and execute manually.</i>")
    return "\n".join(lines)


def _management_note(setup_label: str | None = None) -> str:
    """Per-setup trade management from the saved validation (breakouts trail; the
    rest take a fixed target)."""
    m = None
    try:
        from backtesting.crypto_validation import load_validation
        v = load_validation() or {}
        if setup_label:
            m = (v.get("management_by_setup") or {}).get(setup_label)
        if not m and not v.get("management_by_setup"):
            m = (v.get("meta", {}).get("params", {}) or {}).get("management")
        if not m and setup_label:
            from backtesting.crypto_optimize import management_for
            m = management_for(setup_label)
    except Exception:
        m = None
    if not m:
        return "Manage per the Validation page."
    if m.get("trailing"):
        return f"Trail a {m['stop_mult']}×ATR stop, let winners run (hold ≤{m['max_hold']}d)."
    return (f"{m['stop_mult']}×ATR stop, take profit at {m['target_r']}R "
            f"(hold ≤{m['max_hold']}d).")


def _indicators(df: pd.DataFrame) -> dict | None:
    """Live indicator bundle from candles: price, prior close, RSI(2), RSI(14), 20d mean."""
    if len(df) < 25:
        return None
    close = df["close"]
    rsi2 = _rsi_series(close, 2).dropna()
    rsi14 = _rsi_series(close, 14).dropna()
    if len(rsi2) < 2 or len(rsi14) < 1:
        return None
    return {
        "price":     float(close.iloc[-1]),
        "prev":      float(close.iloc[-2]),
        "rsi2_now":  float(rsi2.iloc[-1]),
        "rsi2_prev": float(rsi2.iloc[-2]),
        "rsi14_now": float(rsi14.iloc[-1]),
        "mean20":    float(close.iloc[-20:].mean()),
    }


def _evaluate(trg: dict, ind: dict) -> tuple[str, str]:
    """
    Returns (verdict, reason) where verdict is 'fire' | 'invalidate' | 'wait'.
    Multi-factor confirmation per setup kind; auto-invalidates on a stop hit.
    """
    import json as _json
    cond = _json.loads(trg["condition_json"]) if trg.get("condition_json") else {}
    kind = cond.get("kind")
    price, prev = ind["price"], ind["prev"]
    stop = cond.get("stop")

    if kind == "mr_reversal":
        if stop and price <= stop:
            return ("invalidate", f"stop {_fmt_price(stop)} hit before the bounce")
        lvl = cond.get("rsi2_level", 12.0)
        mean = cond.get("mean")
        turned    = ind["rsi2_prev"] < lvl <= ind["rsi2_now"]      # RSI(2) turning up
        green     = price > prev                                    # price confirming
        below_mean = mean is None or price < mean                   # still in reversion zone
        above_stop = stop is None or price > stop
        if turned and green and below_mean and above_stop:
            return ("fire", f"RSI2 {ind['rsi2_prev']:.0f}→{ind['rsi2_now']:.0f}↑, green bar, "
                            f"below mean {_fmt_price(mean)}")
        return ("wait", "")

    if kind == "mr_reversal_short":
        # Overbought bounce rolls over (SHORT): RSI(2) turns back DOWN through the
        # level + red bar + still above the mean + below the stop. Stop is ABOVE.
        if stop and price >= stop:
            return ("invalidate", f"stop {_fmt_price(stop)} hit before the roll-over")
        lvl = cond.get("rsi2_level", 88.0)
        mean = cond.get("mean")
        turned    = ind["rsi2_prev"] > lvl >= ind["rsi2_now"]      # RSI(2) turning down
        red       = price < prev                                    # price confirming down
        above_mean = mean is None or price > mean                   # still stretched up
        below_stop = stop is None or price < stop
        if turned and red and above_mean and below_stop:
            return ("fire", f"RSI2 {ind['rsi2_prev']:.0f}→{ind['rsi2_now']:.0f}↓, red bar, "
                            f"above mean {_fmt_price(mean)}")
        return ("wait", "")

    if kind == "breakout":
        if stop and price <= stop:
            return ("invalidate", f"stop {_fmt_price(stop)} hit before breakout")
        lvl, rmax = cond.get("level"), cond.get("rsi_max", 80)
        if lvl is not None and price >= lvl and ind["rsi14_now"] < rmax:
            return ("fire", f"broke {_fmt_price(lvl)}, RSI14 {ind['rsi14_now']:.0f} (&lt;{rmax})")
        return ("wait", "")

    if kind == "breakdown":
        if stop and price >= stop:
            return ("invalidate", f"stop {_fmt_price(stop)} hit")
        lvl, rmin = cond.get("level"), cond.get("rsi_min", 20)
        if lvl is not None and price <= lvl and ind["rsi14_now"] > rmin:
            return ("fire", f"broke {_fmt_price(lvl)} down, RSI14 {ind['rsi14_now']:.0f} (&gt;{rmin})")
        return ("wait", "")

    # ── Legacy single-factor fallback (older triggers) ────────────────────────
    ct, cv = trg["condition_type"], trg["condition_value"]
    if ct == "price_below" and price <= cv:
        return ("fire", f"price {_fmt_price(price)} ≤ {_fmt_price(cv)}")
    if ct == "price_above" and price >= cv:
        return ("fire", f"price {_fmt_price(price)} ≥ {_fmt_price(cv)}")
    if ct == "rsi_cross_up" and ind["rsi14_now"] >= cv:
        return ("fire", f"RSI reclaimed {cv:.0f}")
    return ("wait", "")


def _regime_vetoes(trg: dict) -> bool:
    """
    Whether the BTC regime veto hooks (config, both default off) block this fire.
    Longs vetoed while RISK-OFF (BTC_REGIME_VETO); shorts vetoed while RISK-ON
    (SHORT_VETO_IN_RISK_ON). v1 has both off → always returns False.
    """
    import config
    long_veto = getattr(config, "BTC_REGIME_VETO", False)
    short_veto = getattr(config, "SHORT_VETO_IN_RISK_ON", False)
    if not (long_veto or short_veto):
        return False
    try:
        from utils import btc_regime
        label = btc_regime.get_btc_regime()["label"]
    except Exception:                             # noqa: BLE001
        return False
    d = trg.get("direction") or "long"
    if d == "long" and long_veto and label == btc_regime.RISK_OFF:
        return True
    if d == "short" and short_veto and label == btc_regime.RISK_ON:
        return True
    return False


def poll_once() -> dict:
    """One evaluation pass over all active triggers. Returns a summary."""
    now_iso = datetime.datetime.utcnow().isoformat()
    tdb.expire_stale(now_iso)

    active = tdb.get_triggers("active")
    if not active:
        return {"active": 0, "fired": 0, "invalidated": 0}

    symbols = sorted({t["symbol"] for t in active})
    candles = exchange.get_ohlcv_batch(symbols, timeframe="1d", limit=_CANDLE_LIMIT)

    fired = invalidated = 0
    for t in active:
        df = candles.get(t["symbol"])
        if df is None:
            continue
        ind = _indicators(df)
        if ind is None:
            continue
        verdict, reason = _evaluate(t, ind)
        if verdict == "fire" and _regime_vetoes(t):
            # Veto hooks (both default off): skip firing in the adverse regime.
            log.info("VETOED #%d %s — BTC regime veto (%s)", t["id"], t["symbol"],
                     t.get("direction"))
            continue
        if verdict == "fire":
            text = _alert_text(t, ind["price"], reason)
            delivered = telegram.send_message(text)
            # Mark fired if delivered (or Telegram is a no-op); leave active to
            # retry on a transient send failure so a real alert isn't lost.
            if delivered or not telegram.is_configured():
                tdb.mark_fired(t["id"], ind["price"], note=reason)
                fired += 1
                log.info("FIRED #%d %s — %s", t["id"], t["symbol"], reason)
            else:
                log.warning("trigger #%d met but Telegram send failed; will retry", t["id"])
        elif verdict == "invalidate":
            tdb.set_status(t["id"], "invalidated")
            invalidated += 1
            log.info("INVALIDATED #%d %s — %s", t["id"], t["symbol"], reason)

    return {"active": len(active), "fired": fired, "invalidated": invalidated}


def main() -> None:
    ap = argparse.ArgumentParser(description="QuantCore trigger monitor")
    ap.add_argument("--interval", type=int, default=180, help="poll seconds (min 60)")
    ap.add_argument("--once", action="store_true", help="single pass then exit")
    ap.add_argument("--heartbeat-telegram-hours", type=float, default=0.0,
                    help="send a 'still alive' Telegram every N hours (0 = off)")
    args = ap.parse_args()
    interval = max(args.interval, _MIN_INTERVAL)

    tdb.init_db()
    if not telegram.is_configured():
        log.warning("Telegram not configured — alerts will be logged only. "
                    "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.")

    if args.once:
        log.info("monitor: single pass — %s", poll_once())
        return

    n_active = len(tdb.get_triggers("active"))
    log.info("monitor: starting, poll every %ds, %d active triggers. Ctrl-C to stop.",
             interval, n_active)
    telegram.send_message(f"🟢 <b>Monitor started</b> — watching {n_active} armed "
                          f"trigger(s), polling every {interval}s.")
    hb_secs = args.heartbeat_telegram_hours * 3600
    last_hb = time.time()
    try:
        while True:
            try:
                s = poll_once()
                # Heartbeat: ONE line every poll, so a quiet loop is distinguishable
                # from a dead one (this is what "nothing is watching" rules out).
                log.info("poll %s UTC · %d active · %d fired · %d invalidated",
                         datetime.datetime.utcnow().strftime("%H:%M:%S"),
                         s["active"], s["fired"], s["invalidated"])
                if hb_secs and time.time() - last_hb >= hb_secs:
                    telegram.send_message(f"💓 <b>Monitor alive</b> — {s['active']} "
                                          f"active trigger(s), still watching.")
                    last_hb = time.time()
            except Exception as exc:                # noqa: BLE001 — keep the loop alive
                log.error("poll error: %s", exc)
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("monitor: stopped.")


if __name__ == "__main__":
    main()
