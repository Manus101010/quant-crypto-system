"""
Watcher: read only Bybit account monitor with Telegram alerts. Signal only.

One poll reads the wallet, linear USDT positions, configured futures grid bots
(BYBIT_GRID_BOT_IDS) and today's closed P&L, then computes per position the liq
distance, stop distance, distance to grid edges, unrealised P&L, open risk and
today's realised P&L (Sydney day). Alerts (each sent once until it clears):

  * liq distance < 2x stop distance, or < 15%
  * price within 10% of a grid edge
  * a position or grid has no stop
  * daily realised loss cap ($125) hit
  * an unissued position/bot appears (revenge tag)
  * BTC regime flips (utils/btc_regime.py)

Summaries at 07:00, 15:30 and 21:30 Australia/Sydney.

  python watcher.py --once                       # one poll (live keys)
  python watcher.py --loop --interval 60         # poll every 60 s
  python watcher.py --once --dry-run             # fixture, prints, no Telegram, no keys
  python watcher.py --once --dry-run --fixture path.json --summary
"""
from __future__ import annotations
import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from guard import preflight as pf
from guard.ledger import Ledger, SYD, norm_symbol, sydney_day, sydney_day_start_ms
from utils.logger import get_logger

log = get_logger("watcher")

ROOT = Path(__file__).parent
DEFAULT_FIXTURE = ROOT / "guard" / "fixtures" / "dood_live.json"
LIQ_MIN_PCT = 15.0
EDGE_WARN_PCT = 10.0
SUMMARY_SLOTS = ("07:00", "15:30", "21:30")


def _f(x, default: float = 0.0) -> float:
    try:
        return float(x) if x not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _px(x: float) -> str:
    if not x or not math.isfinite(x):
        return "n/a"
    return f"{x:.8g}"


# ── snapshot ───────────────────────────────────────────────────────────────────
def load_snapshot(fixture: str | Path | None = None, client=None,
                  bot_ids: list[str] | None = None) -> dict:
    """Raw account data, from a fixture (dry run) or the read only Bybit client.
    The only I/O step: everything after it (poll and below) is pure functions over this
    JSON plus injected state/send callables, so the same logic can be ported to another
    runtime (e.g. a Supabase Edge Function) that fetches the same four payloads."""
    if fixture:
        return json.loads(Path(fixture).read_text())
    from utils.bybit_account import BybitAccount
    c = client or BybitAccount()
    grids = c.futures_grid_bots(bot_ids)
    return {"wallet": c.wallet_balance("UNIFIED"),
            "positions": c.positions("linear", "USDT"),
            "grids": grids,
            "grid_errors": list(getattr(c, "grid_errors", []) or []),
            "closed_pnl": c.closed_pnl("linear", start_ms=sydney_day_start_ms())}


def normalise(snap: dict, grid_symbols: set[str] | None = None) -> list[dict]:
    """Positions + grid bots as uniform dicts. A linear position on a symbol with a
    running/registered grid bot is GRID OWNED: kept (kind "grid_position", so its
    liq/no stop checks still run if the bot detail failed) but never revenge tagged,
    and skipped entirely when the bot itself was read (the bot reports it).
    `grid_symbols`: symbols of registered bots (from the ledger registry), used when
    detail could not be fetched."""
    items: list[dict] = []
    grid_syms: set[str] = set()
    reg_syms = {norm_symbol(x) for x in (grid_symbols or set()) if x}
    for g in snap.get("grids") or []:
        if str(g.get("status", "RUNNING")).upper() not in ("RUNNING", "NEW", ""):
            continue
        mode = "short" if "SHORT" in str(g.get("grid_mode", "")).upper() else (
            "long" if "LONG" in str(g.get("grid_mode", "")).upper() else
            ("short" if _f(g.get("current_position")) < 0 else "long"))
        sym = norm_symbol(g["symbol"])
        grid_syms.add(sym)
        items.append({
            "kind": "grid", "id": g.get("bot_id"), "symbol": sym, "side": mode,
            "lo": _f(g.get("min_price")), "hi": _f(g.get("max_price")),
            "grids": int(_f(g.get("cell_number"))), "leverage": _f(g.get("leverage")),
            "margin": _f(g.get("total_investment")), "entry": _f(g.get("entry_price")),
            "mark": _f(g.get("mark_price")) or _f(g.get("last_price")),
            "liq": _f(g.get("liquidation_price")), "stop": _f(g.get("stop_loss_price")) or None,
            "qty": _f(g.get("current_position")), "upnl": _f(g.get("unrealised_pnl")),
            "tick": _f(g.get("tick_size")) or None, "mmr": _f(g.get("m_m_rate")) or None,
        })
    for p in snap.get("positions") or []:
        sym = norm_symbol(p["symbol"])
        if sym in grid_syms:
            continue                                   # the bot entry already covers it
        side = "short" if str(p.get("side")).lower() in ("sell", "short") else "long"
        items.append({
            "kind": "grid_position" if sym in reg_syms else "position",
            "id": f"{sym}:{side}", "symbol": sym, "side": side,
            "entry": _f(p.get("avgPrice")), "mark": _f(p.get("markPrice")),
            "liq": _f(p.get("liqPrice")), "stop": _f(p.get("stopLoss")) or None,
            "qty": _f(p.get("size")), "upnl": _f(p.get("unrealisedPnl")),
            "margin": _f(p.get("positionIM")) or _f(p.get("positionBalance")),
            "leverage": _f(p.get("leverage")),
        })
    return items


