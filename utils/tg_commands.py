"""
Telegram commands for the bot (read-mostly, signal-only — nothing here trades).

Only messages from TELEGRAM_CHAT_ID are answered. The monitor calls listen()
while it waits between polls, so replies come within seconds (long-polling).

  /status   gate, BTC, armed setups, open trades, money at risk
  /open     open trades with live R
  /took X   mark your open X trade as taken (counts toward the risk cap)
  /untook X undo
  /scan     run a scan & arm now
  /help
"""
from __future__ import annotations
import time

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

log = get_logger(__name__)
_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
_HELP = ("🤖 <b>Commands</b>\n/status — market gate, BTC, armed setups, risk\n"
         "/open — your open trades with live R\n/took HYPE — mark a trade as taken\n"
         "/untook HYPE — undo\n/longs off | on — switch long alerts off/on\n/scan — run a scan now\n"
         "/guard short DOODUSDT grid 0.0016 0.0025 200 5x 263.86 [sl X] [@entry] — check a grid\n"
         "/guard long BTCUSDT 65000 63000 10x 50 — check a plain trade (entry stop lev margin)\n"
         "/addbot BOTID SYMBOL — watch a Bybit grid bot · /rmbot BOTID · /bots\n"
         "/desk SOL long [entry stop] — AI desk review (veto only) · /deskstats — is the desk helping?\n"
         "/bot SOL [investment] — grid bot plan for any coin (mode, range, leverage, stop)\n"
         "<i>Signal only — the bot never trades.</i>")


def _send(text: str) -> None:
    from utils import telegram
    telegram.send_message(text)


def _status() -> str:
    from triggers import db
    from triggers.outcomes import portfolio_heat
    from utils import btc_regime
    lines = ["📊 <b>Status</b>"]
    try:
        from utils.breadth import long_gate, alt_breadth
        ok, why = long_gate()
        b = alt_breadth()
        lines.append((f"🟢 Longs allowed · {b['pct']:.0f}% of alts above 50d" if ok and b else
                      "🟢 Longs allowed" if ok else f"⛔ No new longs — {why}"))
    except Exception:                                  # noqa: BLE001
        pass
    r = btc_regime.get_btc_regime()
    lines.append(f"🧭 BTC {r['label']} — {r.get('detail', '')}")
    act = db.get_triggers("active")
    lines.append(f"📡 Armed: {len(act)}" + (" — " + ", ".join(
        f"{t['symbol'].replace('-USD', '')}{'▼' if t['direction'] == 'short' else '▲'}" for t in act[:15]) if act else ""))
    op = db.get_fired_trades(open_only=True)
    taken = [t for t in op if t.get("taken")]
    h = portfolio_heat()
    lines.append(f"📒 Open: {len(op)} tracked · {len(taken)} taken by you")
    lines.append(f"🔥 Money at risk: ${h['open_risk']:.0f} of ${h['cap']:.0f}")
    return "\n".join(lines)


def _open() -> str:
    from triggers import db
    from triggers.outcomes import open_marks
    op = db.get_fired_trades(open_only=True)
    if not op:
        return "📒 No open trades."
    mk = open_marks(op)
    rows = sorted(op, key=lambda t: (not t.get("taken"), -(mk.get(t["id"]) or 0)))
    out = ["📒 <b>Open trades</b> (✅ = you took it)"]
    for t in rows[:30]:
        r = mk.get(t["id"])
        out.append(f"{'✅' if t.get('taken') else '·'} {t['symbol'].replace('-USD', '')} "
                   f"{'▼' if t.get('direction') == 'short' else '▲'} {t.get('setup_label', '')[:22]} "
                   f"{'' if r is None else f'{r:+.2f}R'}")
    return "\n".join(out)


