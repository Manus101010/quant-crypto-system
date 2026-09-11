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
    arrow = "🟢 LONG" if trg.get("direction") == "long" else "🔴 SHORT"
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
    lines.append("\n<i>Signal only — review and execute manually.</i>")
    return "\n".join(lines)


def _evaluate(trg: dict, price: float | None, rsi_now: float | None,
              rsi_prev: float | None) -> tuple[bool, str]:
    ct, cv = trg["condition_type"], trg["condition_value"]
    if ct == "price_below" and price is not None:
        return (price <= cv, f"price {_fmt_price(price)} ≤ {_fmt_price(cv)}")
    if ct == "price_above" and price is not None:
        return (price >= cv, f"price {_fmt_price(price)} ≥ {_fmt_price(cv)}")
    if ct == "rsi_cross_up" and rsi_now is not None and rsi_prev is not None:
        return (rsi_prev < cv <= rsi_now, f"RSI reclaimed {cv:.0f} ({rsi_prev:.0f}→{rsi_now:.0f})")
    if ct == "rsi_cross_down" and rsi_now is not None and rsi_prev is not None:
        return (rsi_prev > cv >= rsi_now, f"RSI broke {cv:.0f} ({rsi_prev:.0f}→{rsi_now:.0f})")
    return (False, "")


def poll_once() -> dict:
    """One evaluation pass over all active triggers. Returns a summary."""
    # Expire stale triggers first.
    now_iso = datetime.datetime.utcnow().isoformat()
    tdb.expire_stale(now_iso)

    active = tdb.get_triggers("active")
    if not active:
        return {"active": 0, "fired": 0}

    symbols = sorted({t["symbol"] for t in active})
    prices = exchange.get_last_prices(symbols)

    # Candle-based RSI only for symbols that need it.
    rsi_syms = sorted({t["symbol"] for t in active
                       if t["condition_type"].startswith("rsi_")})
    rsi_now: dict[str, float] = {}
    rsi_prev: dict[str, float] = {}
    if rsi_syms:
        candles = exchange.get_ohlcv_batch(rsi_syms, timeframe="1d", limit=_CANDLE_LIMIT)
        for s, df in candles.items():
            if len(df) >= 20:
                r = _rsi_series(df["close"]).dropna()
                if len(r) >= 2:
                    rsi_now[s], rsi_prev[s] = float(r.iloc[-1]), float(r.iloc[-2])

    fired = 0
    for t in active:
        sym = t["symbol"]
        price = prices.get(sym)
        met, reason = _evaluate(t, price, rsi_now.get(sym), rsi_prev.get(sym))
        if not met:
            continue
        px = price if price is not None else (t.get("ref_price") or 0.0)
        text = _alert_text(t, px, reason)
        delivered = telegram.send_message(text)
        # Mark fired if delivered, or if Telegram isn't configured (no-op) — but
        # NOT on a transient send failure, so a real alert can retry next poll.
        if delivered or not telegram.is_configured():
            tdb.mark_fired(t["id"], px, note=reason)
            fired += 1
            log.info("FIRED #%d %s — %s", t["id"], sym, reason)
        else:
            log.warning("trigger #%d met but Telegram send failed; will retry", t["id"])

    return {"active": len(active), "fired": fired}


def main() -> None:
    ap = argparse.ArgumentParser(description="QuantCore trigger monitor")
    ap.add_argument("--interval", type=int, default=180, help="poll seconds (min 60)")
    ap.add_argument("--once", action="store_true", help="single pass then exit")
    args = ap.parse_args()
    interval = max(args.interval, _MIN_INTERVAL)

    tdb.init_db()
    if not telegram.is_configured():
        log.warning("Telegram not configured — alerts will be logged only. "
                    "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.")

    if args.once:
        log.info("monitor: single pass — %s", poll_once())
        return

    log.info("monitor: starting, poll every %ds. Ctrl-C to stop.", interval)
    telegram.send_message("🟢 <b>Monitor started</b> — watching your armed triggers.")
    try:
        while True:
            try:
                s = poll_once()
                if s["fired"]:
                    log.info("poll: %d active, %d fired", s["active"], s["fired"])
            except Exception as exc:                # noqa: BLE001 — keep the loop alive
                log.error("poll error: %s", exc)
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("monitor: stopped.")


if __name__ == "__main__":
    main()