# ── metrics ────────────────────────────────────────────────────────────────────
def metrics(it: dict) -> dict:
    """Distances (% of mark) and $ risk at stop for one item. Without a stop the whole
    margin counts as open risk (that's what a liquidation costs)."""
    mark, entry, liq, stop = it["mark"], it["entry"], it["liq"], it.get("stop")
    short = it["side"] == "short"
    m = {"liq_dist_pct": abs(liq - mark) / mark * 100 if liq and mark else math.inf}
    m["stop_dist_pct"] = abs(stop - mark) / mark * 100 if stop and mark else None
    if it["kind"] == "grid":
        lo, hi = it["lo"], it["hi"]
        m["dist_top_pct"] = (hi - mark) / mark * 100
        m["dist_bottom_pct"] = (mark - lo) / mark * 100
        mmr = it.get("mmr") or (pf.implied_mmr(it["side"], abs(it["qty"]), entry, it["margin"], liq)
                                if liq and it["qty"] else pf.DEFAULT_MMR)
        dr = pf.infer_deploy_ratio(it["side"], lo, hi, it["grids"], entry, it["margin"],
                                   it["leverage"], it["qty"], mark=mark) or 1.0
        # Launch price as entry: loss measured against the investment, like the 25% rule.
        v = pf.check_grid(it["side"], lo, hi, it["grids"], it["leverage"], it["margin"], stop,
                          entry or mark, deploy_ratio=dr, mmr=max(mmr, 0.0), tick=it.get("tick"),
                          live_liq=liq or None)
        m["verdict"] = v
        m["worst_loss"] = v.metrics["loss_at_stop"]
        m["risk_usd"] = v.metrics["loss_at_stop"] if stop else it["margin"]
    else:
        q = abs(it["qty"])
        if stop:
            m["risk_usd"] = max(0.0, q * ((stop - entry) if short else (entry - stop)))
        else:
            m["risk_usd"] = it["margin"]
    return m


def evaluate(items: list[dict]) -> list[dict]:
    """Alert dicts {key, text} for the current state (dedupe happens in poll())."""
    out = []
    for it in items:
        m = it["m"]
        tag = f"{it['symbol']} {it['side']} {'grid' if it['kind'] == 'grid' else 'grid position' if it['kind'] == 'grid_position' else ''}".strip()
        if not it.get("stop"):
            extra = ""
            if it["kind"] == "grid":
                sl = (pf.round_tick(it["hi"] * 1.005, it.get("tick"), "up") if it["side"] == "short"
                      else pf.round_tick(it["lo"] * 0.995, it.get("tick"), "down"))
                extra = (f" Bybit needs the SL {'at or above the range top' if it['side'] == 'short' else 'at or below the range bottom'}"
                         f" ({_px(sl)}); worst case at that stop ${m['worst_loss']:.2f}.")
            out.append({"key": f"nostop:{it['id']}",
                        "text": f"🚨 <b>No stop</b> on {tag}. Margin at risk ${it['margin']:.2f}.{extra}"})
        ld, sd = m["liq_dist_pct"], m.get("stop_dist_pct")
        if ld < LIQ_MIN_PCT or (sd and ld < 2 * sd):
            why = f"liq {ld:.1f}% away" + (f" vs stop {sd:.1f}% (need 2x)" if sd else "")
            out.append({"key": f"liq:{it['id']}",
                        "text": f"⚠️ <b>Liquidation close</b> {tag}: {why}. Mark {_px(it['mark'])}, liq {_px(it['liq'])}."})
        if it["kind"] == "grid":
            if 0 <= m["dist_top_pct"] < EDGE_WARN_PCT or m["dist_top_pct"] < 0:
                out.append({"key": f"edgetop:{it['id']}",
                            "text": f"📈 {tag}: price {_px(it['mark'])} is {m['dist_top_pct']:.1f}% from the range TOP {_px(it['hi'])}"
                                    + (" (short grid fully loaded above here)" if it["side"] == "short" else " (out of range above)")})
            if 0 <= m["dist_bottom_pct"] < EDGE_WARN_PCT or m["dist_bottom_pct"] < 0:
                out.append({"key": f"edgebot:{it['id']}",
                            "text": f"📉 {tag}: price {_px(it['mark'])} is {m['dist_bottom_pct']:.1f}% from the range BOTTOM {_px(it['lo'])}"
                                    + (" (long grid fully loaded below here)" if it["side"] == "long" else " (grid runs out of range below)")})
    return out


