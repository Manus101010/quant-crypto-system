"""JSON schemas each desk agent must return (enforced through tool use)."""
from __future__ import annotations

ACTIONS = ["TAKE", "TAKE_REDUCED", "WAIT", "SKIP"]
POSITION_ACTIONS = ["HOLD", "TIGHTEN_STOP", "TAKE_PARTIAL", "CLOSE"]

_num = {"type": "number"}
_str = {"type": "string"}
_bool = {"type": "boolean"}
_conf = {"type": "number", "minimum": 0, "maximum": 1}
_ten = {"type": "number", "minimum": 0, "maximum": 10}
_strs = {"type": "array", "items": _str}
_cited = {"type": "array", "items": {"type": "object", "properties": {
    "point": _str, "source_key": _str}, "required": ["point", "source_key"]}}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props,
            "required": required if required is not None else list(props)}


SCHEMAS: dict[str, dict] = {
    "technical": _obj({
        "bias": {"enum": ["long", "short", "neutral"]},
        "setup_quality": _ten,
        "timeframe_alignment": _obj({k: {"enum": ["up", "down", "flat", "unknown"]}
                                     for k in ("15m", "1h", "4h", "1d")}),
        "late_entry": _bool,
        "evidence": _cited, "invalidation": _str, "confidence": _conf}),
    "onchain": _obj({
        "bias": {"enum": ["long", "short", "neutral"]},
        "flow_signal": {"enum": ["accumulation", "distribution", "none", "unknown"]},
        "supply_risk": {"enum": ["low", "medium", "high", "unknown"]},
        "manipulation_risk": {"enum": ["low", "medium", "high"]},
        "evidence": _cited, "missing": _strs, "confidence": _conf}),
    "positioning": _obj({
        "crowded_side": {"enum": ["longs", "shorts", "neither", "unknown"]},
        "trade_side_crowded": _bool,
        "move_driver": {"enum": ["new_positions", "covering", "unclear"]},
        "squeeze_risk_against_trade": {"enum": ["low", "medium", "high"]},
        "prereg_rule_a": {"type": ["boolean", "null"]},
        "prereg_rule_b": {"type": ["boolean", "null"]},
        "evidence": _cited, "confidence": _conf}),
    "macro": _obj({
        "btc_regime": {"enum": ["risk_on", "risk_off", "chop", "unknown"]},
        "event_risk_72h": {"type": "array", "items": _obj({
            "event": _str, "when": _str, "impact": {"enum": ["low", "medium", "high"]}})},
        "narrative": {"enum": ["gaining", "fading", "none", "unknown"]},
        "backdrop_supports_trade": _bool,
        "evidence": _cited, "confidence": _conf}),
    "bull": _obj({
        "thesis": _str, "top_evidence": _cited,
        "rebuttals": {"type": "array", "items": _obj({"point": _str, "answer": _str})},
        "what_would_change_my_mind": _str, "conviction": _ten}),
    "bear": _obj({
        "thesis": _str, "top_risks": _cited,
        "rebuttals": {"type": "array", "items": _obj({"point": _str, "answer": _str})},
        "what_would_change_my_mind": _str, "conviction": _ten}),
    "trader": _obj({
        "action": {"enum": ACTIONS},
        "option_id": {"type": ["string", "null"]},
        "wait_condition": {"type": ["string", "null"]},
        "reason": _str, "decisive_evidence": _strs, "conviction": _ten}),
    "risk": _obj({
        "final_action": {"enum": ACTIONS},
        "unscored_risks": {"type": "array", "items": _obj({
            "risk": _str, "severity": {"enum": ["low", "medium", "high"]}, "source_key": _str})},
        "chasing_flag": _bool}),
    "pm": _obj({
        "approved_action": {"enum": ACTIONS},
        "book_note": _str,
        "telegram": {"type": "array", "items": _str, "minItems": 4, "maxItems": 4}}),
    "position_review": _obj({
        "action": {"enum": POSITION_ACTIONS},
        "option_id": {"type": ["string", "null"]},
        "reason": _str, "thesis_still_valid": _bool, "conviction": _ten}),
}

# Higher = stricter. The desk may only move a verdict to the right.
STRICTNESS = {"TAKE": 0, "TAKE_REDUCED": 1, "WAIT": 2, "SKIP": 3}
POSITION_STRICTNESS = {"HOLD": 0, "TIGHTEN_STOP": 1, "TAKE_PARTIAL": 2, "CLOSE": 3}


def stricter(a: str, b: str) -> str:
    """The stricter of two actions (unknown values count as SKIP)."""
    return a if STRICTNESS.get(a, 3) >= STRICTNESS.get(b, 3) else b
