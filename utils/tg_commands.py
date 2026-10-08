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
         "/untook HYPE — undo\n/scan — run a scan now\n<i>Signal only — the bot never trades.</i>")


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
    return (f"✅ Marked {sym} as taken — it now counts toward your risk cap." if taken
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
    if cmd == "/scan":
        return _scan()
    return "Unknown command. " + _HELP


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
