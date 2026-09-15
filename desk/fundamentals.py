"""
Trade Desk — light fundamentals pass (Claude + live web search).

A fast desk read, not a research report: what the project is, tokenomics basics
(circulating vs FDV), and RECENT catalysts pulled via Claude's web_search tool.
Each catalyst carries its source + date so freshness is judgeable; when nothing
recent is found we say so plainly rather than padding with stale general text.

Read-only / signal-only. Cached in-memory ~1h per symbol.

Deferred seams (v1 does NOT build these — noted for later):
  • _sentiment(symbol): a per-coin sentiment meter would slot in here.
  • _onchain(symbol):   DexScreener / on-chain holder & liquidity metrics here.
"""
from __future__ import annotations
import json
import time
import datetime

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from utils.logger import get_logger

log = get_logger(__name__)

_TTL = 3600
_cache: dict[str, tuple[float, dict]] = {}

_SYSTEM = (
    "You are a crypto desk analyst giving a FAST pre-trade fundamentals read, not "
    "a research report. Be concise and concrete. Use web_search to find RECENT "
    "catalysts/news (last ~30 days). For every catalyst include its source name and "
    "publication date. If you find nothing genuinely recent, say so — do NOT pad with "
    "stale or generic background. Never give financial advice or price targets."
)

# Final answer must be exactly this JSON (Claude may web_search first).
_SCHEMA_HINT = """
Return ONLY a JSON object, no prose around it:
{
  "project": "one or two sentences: what this coin/project actually is",
  "tokenomics": "one or two sentences: circulating vs FDV / max supply, unlock or
                 inflation risk if known — say 'unknown' for anything you can't verify",
  "catalysts": [
    {"headline": "...", "source": "publisher name", "date": "YYYY-MM-DD", "url": "..."}
  ],
  "nothing_recent": true/false,
  "read": "one plain sentence on the fundamental backdrop for a short-horizon trade"
}
"""


def _extract_json(text: str) -> dict | None:
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b == -1 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except Exception:
        return None


def fa_read(symbol: str, force: bool = False) -> dict:
    """Light fundamentals read for `symbol` (e.g. 'SOL-USD'). Never raises."""
    base = symbol.split("-")[0].split("/")[0].upper()
    hit = _cache.get(base)
    if hit and not force and time.time() - hit[0] < _TTL:
        return hit[1]

    if not ANTHROPIC_API_KEY:
        return {"ok": False, "note": "No ANTHROPIC_API_KEY — FA read unavailable.",
                "project": "", "tokenomics": "", "catalysts": [], "nothing_recent": True}

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = (f"Coin ticker: {base} (crypto). Give the fast fundamentals read.\n"
                  f"{_SCHEMA_HINT}")
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            system=_SYSTEM,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        data = _extract_json(text) or {}
        out = {
            "ok": True,
            "project": data.get("project", ""),
            "tokenomics": data.get("tokenomics", ""),
            "catalysts": data.get("catalysts", []) or [],
            "nothing_recent": bool(data.get("nothing_recent", not data.get("catalysts"))),
            "read": data.get("read", ""),
            "fetched_at": datetime.datetime.utcnow().isoformat(),
            "model": CLAUDE_MODEL,
        }
        _cache[base] = (time.time(), out)
        return out
    except Exception as exc:                       # noqa: BLE001 — desk must not crash
        log.warning("fa_read(%s) failed: %s", base, exc)
        return {"ok": False, "note": f"FA read failed: {exc}", "project": "",
                "tokenomics": "", "catalysts": [], "nothing_recent": True}


# ── Deferred seams (v1: not built) ────────────────────────────────────────────
def _sentiment(symbol: str):
    """DEFERRED: per-coin sentiment meter would slot in here (social/derivs skew)."""
    return None


def _onchain(symbol: str):
    """DEFERRED: on-chain metrics (DexScreener liquidity, holder concentration,
    supply flows) would slot in here."""
    return None