def _took(arg: str, taken: bool) -> str:
    from triggers import db
    sym = arg.strip().upper().replace("-USD", "")
    if not sym:
        return "Usage: /took HYPE"
    op = [t for t in db.get_fired_trades(open_only=True) if t["symbol"].replace("-USD", "") == sym]
    if not op:
        return f"No open {sym} trade to mark."
    t = sorted(op, key=lambda t: t.get("fired_at") or "")[-1]
    db.set_outcome(t["id"], {"taken": taken})
    lock_note = ""
    if taken:
        try:                     # taking a trade uses up the 1R lock after a stop out
            from guard.ledger import Ledger
            led = Ledger()
            if led.lock():
                led.issue({"symbol": t["symbol"], "type": "plain",
                           "direction": t.get("direction") or "long",
                           "stop": t.get("stop"), "trigger_id": t["id"]})
                lock_note = "\n🔒 This one is your 1R trade after the stop out: max loss $12.50."
        except Exception as exc:                         # noqa: BLE001
            log.debug("guard lock on /took failed: %s", exc)
    return (f"✅ Marked {sym} as taken — it now counts toward your risk cap.{lock_note}" if taken
            else f"↩️ {sym} unmarked.")


def _scan() -> str:
    from triggers import autoscan
    _send("🛰 Scanning now… (about a minute)")
    autoscan.run_scan("manual")                        # sends its own summary
    return ""


def handle(text: str) -> str:
    cmd, _, arg = text.strip().partition(" ")
    cmd = cmd.lower().split("@")[0]
    if cmd in ("/start", "/help"):
        return _HELP
    if cmd == "/status":
        return _status()
    if cmd == "/open":
        return _open()
    if cmd == "/took":
        return _took(arg, True)
    if cmd == "/untook":
        return _took(arg, False)
    if cmd == "/longs":
        from triggers import db
        a = arg.strip().lower()
        if a in ("off", "pause", "stop"):
            import datetime as _dt
            db.set_state("longs:paused", "1")
            db.set_state("longs:paused_at", _dt.datetime.utcnow().isoformat())
            for t in db.get_triggers("active"):
                if t["direction"] == "long":
                    db.set_status(t["id"], "cancelled")
            return "⛔ Longs paused for 24 hours — no new long alerts, armed longs cancelled. Shorts still alert. They switch back on by themselves; /longs on to resume sooner."
        if a in ("on", "resume", "start"):
            db.set_state("longs:paused", "0")
            return "🟢 Longs switched ON — the market filter decides again. Next scan will arm them if it allows."
        from utils.breadth import longs_paused_until
        until = longs_paused_until()           # clears a pause that has lapsed
        return ((f"Longs are OFF (paused by you until {until:%d %b %H:%M} UTC)." if until
                 else "Longs are ON (the market filter decides).")
                + " Use /longs off or /longs on.")
    if cmd == "/scan":
        return _scan()
    if cmd == "/guard":
        return _guard(arg)
    if cmd == "/desk":
        return _desk(arg)
    if cmd == "/bot":
        parts = arg.split()
        if not parts:
            return "Usage: /bot SOL [investment], e.g. /bot SOL 50"
        try:
            inv = float(parts[1]) if len(parts) > 1 else 50.0
        except ValueError:
            return "Investment must be a number, e.g. /bot SOL 50"
        from desk import botplan
        return botplan.text(botplan.plan(parts[0], inv))
    if cmd == "/deskstats":
        from desk.agents.store import scorecard_text
        return scorecard_text()
    if cmd in ("/addbot", "/rmbot", "/bots"):
        from guard.ledger import Ledger
        led = Ledger()
        if cmd == "/bots":
            b = led.grid_bots()
            return "\n".join(f"• {k} {v.get('symbol') or ''}" for k, v in b.items()) or "No grid bots registered."
        parts = arg.split()
        if not parts:
            return f"Usage: {cmd} BOTID" + (" SYMBOL (Bot ID is on the bot details page)" if cmd == "/addbot" else "")
        if cmd == "/addbot":
            led.add_grid_bot(parts[0], parts[1].upper() if len(parts) > 1 else None)
            return f"🤖 Watching grid bot {parts[0]}."
        return "Removed." if led.remove_grid_bot(parts[0]) else "Not registered."
    return "Unknown command. " + _HELP


