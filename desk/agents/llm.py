"""Thin Claude API caller for the desk: one forced tool call returns validated JSON.

Billing: this uses the Claude API (pay per token from Anthropic Console credits),
NOT the Claude Pro plan. Default model is the small, cheap one; see config.
"""
from __future__ import annotations
import json
from typing import Callable
from utils.logger import get_logger

log = get_logger(__name__)

# (system, user, schema_name, schema, model, temperature) -> dict
LLMFn = Callable[[str, str, str, dict, str, float], dict]

_client = None
usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}


def _get_client():
    global _client
    if _client is None:
        import anthropic
        from config import ANTHROPIC_API_KEY
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def claude_call(system: str, user: str, schema_name: str, schema: dict,
                model: str, temperature: float = 0.0) -> dict:
    """Ask Claude for exactly one tool call matching `schema`. Raises on failure."""
    resp = _get_client().messages.create(
        model=model,
        max_tokens=1500,
        temperature=temperature,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=[{"name": f"submit_{schema_name}",
                "description": f"Submit the {schema_name} report.",
                "input_schema": schema}],
        tool_choice={"type": "tool", "name": f"submit_{schema_name}"},
        messages=[{"role": "user", "content": user}],
    )
    u = getattr(resp, "usage", None)
    if u is not None:
        usage["input_tokens"] += int(getattr(u, "input_tokens", 0) or 0)
        usage["output_tokens"] += int(getattr(u, "output_tokens", 0) or 0)
    usage["calls"] += 1
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            data = block.input
            return data if isinstance(data, dict) else json.loads(data)
    raise ValueError(f"{schema_name}: no tool call in response")