# ── state helpers ──────────────────────────────────────────────────────────────
class MemState:
    """In memory app_state for dry runs and tests."""

    def __init__(self) -> None:
        self.d: dict[str, str] = {}

    def get(self, k: str) -> str | None:
        return self.d.get(k)

    def set(self, k: str, v: str) -> None:
        self.d[k] = v


def due_summary(now: datetime, sent: set[str]) -> str | None:
    """The latest summary slot that has passed today (Sydney) and wasn't sent yet."""
    local = now.astimezone(SYD)
    hm = local.strftime("%H:%M")
    due = [s for s in SUMMARY_SLOTS if s <= hm]
    if not due:
        return None
    slot = f"{local:%Y-%m-%d} {due[-1]}"
    return None if slot in sent else slot


def summary_text(items: list[dict], wallet: dict, day: dict, open_risk: float,
                 regime: dict | None, unissued: dict) -> str:
    lines = [f"🛡 <b>Guard summary</b> {datetime.now(SYD):%a %H:%M} Sydney"]
    if wallet:
        lines.append(f"Equity ${_f(wallet.get('totalEquity')):.2f} · available "
                     f"${_f(wallet.get('totalAvailableBalance')):.2f}")
    lines.append(f"Realised today ${day['realised']:+.2f} (unissued ${day['realised_unissued']:+.2f})"
                 f" · cap -${pf.DAILY_LOSS_CAP:.0f}")
    lines.append(f"Open risk ${open_risk:.2f} of ${pf.OPEN_RISK_CAP:.0f}")
    for it in items:
        m = it["m"]
        stop_txt = "none" if not it.get("stop") else f"{m['stop_dist_pct']:.1f}%"
        s = (f"• {it['symbol']} {it['side']}{' grid' if it['kind'] == 'grid' else ''} "
             f"uPnL ${it['upnl']:+.2f} · liq {m['liq_dist_pct']:.1f}% away · stop {stop_txt}")
        if it["kind"] == "grid":
            s += f" · top {m['dist_top_pct']:.1f}% / bottom {m['dist_bottom_pct']:.1f}%"
        if it.get("unissued"):
            s += " · UNISSUED"
        lines.append(s)
    if not items:
        lines.append("No open positions or grid bots.")
    if regime:
        lines.append(f"🧭 BTC {regime.get('label')}")
    return "\n".join(lines)


