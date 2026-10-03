"""
Scheduled Scan & Arm — the cloud monitor calls `run_due()` every loop.

Runs a full scan at the local times in config.AUTO_SCAN_SCHEDULE (Sydney times
follow daylight saving automatically), arms the best setups exactly like the
"Run Scan & Arm" button, and pushes a Telegram summary. The last run per slot
is stored in app_state so a relay restart never repeats or skips a scan; a slot
missed by more than CATCH_UP_MIN is skipped rather than run stale.

Signal-only: arming creates alerts; nothing is ever traded.
"""
from __future__ import annotations
import datetime as _dt
from zoneinfo import ZoneInfo
from config import AUTO_SCAN_SCHEDULE, AUTO_SCAN_PARAMS
from triggers import db as tdb
from utils import telegram
from utils.logger import get_logger

log = get_logger(__name__)
CATCH_UP_MIN = 90
_APP_URL = "https://quantcore.streamlit.app/scanner"


def _slot_time(tz: str, hhmm: str, now_utc: _dt.datetime) -> _dt.datetime:
    """Most recent occurrence (UTC) of local hh:mm at or before now."""
    z = ZoneInfo(tz)
    local_now = now_utc.astimezone(z)
    h, m = map(int, hhmm.split(":"))
    t = local_now.replace(hour=h, minute=m, second=0, microsecond=0)
    if t > local_now:
        t -= _dt.timedelta(days=1)
    return t.astimezone(_dt.timezone.utc)


def due(now_utc: _dt.datetime | None = None) -> list[tuple[str, _dt.datetime]]:
    now_utc = now_utc or _dt.datetime.now(_dt.timezone.utc)
    out = []
    for name, tz, hhmm in AUTO_SCAN_SCHEDULE:
        slot = _slot_time(tz, hhmm, now_utc)
        if now_utc - slot > _dt.timedelta(minutes=CATCH_UP_MIN):
            continue                                  # too late — don't run stale
        last = tdb.get_state(f"autoscan:{name}")
        if last and last >= slot.isoformat():
            continue                                  # already ran this slot
        out.append((name, slot))
    return out


def seconds_to_next(now_utc: _dt.datetime | None = None) -> float:
    """Seconds until the next scheduled slot (lets the monitor wake on time)."""
    now_utc = now_utc or _dt.datetime.now(_dt.timezone.utc)
    from config import BRIEF_SCHEDULE
    slots = [(tz, hhmm) for _, tz, hhmm in AUTO_SCAN_SCHEDULE] + [BRIEF_SCHEDULE]
    nxt = min(_slot_time(tz, hhmm, now_utc) + _dt.timedelta(days=1) for tz, hhmm in slots)
    return max(0.0, (nxt - now_utc).total_seconds())


def _regime_score():
    try:
        from signals.aggregator import run_all
        return run_all().get("deployment_score")
    except Exception as exc:                          # noqa: BLE001
        log.warning("autoscan: macro score unavailable — %s", exc)
        return None


def _fmt(p):
    if p is None:
        return "—"
    return f"${p:,.2f}" if p >= 100 else (f"${p:.4f}" if p >= 0.01 else f"${p:.8f}".rstrip("0"))


