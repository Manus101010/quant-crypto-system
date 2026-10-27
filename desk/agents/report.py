"""HTML report per desk run + the short Telegram verdict."""
from __future__ import annotations
import html
import json
import datetime as _dt
from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parents[2] / "paper_trades" / "desk"
_ICON = {"TAKE": "🟢", "TAKE_REDUCED": "🟡", "WAIT": "⏸", "SKIP": "⛔", "NO_OPINION": "⚪",
         "HOLD": "🟢", "TIGHTEN_STOP": "🟡", "TAKE_PARTIAL": "🟡", "CLOSE": "⛔"}


def telegram_text(result: dict) -> str:
    sym = (result.get("symbol") or "").replace("USDT", "")
    head = (f"🧠 <b>Desk on {html.escape(sym)} {html.escape(result.get('direction') or '')}"
            f" ({html.escape(result.get('setup_label') or 'manual')})</b>")
    lines = [html.escape(x) for x in result.get("telegram", []) if x]
    icon = _ICON.get(result.get("action"), "")
    if lines:
        lines[0] = f"{icon} <b>{lines[0]}</b>"
    tail = ""
    if result.get("bad_citations"):
        tail = f"\n<i>⚠️ {len(result['bad_citations'])} cited figures not found in the data; treat with care.</i>"
    return head + "\n" + "\n".join(lines) + tail + "\n<i>Veto only: it can shrink or skip a trade, never add one.</i>"


def _section(title: str, data) -> str:
    return (f"<h2>{html.escape(title)}</h2><pre>"
            f"{html.escape(json.dumps(data, indent=2, default=str))}</pre>")


def write_html(result: dict, pack: dict) -> str | None:
    """Save the full run (fact pack + every agent output) as one HTML page."""
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        name = f"{stamp}_{result.get('symbol') or 'X'}_{(pack.get('meta') or {}).get('trigger_id') or 'manual'}.html"
        outs = result.get("outputs", {})
        body = "".join(_section(r, outs[r]) for r in outs)
        page = ("<!doctype html><meta charset='utf-8'><title>Desk report</title>"
                "<style>body{font:14px system-ui;max-width:900px;margin:24px auto;padding:0 16px}"
                "pre{background:#f4f4f4;padding:12px;overflow:auto;white-space:pre-wrap}</style>"
                f"<h1>{html.escape(str(result.get('symbol')))} {html.escape(str(result.get('direction')))}: "
                f"{html.escape(str(result.get('action')))}</h1>"
                f"<p>{html.escape(' | '.join(result.get('telegram', [])))}</p>"
                f"<p>Model {html.escape(str(result.get('model')))}, prompts {html.escape(str(result.get('prompt_version')))}, "
                f"bad citations {len(result.get('bad_citations', []))}</p>"
                + body + _section("fact pack", pack))
        path = REPORT_DIR / name
        path.write_text(page)
        return str(path.relative_to(REPORT_DIR.parents[1]))
    except Exception:                                 # noqa: BLE001
        return None
