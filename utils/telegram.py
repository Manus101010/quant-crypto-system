"""
Telegram alert channel — one-way push notifications to the user's phone.

Signal-only guardrail: this sends messages *to* the user; it never receives
commands, executes trades, or touches any exchange account. Uses a plain
requests call to the Bot API sendMessage endpoint (no heavy dependency).

Credentials come from .env via config (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID).
If either is unset, send_message() is a graceful no-op (logs and returns False)
so the scanner/monitor run fine without Telegram configured.
"""
from __future__ import annotations
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import get_logger

log = get_logger(__name__)

_TIMEOUT = 10


def is_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_message(text: str, *, parse_mode: str = "HTML",
                 disable_preview: bool = True) -> bool:
    """
    Send a message to the configured chat. Returns True on success, False on
    a no-op (unconfigured) or failure. Never raises.
    """
    if not is_configured():
        log.info("telegram: no-op (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID unset)")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    }
    try:
        r = requests.post(url, json=payload, timeout=_TIMEOUT)
        if r.status_code != 200:
            log.warning("telegram: sendMessage %d — %s", r.status_code, r.text[:200])
            # Safety net: a stray '<'/'>' in a dynamic value can break HTML parsing
            # (400 "can't parse entities"). Never lose an alert over formatting —
            # retry once as plain text with the markup stripped.
            if r.status_code == 400 and parse_mode:
                plain = _strip_tags(text)
                r2 = requests.post(url, json={
                    "chat_id": TELEGRAM_CHAT_ID, "text": plain,
                    "disable_web_page_preview": disable_preview,
                }, timeout=_TIMEOUT)
                if r2.status_code == 200:
                    log.info("telegram: delivered as plain text after HTML parse error")
                    return True
                log.warning("telegram: plain-text retry %d — %s", r2.status_code, r2.text[:200])
            return False
        return True
    except Exception as exc:                       # noqa: BLE001 — never raise into caller
        log.warning("telegram: send failed — %s", exc)
        return False


def _strip_tags(text: str) -> str:
    """Remove the small HTML subset we use (<b>…</b> etc.) and unescape entities,
    so a message that failed HTML parsing still reads cleanly as plain text."""
    import re, html
    return html.unescape(re.sub(r"</?[a-zA-Z][^>]*>", "", text))


def send_test() -> bool:
    """Send a connectivity ping. Returns True if delivered."""
    return send_message(
        "✅ <b>QuantCore connected</b>\n"
        "Telegram alerts are wired up. You'll get scanner triggers here."
    )
