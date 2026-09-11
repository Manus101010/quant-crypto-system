"""
Outbound webhook alerting
=========================
Pushes high-conviction trade setups and macro regime changes to an external
service (Discord / Slack / generic JSON endpoint).

Config (env vars, all optional):
  WEBHOOK_URL          – target URL. If unset, every send is a logged no-op.
  WEBHOOK_FORMAT       – "discord" | "slack" | "generic"  (default "discord")
  WEBHOOK_HMAC_SECRET  – if set, payloads are signed with HMAC-SHA256 and the
                         hex digest is sent in the `X-Signature-256` header
                         as `sha256=<digest>`.

All delivery is best-effort: this module NEVER raises into the caller.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import requests

from utils.logger import get_logger

log = get_logger(__name__)

_TIMEOUT_S = 5
_DEDUPE_TTL_S = 6 * 60 * 60          # 6 hours
_REGIME_MIN_DELTA = 10              # min score move to fire a regime alert

# In-memory dedupe: key -> last-sent epoch seconds
_recent: dict[str, float] = {}


# ── helpers ────────────────────────────────────────────────────────────────────
def _cfg() -> tuple[str | None, str, str | None]:
    url = os.getenv("WEBHOOK_URL")
    fmt = (os.getenv("WEBHOOK_FORMAT") or "discord").lower()
    secret = os.getenv("WEBHOOK_HMAC_SECRET")
    return url, fmt, secret


def _dedupe(key: str) -> bool:
    """Return True if this key was already sent within the TTL (i.e. skip)."""
    now = time.time()
    # opportunistic cleanup
    for k, ts in list(_recent.items()):
        if now - ts > _DEDUPE_TTL_S:
            _recent.pop(k, None)
    last = _recent.get(key)
    if last is not None and now - last < _DEDUPE_TTL_S:
        return True
    _recent[key] = now
    return False


def _post(payload: dict) -> bool:
    """POST payload to the configured webhook. Returns True on success."""
    url, _, secret = _cfg()
    if not url:
        log.info("webhook no-op (WEBHOOK_URL unset): %s",
                 json.dumps(payload)[:300])
        return False

    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-Signature-256"] = f"sha256={sig}"

    try:
        resp = requests.post(url, data=body, headers=headers, timeout=_TIMEOUT_S)
        if resp.status_code >= 300:
            log.warning("webhook POST returned %d: %s", resp.status_code, resp.text[:200])
            return False
        log.info("webhook delivered (%d)", resp.status_code)
        return True
    except Exception as exc:                       # noqa: BLE001 — never raise
        log.warning("webhook POST failed: %s", exc)
        return False


# ── formatters ───────────────────────────────────────────────────────────────
def _f(v) -> str:
    try:
        return f"{float(v):,.4g}"
    except Exception:
        return str(v) if v is not None else "—"


def _setup_fields(row: dict) -> dict:
    trade = row.get("trade") or {}
    return {
        "ticker":     row.get("ticker", "?"),
        "setup":      row.get("setup_label", "—"),
        "conviction": row.get("conviction") or 0,
        "action":     trade.get("action", "—"),
        "entry":      trade.get("entry", "—"),
        "target":     trade.get("target", "—"),
        "stop":       trade.get("stop", "—"),
        "rr":         trade.get("rr", "—"),
        "vol_usd_m":  row.get("vol_usd_m"),
    }


def _setup_payload(fmt: str, s: dict) -> dict:
    title = f"{s['action']} {s['ticker']} — {s['setup']}"
    desc_lines = [
        f"Conviction: {s['conviction']:.0f}/100",
        f"Entry: {s['entry']}",
        f"Target: {s['target']}",
        f"Stop: {s['stop']}",
        f"R:R: {s['rr']}",
    ]
    if s.get("vol_usd_m") is not None:
        desc_lines.append(f"Volume: ${_f(s['vol_usd_m'])}M")
    desc = "\n".join(desc_lines)

    if fmt == "discord":
        return {
            "embeds": [{
                "title": title,
                "description": desc,
                "color": 0x2ECC71 if s["action"] == "BUY" else 0xE74C3C,
                "fields": [
                    {"name": "Conviction", "value": f"{s['conviction']:.0f}", "inline": True},
                    {"name": "Entry",      "value": str(s["entry"]),  "inline": True},
                    {"name": "Target",     "value": str(s["target"]), "inline": True},
                    {"name": "Stop",       "value": str(s["stop"]),   "inline": True},
                    {"name": "R:R",        "value": str(s["rr"]),     "inline": True},
                ],
            }]
        }
    if fmt == "slack":
        return {
            "attachments": [{
                "color": "#2ECC71" if s["action"] == "BUY" else "#E74C3C",
                "blocks": [
                    {"type": "header",
                     "text": {"type": "plain_text", "text": title}},
                    {"type": "section",
                     "text": {"type": "mrkdwn", "text": desc}},
                ],
            }]
        }
    # generic
    return {"type": "setup_alert", **s}


def _regime_payload(fmt: str, old_score, new_score, regime) -> dict:
    direction = "↑" if (new_score or 0) >= (old_score or 0) else "↓"
    title = f"Macro regime shift {direction} — {regime}"
    desc = (f"Deployment Score: {_f(old_score)} → {_f(new_score)}\n"
            f"Regime: {regime}")

    if fmt == "discord":
        return {
            "embeds": [{
                "title": title,
                "description": desc,
                "color": 0x3498DB,
            }]
        }
    if fmt == "slack":
        return {
            "attachments": [{
                "color": "#3498DB",
                "blocks": [
                    {"type": "header",
                     "text": {"type": "plain_text", "text": title}},
                    {"type": "section",
                     "text": {"type": "mrkdwn", "text": desc}},
                ],
            }]
        }
    return {
        "type": "regime_alert",
        "old_score": old_score,
        "new_score": new_score,
        "regime": regime,
    }


# ── public API ───────────────────────────────────────────────────────────────
def send_setup_alert(row: dict) -> bool:
    """Format a high-conviction setup row and POST it. Never raises."""
    try:
        _, fmt, _ = _cfg()
        s = _setup_fields(row)
        key = f"setup:{s['ticker']}:{s['setup']}"
        if _dedupe(key):
            log.info("webhook dedupe skip: %s", key)
            return False
        return _post(_setup_payload(fmt, s))
    except Exception as exc:                       # noqa: BLE001 — never raise
        log.warning("send_setup_alert failed: %s", exc)
        return False


def _decay_payload(fmt: str, setup_label: str, detail: dict) -> dict:
    bw, rw = detail.get("baseline_win"), detail.get("recent_win")
    bpf, rpf = detail.get("baseline_pf"), detail.get("recent_pf")
    title = f"⚠ Signal decay — {setup_label} ({detail.get('severity', 'warn')})"
    lines = [
        f"Win rate: {_f(bw)} → {_f(rw)}",
        f"Profit factor: {_f(bpf)} → {_f(rpf)}",
        f"Recent sample: n={detail.get('recent_n', '?')}",
        "This setup's edge has materially weakened — review before trusting its conviction.",
    ]
    body = "\n".join(lines)
    if fmt == "slack":
        return {"text": f"*{title}*\n{body}"}
    if fmt == "discord":
        return {"embeds": [{"title": title, "description": body, "color": 15158332}]}
    return {"event": "signal_decay", "setup": setup_label, "detail": detail}


def send_decay_alert(setup_label: str, detail: dict) -> bool:
    """POST when a setup's edge decays. Reuses delivery/dedupe. Never raises."""
    try:
        _, fmt, _ = _cfg()
        key = f"decay:{setup_label}"
        if _dedupe(key):
            log.info("webhook dedupe skip: %s", key)
            return False
        return _post(_decay_payload(fmt, setup_label, detail))
    except Exception as exc:                       # noqa: BLE001 — never raise
        log.warning("send_decay_alert failed: %s", exc)
        return False


def send_regime_alert(old_score, new_score, regime) -> bool:
    """POST when the macro regime shifts materially. Never raises."""
    try:
        _, fmt, _ = _cfg()
        try:
            delta = abs(float(new_score) - float(old_score))
            if delta < _REGIME_MIN_DELTA:
                log.info("regime alert skipped: Δ%.1f < %d", delta, _REGIME_MIN_DELTA)
                return False
        except Exception:
            pass  # if scores aren't numeric, fall through and try to send
        key = f"regime:{regime}"
        if _dedupe(key):
            log.info("webhook dedupe skip: %s", key)
            return False
        return _post(_regime_payload(fmt, old_score, new_score, regime))
    except Exception as exc:                       # noqa: BLE001 — never raise
        log.warning("send_regime_alert failed: %s", exc)
        return False
