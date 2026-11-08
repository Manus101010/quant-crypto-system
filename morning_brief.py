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
    from triggers.scan import effective_deactivated
    off = effective_deactivated()
    d = [x for x in tdb.get_deactivations() if x["setup_label"] in off]
    if not d:
        return ""
    names = ", ".join(x["setup_label"] for x in d)
    return f"⛔ <b>Deactivated by decay watch:</b> {names}"


def _gate_line() -> str:
    try:
        from utils.breadth import long_gate, alt_breadth
        ok, why = long_gate()
        b = alt_breadth()
        br = f" · {b['pct']:.0f}% of alts above their 50-day" if b else ""
        return ("🟢 <b>Longs allowed</b> — BTC above its 200d &amp; 50d" + br) if ok else \
               (f"⛔ <b>No new longs</b> — {why}. Shorts still allowed.")
    except Exception:                              # noqa: BLE001
        return ""


def _week_ahead() -> str:
    """Macro releases this week + unlocks/catalysts on coins you hold or watch."""
    try:
        from utils import events
        lines = []
        mac = events.macro_events(7)
        if mac:
            lines.append("🗓 <b>This week:</b> " + "; ".join(
                f"{e['name']} — {events._when(e['date'])}" for e in mac))
        syms = sorted({t["symbol"] for t in tdb.get_fired_trades(open_only=True)}
                      | {t["symbol"] for t in tdb.get_triggers("active")}
                      | {w["symbol"] for w in tdb.get_watchlist()})
        for s_ in syms:
            w = events.coin_warning(s_, 7)
            if w:
                lines.append(f"<b>{s_.replace('-USD','')}</b> — " + w.replace("\n", " · "))
        return "\n".join(lines)
    except Exception as exc:                       # noqa: BLE001
        log.debug("week ahead failed: %s", exc)
        return ""


def _movers() -> str:
    try:
        from desk import movers
        return movers.text(movers.board())
    except Exception as exc:                       # noqa: BLE001
        log.debug("movers failed: %s", exc)
        return ""


def _date_line() -> str:
    import zoneinfo
    now = datetime.datetime.now(zoneinfo.ZoneInfo("Australia/Sydney"))
    return f"☀️ <b>{now.strftime('%a %d %b')}</b>"


def _btc_line() -> str:
    """One line: where BTC is and what that allows."""
    try:
        from utils.breadth import long_gate
        from utils.exchange import get_ohlcv
        d = get_ohlcv("BTC-USD", "1d", 60)
        px = float(d["close"].iloc[-1]) if d is not None and len(d) else None
        ok, why = long_gate()
        side = "longs and shorts allowed" if ok else f"{why}, so shorts only"
        return f"BTC {px:,.0f}: {side}." if px else f"BTC: {side}."
    except Exception:                              # noqa: BLE001
        return ""


def _new_trades() -> str:
    """Alerts that fired in the last 24h and are still open, as Pionex orders."""
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).isoformat()
    try:
        from triggers.outcomes import is_basket_capped
    except Exception:                              # noqa: BLE001
        def is_basket_capped(t):                   # noqa: E306
            return False
    rows = [t for t in tdb.get_triggers_since(cutoff)
            if t.get("status") == "fired" and t.get("outcome") is None
            and not is_basket_capped(t)]
    if not rows:
        return "<b>New trades:</b> none in the last 24 hours."
    try:
        from triggers.outcomes import planned_position
    except Exception:                              # noqa: BLE001
        planned_position = None
    out = ["<b>New trades</b> (Pionex Futures)"]
    for t in rows[:6]:
        short = t.get("direction") == "short"
        coin = t["symbol"].replace("-USD", "")
        e, st_, tp = t.get("fired_price"), t.get("stop"), t.get("tp") or t.get("target")
        line = f"{'🔴 Short' if short else '🟢 Long'} <b>{coin}</b>: entry {_fmt(e)}, stop {_fmt(st_)}"
        if tp:
            line += f", take profit {_fmt(tp)}"
        pos = planned_position(e, st_) if planned_position else None
        if pos:
            line += f", ${pos['margin']:.0f} at {pos['leverage']}x"
        out.append(line)
    out.append("Prices may have moved since the alert: skip any that ran past the entry.")
    return "\n".join(out)