def _desk(arg: str) -> str:
    """On demand desk review: /desk SOL long [entry stop]. Costs API tokens."""
    from config import ANTHROPIC_API_KEY
    parts = arg.split()
    if len(parts) < 2 or parts[1].lower() not in ("long", "short"):
        return "Usage: /desk SOL long [entry stop]  (stop needed for the guard check)"
    if not ANTHROPIC_API_KEY:
        return "Desk needs an ANTHROPIC_API_KEY (Claude API credits, separate from Claude Pro)."
    try:
        entry = float(parts[2]) if len(parts) > 2 else None
        stop = float(parts[3]) if len(parts) > 3 else None
    except ValueError:
        return "Entry and stop must be numbers, e.g. /desk SOL long 182.4 176.9"
    from desk.agents.service import review
    from desk.agents.report import telegram_text
    res = review(parts[0], parts[1].lower(), entry=entry, stop=stop, send=False)
    return telegram_text(res)


def _guard(arg: str) -> str:
    """Pre flight check of a setup against the trader's rules. Append 'issue' to
    register an accepted plan so the watcher does not tag it as unissued."""
    from guard import preflight as pf
    from guard.ledger import Ledger
    from utils import exchange
    issue = arg.strip().lower().endswith(" issue")
    if issue:
        arg = arg.strip()[:-len(" issue")]
    try:
        g = pf.parse_guard_command(arg)
    except (ValueError, IndexError) as exc:
        return f"Usage: /guard short DOODUSDT grid LO HI GRIDS 5x INVEST [sl X] [@ENTRY] [issue]\n({exc})"
    led = Ledger()
    day = led.day()
    ctx = dict(daily_realised_pnl=day["realised"], max_loss_usd=led.max_loss_for_next())
    try:
        from triggers.outcomes import portfolio_heat
        ctx["open_risk_usd"] = portfolio_heat()["open_risk"]
    except Exception:                                   # noqa: BLE001
        pass
    if g["type"] == "grid":
        entry = g["entry"]
        if entry is None:
            sym = g["symbol"].replace("USDT", "") + "-USD"
            try:
                entry = exchange.get_last_prices([sym]).get(sym)
            except Exception:                           # noqa: BLE001
                entry = None
        if not entry:
            return "No live price; add @ENTRY, e.g. @0.0021"
        from config import GUARD_SMALLCAP_MMR
        v = pf.check_grid(g["direction"], g["lo"], g["hi"], g["grids"], g["leverage"],
                          g["investment"], g["stop"], entry, mmr=GUARD_SMALLCAP_MMR, **ctx)
    else:
        v = pf.check_plain(g["direction"], g["entry"], g["stop"], g["leverage"], g["margin"], **ctx)
    txt = pf.format_verdict(v, g["symbol"])
    if ctx.get("max_loss_usd"):
        txt += f"\n🔒 1R lock active (after a stop out): this setup may lose at most ${ctx['max_loss_usd']:.2f}."
    if issue:
        if v.ok:
            led.issue(g | {"mode": g["direction"]})
            txt += "\n✅ Registered as issued: the watcher won't tag it."
        else:
            txt += "\n⛔ Not registered: fix the failed rules first."
    return txt


def listen(seconds: float) -> None:
    """Answer commands for up to `seconds` (Telegram long-polling)."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        time.sleep(seconds)
        return
    from triggers import db
    end = time.time() + seconds
    while (left := end - time.time()) > 1:
        try:
            off = int(db.get_state("tg:offset") or 0)
            r = requests.get(f"{_API}/getUpdates", timeout=min(50, left) + 10,
                             params={"offset": off, "timeout": int(min(50, left))}).json()
        except Exception as exc:                       # noqa: BLE001 — never break the loop
            log.debug("tg listen error: %s", exc)
            time.sleep(min(10, max(left, 0)))
            continue
        for u in r.get("result", []):
            db.set_state("tg:offset", str(u["update_id"] + 1))
            msg = u.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != str(TELEGRAM_CHAT_ID):
                continue                               # only answer the owner
            txt = msg.get("text") or ""
            if not txt.startswith("/"):
                continue
            try:
                reply = handle(txt)
            except Exception as exc:                   # noqa: BLE001
                reply = f"⚠️ Command failed: {exc}"
            if reply:
                _send(reply)