def summary(name: str, res: dict, regime_score) -> str:
    _n = _dt.datetime.now(ZoneInfo("Australia/Sydney"))
    syd = _n.strftime("%a ") + _n.strftime("%-I:%M%p").lower()
    label = {"morning": "Morning scan", "close": "Daily-close scan", "arvo": "Afternoon scan"}.get(name, "Scan")
    lines = [f"🛰 <b>{label}</b> — {syd} Sydney"]
    try:
        from utils import btc_regime
        r = btc_regime.get_btc_regime()
        lines.append(f"🧭 BTC {r['label']}" + (f" · deployment {regime_score:.0f}" if regime_score else ""))
    except Exception:                                 # noqa: BLE001
        pass
    if res.get("regime_blocked"):
        lines.append(f"⛔ Risk-off (deployment {res.get('regime_score', 0):.0f}) — nothing armed; "
                     "existing triggers kept.")
    if res.get("btc_below_200d"):
        lines.append(f"⛔ No new longs: {res.get('long_gate_reason') or 'market trend is down'}. "
                     "Shorts still allowed. (Full-cycle backtest: this filter cut the worst "
                     "drawdown by ~44%.)")
    armed = res.get("armed") or []
    lines.append(f"\n<b>{res.get('actionable', 0)} valid setups → {len(armed)} armed</b>")
    for a in armed:
        arrow = "▲" if a["direction"] == "long" else "▼"
        lvl = a.get("level")
        how = "trailing stop" if a.get("trailing") else "take-profit at 3× risk"
        fire = (f"alerts if price goes {'above' if a['direction']=='long' else 'below'} {_fmt(lvl)}"
                if a.get("category") != "mean_reversion" else "alerts when the dip turns up")
        sp = a.get("stop_pct")
        lines.append(f"📡 {arrow} <b>{a['symbol'].replace('-USD','')}</b> {a['setup_label']} — "
                     f"{fire} · stop {sp:.0f}% below · {how}" if sp else
                     f"📡 {arrow} <b>{a['symbol'].replace('-USD','')}</b> {a['setup_label']} — {fire}")
    try:
        from utils import events
        flagged = [f"{a['symbol'].replace('-USD','')}: {events.coin_warning(a['symbol'], 7).splitlines()[0]}"
                   for a in armed if events.coin_warning(a["symbol"], 7)]
        if flagged:
            lines.append("\n⚠️ <b>Event risk on armed coins</b>\n" + "\n".join(flagged))
        mw = events.macro_warning(3)
        if mw:
            lines.append(mw)
    except Exception as exc:                          # noqa: BLE001
        log.debug("autoscan events failed: %s", exc)
    hs = res.get("held_status") or {}
    if hs:
        gone = [s.replace('-USD', '') for s, v in hs.items() if v["verdict"] == "gone"]
        ok = sum(1 for v in hs.values() if v["verdict"] == "valid")
        lines.append(f"\n📌 Open trades: {ok} ✅ still valid"
                     + (f" · ⚠️ setup gone: {', '.join(gone)}" if gone else ""))
    skipped = []
    if res.get("wide_stop_excluded"):
        skipped.append(f"{len(res['wide_stop_excluded'])} stop too wide")
    if res.get("crowded_excluded"):
        skipped.append(f"{len(res['crowded_excluded'])} crowded")
    if skipped:
        lines.append("🛡️ Skipped: " + " · ".join(skipped))
    lines.append(f"\n<a href='{_APP_URL}'>Open scanner</a> · <i>Signal only — you execute.</i>")
    return "\n".join(lines)


def run_scan(name: str) -> dict:
    from triggers.scan import run_scan_and_arm
    p = AUTO_SCAN_PARAMS
    score = _regime_score()
    res = run_scan_and_arm(universe_size=100, top_n=p["top_n"], regime_score=score,
                           expiry_hours=p["expiry_hours"], min_vol_usd_m=p["min_vol_usd_m"],
                           source=p["source"], max_per_setup=max(2, p["top_n"] // 3),
                           max_stop_pct=p["max_stop_pct"])
    telegram.send_message(summary(name, res, score))
    return res


def _brief_due(now_utc=None):
    from config import BRIEF_SCHEDULE
    now_utc = now_utc or _dt.datetime.now(_dt.timezone.utc)
    slot = _slot_time(BRIEF_SCHEDULE[0], BRIEF_SCHEDULE[1], now_utc)
    if now_utc - slot > _dt.timedelta(minutes=CATCH_UP_MIN):
        return None
    last = tdb.get_state("brief:daily")
    return None if (last and last >= slot.isoformat()) else slot


def run_due() -> list[str]:
    """Run every scan slot (and the morning brief) that's due now."""
    ran = []
    slot = _brief_due()
    if slot:
        tdb.set_state("brief:daily", slot.isoformat())
        try:
            import morning_brief
            telegram.send_message(morning_brief.build_brief())
            ran.append("brief")
        except Exception as exc:                      # noqa: BLE001
            log.error("brief failed — %s", exc)
    for name, slot in due():
        # Mark first so a crash mid-scan can't loop-retry a heavy scan every poll.
        tdb.set_state(f"autoscan:{name}", slot.isoformat())
        log.info("autoscan: running %s (slot %s)", name, slot.isoformat())
        try:
            res = run_scan(name)
            log.info("autoscan: %s armed %d of %d", name, len(res.get("armed") or []),
                     res.get("actionable", 0))
            ran.append(name)
        except Exception as exc:                      # noqa: BLE001
            log.error("autoscan: %s failed — %s", name, exc)
            telegram.send_message(f"⚠️ Auto-scan ({name}) failed: {exc}")
    return ran