# ── one poll ───────────────────────────────────────────────────────────────────
def poll(snap: dict, *, ledger: Ledger, state_get, state_set, send, regime: dict | None,
         now: datetime | None = None, force_summary: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    reg = ledger.grid_bots()
    items = normalise(snap, {v.get("symbol") for v in reg.values() if v.get("symbol")})
    for it in items:
        it["m"] = metrics(it)
    day = ledger.apply_closed(snap.get("closed_pnl") or [], now)
    # Grid owned positions are never "unissued" on their own; the bot entry is what counts.
    new_unissued = ledger.tag_unissued([i for i in items if i["kind"] != "grid_position"], now)
    tags = ledger.unissued()
    for it in items:
        it["unissued"] = f"{it['kind']}:{it['symbol']}:{it['side']}" in tags
    open_risk = round(sum(it["m"]["risk_usd"] for it in items), 2)

    alerts = evaluate(items)
    for it in new_unissued:
        alerts.append({"key": f"unissued:{it['kind']}:{it['symbol']}:{it['side']}",
                       "text": f"🩸 <b>Unissued</b> {it['symbol']} {it['side']} {it['kind']} "
                               f"(margin ${it.get('margin', 0):.2f}). The guard didn't issue this: "
                               "tagged as revenge, P&L tracked separately. Next issued setup is 1R."})
    if new_unissued and not ledger.lock():
        ledger.record_stopout(new_unissued[0]["symbol"], 0.0, now)   # revenge => 1R lock
    if day["realised"] <= -pf.DAILY_LOSS_CAP and ledger.mark_cap_hit(now):
        alerts.append({"key": f"cap:{day['day']}",
                       "text": f"🛑 <b>Daily loss cap hit</b>: realised ${day['realised']:.2f} today. "
                               "Guard is shut until midnight Sydney. No new setups will be issued."})
    for e in snap.get("grid_errors") or []:
        hint = (" The API key may lack bot read permission: in Bybit API management enable "
                "read access for bots/Copy trading (still Read-Only, no trade)."
                if e.get("kind") == "permission" else "")
        alerts.append({"key": f"griderr:{e.get('bot_id')}:{e.get('kind')}",
                       "text": f"⚠️ Couldn't read grid bot {e.get('bot_id')}: {e.get('error')}.{hint} "
                               "Its position is still watched as a plain position."})
    if open_risk > pf.OPEN_RISK_CAP:
        alerts.append({"key": "openrisk",
                       "text": f"🔥 Open risk ${open_risk:.2f} > ${pf.OPEN_RISK_CAP:.0f} cap."})
    if regime and regime.get("label"):
        prev = state_get("guard:btc_regime")
        if prev and prev != regime["label"]:
            alerts.append({"key": f"regime:{regime['label']}:{now:%Y%m%d%H}",
                           "text": f"🧭 <b>BTC regime flip</b>: {prev} → {regime['label']}. {regime.get('detail', '')}"})
        state_set("guard:btc_regime", regime["label"])

    # Dedupe: send an alert only when it becomes active; forget it once it clears.
    active_prev = set(json.loads(state_get("guard:alerts") or "[]"))
    keys_now = {a["key"] for a in alerts}
    sent = []
    for a in alerts:
        if a["key"] not in active_prev:
            send(a["text"])
            sent.append(a["key"])
    state_set("guard:alerts", json.dumps(sorted(keys_now)))

    done = set(json.loads(state_get("guard:summaries") or "[]"))
    slot = due_summary(now, done)
    summary = None
    if slot or force_summary:
        summary = summary_text(items, snap.get("wallet") or {}, day, open_risk, regime, tags)
        send(summary)
        if slot:
            done.add(slot)
            state_set("guard:summaries", json.dumps(sorted(done)[-12:]))
    return {"items": items, "alerts": alerts, "sent": sent, "day": day,
            "open_risk": open_risk, "summary": summary}


def _regime(snap: dict, dry: bool) -> dict | None:
    if dry:
        return snap.get("btc_regime")
    try:
        from utils import btc_regime
        return btc_regime.get_btc_regime()
    except Exception as exc:                        # noqa: BLE001
        log.warning("regime unavailable: %s", exc)
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read only Bybit watcher (signal only)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--once", action="store_true", help="one poll then exit (default)")
    g.add_argument("--loop", action="store_true", help="poll forever")
    ap.add_argument("--interval", type=int, default=60, help="seconds between polls")
    ap.add_argument("--max-minutes", type=float, default=0, help="stop the loop after N minutes")
    ap.add_argument("--dry-run", action="store_true", help="use a fixture, print, no Telegram")
    ap.add_argument("--fixture", default=None, help="fixture JSON (implies --dry-run)")
    ap.add_argument("--summary", action="store_true", help="send a summary now")
    a = ap.parse_args(argv)
    dry = a.dry_run or bool(a.fixture)
    fixture = a.fixture or (DEFAULT_FIXTURE if dry else None)

    if dry:
        mem = MemState()
        ledger = Ledger(mem.get, mem.set)
        sget, sset = mem.get, mem.set

        def send(text: str) -> None:
            print("\n" + "-" * 60 + "\n" + text)
    else:
        from triggers import db
        from utils import telegram
        ledger = Ledger()
        sget, sset = db.get_state, db.set_state

        def send(text: str) -> None:
            if not telegram.send_message(text):
                print(text)

    end = time.time() + a.max_minutes * 60 if a.max_minutes else None
    while True:
        try:
            env_ids = [x.strip() for x in os.getenv("BYBIT_GRID_BOT_IDS", "").split(",") if x.strip()]
            snap = load_snapshot(fixture, bot_ids=None if dry else ledger.grid_bot_ids(env_ids))
            res = poll(snap, ledger=ledger, state_get=sget, state_set=sset, send=send,
                       regime=_regime(snap, dry), force_summary=a.summary)
            log.info("poll: %d items, %d alerts (%d new), open risk $%.2f, realised $%.2f",
                     len(res["items"]), len(res["alerts"]), len(res["sent"]),
                     res["open_risk"], res["day"]["realised"])
            a.summary = False
        except Exception as exc:                    # noqa: BLE001 — keep the loop alive
            from utils.bybit_account import BybitGeoBlocked, BybitAuthMissing
            log.error("poll failed: %s", exc)
            if isinstance(exc, (BybitGeoBlocked, BybitAuthMissing)):
                if not dry:
                    send(f"⚠️ Watcher stopped: {exc}")
                return 2
        if not a.loop or (end and time.time() >= end):
            return 0
        time.sleep(max(5, a.interval))


if __name__ == "__main__":
    raise SystemExit(main())