def _movers_short() -> str:
    """Only the movers in a clean state; one line if there are none."""
    try:
        from desk import movers
        b = movers.board()
    except Exception as exc:                       # noqa: BLE001
        log.debug("movers failed: %s", exc)
        return ""
    keep = [r for r in b["rows"] if r["state"] not in ("CHOP", "NO DATA")]
    note = ("Reminder: shorting the day's top gainers lost in testing; they tend to keep "
            "rising for 1 to 3 days.")
    if not keep:
        return "<b>Movers:</b> nothing clean in today's top gainers and losers.\n" + note
    out = ["<b>Movers worth a look</b>"]
    for r in keep:
        icon, verdict = movers.VERDICT.get(r["state"], ("·", ""))
        out.append(f"{icon} <b>{r['base']}</b> {r['pct']:+.0f}%: {r['state'].lower()}. {verdict}")
    out.append(note)
    return "\n".join(out)


def _results_line() -> str:
    """Win rate and average R per trade. Never dollar totals."""
    try:
        from triggers import outcomes
        parts = []
        for name, taken in (("Your trades", True), ("All alerts", False)):
            t = outcomes.live_stats(taken_only=taken)["total"]
            if t["n"]:
                parts.append(f"{name}: {t['n']} closed, {t['win_rate'] * 100:.0f}% won, "
                             f"{t['total_r'] / t['n']:+.2f}R per trade")
        return ("<b>Results</b>\n" + "\n".join(parts)) if parts else ""
    except Exception:                              # noqa: BLE001
        return ""


def _week_short() -> str:
    try:
        from utils import events
        mac = events.macro_events(7)
        if not mac:
            return ""
        return "<b>This week:</b> " + "; ".join(f"{e['name']} {events._when(e['date'])}" for e in mac)
    except Exception:                              # noqa: BLE001
        return ""


def _universe_warning() -> str:
    """The scanner's saved Pionex coin list goes stale: say so after 21 days."""
    try:
        import json
        from config import ROOT_DIR
        d = json.loads((ROOT_DIR / "data" / "pionex_perps.json").read_text())
        age = (datetime.date.today() - datetime.date.fromisoformat(d["updated"])).days
        if age > 21:
            return (f"⚠️ The Pionex coin list is {age} days old; new listings are being missed. "
                    "Ask Claude to refresh it.")
    except Exception:                              # noqa: BLE001
        return "⚠️ The saved Pionex coin list is missing; ask Claude to fix it."
    return ""


def build_brief() -> str:
    """6 Nov 2026 rewrite: short, plain, Pionex first. No dollar results, no command
    list, no internal state (deactivated setups, deployment score)."""
    tdb.init_db()
    parts = [_date_line(), _btc_line(), _new_trades(), _movers_short(),
             _results_line(), _week_short(), _universe_warning(),
             "<i>/help lists the commands.</i>"]
    return "\n\n".join(p for p in parts if p)


# Daily reminder of the Telegram commands (he won't remember them otherwise).
COMMANDS_CHEATSHEET = (
    "📋 <b>Commands</b>\n"
    "<code>/status</code> market, BTC, armed setups, risk\n"
    "<code>/open</code> your open trades with live R\n"
    "<code>/took SOL</code> mark a trade taken (<code>/untook SOL</code> undo)\n"
    "<code>/scan</code> run a scan now · <code>/longs off</code> or <code>on</code>\n"
    "<code>/guard long SOL 182.4 176.9 7x 50</code> check a plain trade (entry stop lev margin)\n"
    "<code>/guard short DOODUSDT grid 0.0016 0.00221 200 3x 263.86 sl 0.002221</code> check a grid\n"
    "<code>/addbot BOTID DOOD</code> watch a grid bot · <code>/bots</code> list\n"
    "<code>/movers</code> top gainers and losers, sorted into states with scores\n"
    "<code>/bot SOL 50</code> grid bot plan for any coin: mode, range, leverage, stop\n"
    "<code>/desk SOL long 182.4 176.9</code> AI desk review · <code>/deskstats</code> is it helping\n"
    "<code>/help</code> full list"
)


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
