#!/usr/bin/env python3
"""
Morning Brief — the scheduled one-page daily read (prompt #10, done reliably).

Runs UNATTENDED on a schedule, so it is built entirely on the code/ccxt path —
it never depends on TradingView being open (a CDP connection would fail most
mornings). Off the monitor hot path: a standalone job like revalidate.py.

Assembles, into one Telegram message:
  • BTC regime + macro deployment score (the backdrop)
  • Overnight trigger activity (fired / invalidated / expired in the last 24h)
  • What's still armed and being watched
  • Your watchlist — price, 24h, position in the 20-day range, and a flag when a
    coin is within ~3% of its range high/low
  • Any setups the weekly revalidation auto-deactivated

Signal-only, ccxt read-only, free data. Nothing here arms or places anything.

Usage:
    ./venv/bin/python morning_brief.py            # build + send
    ./venv/bin/python morning_brief.py --dry-run  # print, don't send
"""
from __future__ import annotations
import argparse
import datetime

from triggers import db as tdb
from utils import telegram
from utils.logger import get_logger

log = get_logger("morning_brief")

_NEAR_LEVEL_PCT = 3.0        # flag a watchlist coin within this % of its range hi/lo


def _fmt(v) -> str:
    if v is None:
        return "—"
    v = float(v)
    if v == 0:    return "—"
    if v < 0.01:  return f"${v:,.6f}"
    if v < 1:     return f"${v:,.4f}"
    if v < 100:   return f"${v:,.2f}"
    return f"${v:,.0f}"


def _regime_line() -> str:
    try:
        from utils import btc_regime
        r = btc_regime.get_btc_regime()
        line = f"🧭 <b>BTC {r['label']}</b> — {r.get('detail','')}"
    except Exception as exc:                       # noqa: BLE001
        line = f"🧭 BTC regime unavailable ({exc})"
    try:
        from signals.aggregator import run_all
        m = run_all()
        line += f"\n📊 Deployment score <b>{m['deployment_score']:.0f}</b> — {m['regime']}"
    except Exception as exc:                        # noqa: BLE001
        line += f"\n📊 Macro score unavailable ({exc})"
    return line


def _overnight() -> str:
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).isoformat()
    changed = tdb.get_triggers_since(cutoff)
    if not changed:
        return "😴 <b>Overnight:</b> no triggers fired or invalidated."
    by = {}
    for t in changed:
        by.setdefault(t["status"], []).append(t)
    lines = ["🔔 <b>Overnight trigger activity:</b>"]
    for status in ("fired", "invalidated", "expired"):
        rows = by.get(status, [])
        for t in rows[:6]:
            arrow = "🟢" if t["direction"] == "long" else "🔴"
            lines.append(f"• {arrow} <b>{t['symbol']}</b> {t.get('setup_label','')} — {status}")
    return "\n".join(lines)


def _active() -> str:
    active = tdb.get_triggers("active")
    if not active:
        return "👁 <b>Watching:</b> nothing armed right now."
    head = f"👁 <b>Watching {len(active)} trigger(s):</b>"
    tops = ", ".join(f"{t['symbol']} ({t['direction'][0].upper()})" for t in active[:8])
    return f"{head} {tops}"


def _watchlist() -> str:
    wl = tdb.get_watchlist()
    if not wl:
        return ("⭐ <b>Watchlist:</b> empty — add coins in the Trade Desk to get a daily "
                "read on them here.")
    from utils.exchange import get_ohlcv
    from desk import analysis as A
    lines = ["⭐ <b>Watchlist:</b>"]
    for w in wl:
        sym = w["symbol"]
        df = get_ohlcv(sym, "1d", 400)
        if df is None or df.empty:
            lines.append(f"• {sym} — no data")
            continue
        s = A.structure(df)
        price = s["price"]
        h1 = get_ohlcv(sym, "1h", 30)
        chg = ((price / float(h1['close'].iloc[-25]) - 1) * 100
               if h1 is not None and len(h1) >= 25 else None)
        hi, lo = s.get("range_hi20"), s.get("range_lo20")
        flag = ""
        if hi and price >= hi * (1 - _NEAR_LEVEL_PCT / 100):
            flag = " ⚠️ near 20-day HIGH"
        elif lo and price <= lo * (1 + _NEAR_LEVEL_PCT / 100):
            flag = " ⚠️ near 20-day LOW"
        chg_txt = f"{chg:+.1f}% 24h" if chg is not None else ""
        lines.append(f"• <b>{sym}</b> {_fmt(price)} {chg_txt}{flag}")
    return "\n".join(lines)


def _decay() -> str:
    d = tdb.get_deactivations()
    if not d:
        return ""
    names = ", ".join(x["setup_label"] for x in d)
    return f"⛔ <b>Deactivated by decay watch:</b> {names}"


def _track_record() -> str:
    """Live results of fired signals, and any setup lagging its backtest."""
    try:
        from triggers import outcomes
        ls = outcomes.live_stats()
    except Exception:                              # noqa: BLE001
        return ""
    t = ls["total"]
    if not t["n"] and not ls["open"]:
        return ""
    line = f"📒 <b>Live record:</b> {t['n']} closed"
    if t["n"]:
        line += f", {t['win_rate']*100:.0f}% win, {t['total_r']:+.2f}R total"
    line += f" · {len(ls['open'])} open"
    lag = [r["setup"] for r in ls["by_setup"] if r["verdict"] in ("lagging backtest", "no edge live")]
    if lag:
        line += "\n⚠️ Underperforming live: " + ", ".join(lag)
    return line


def build_brief() -> str:
    tdb.init_db()
    today = datetime.datetime.utcnow().strftime("%a %d %b %Y")
    parts = [f"☀️ <b>Morning Brief — {today} UTC</b>",
             _regime_line(), _overnight(), _active(), _watchlist()]
    rec = _track_record()
    if rec:
        parts.append(rec)
    decay = _decay()
    if decay:
        parts.append(decay)
    parts.append("<i>Signal only — a read, not a trade. You execute manually.</i>")
    return "\n\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Morning Brief (scheduled, off the hot path)")
    ap.add_argument("--dry-run", action="store_true", help="print instead of sending")
    args = ap.parse_args()
    text = build_brief()
    if args.dry_run:
        print(text)
        return
    ok = telegram.send_message(text)
    log.info("morning_brief sent=%s", ok)


if __name__ == "__main__":
    main()
