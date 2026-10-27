"""Desk orchestrator: analysts in parallel → bull vs bear → trader → risk → PM.

Veto only, enforced in code: the final action can never be looser than the
trader's, and a guard REJECT or any failed step makes the run SKIP / no opinion.
"""
from __future__ import annotations
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from desk.agents.schemas import SCHEMAS, STRICTNESS, POSITION_STRICTNESS, stricter
from desk.agents.factpack import flat_keys
from utils.logger import get_logger

log = get_logger(__name__)
_PROMPTS = Path(__file__).parent / "prompts"
ANALYSTS = ("technical", "onchain", "positioning", "macro")


def _cfg(name: str, default):
    try:
        import config
        return getattr(config, name, default)
    except Exception:                                 # noqa: BLE001
        return default


def prompt(role: str) -> str:
    return (_PROMPTS / "preamble.txt").read_text() + "\n" + (_PROMPTS / f"{role}.txt").read_text()


def _pack_text(pack: dict) -> str:
    return "FACT PACK (JSON, cite keys by dotted path):\n" + json.dumps(pack, default=str, indent=1)


def _cited_keys(obj) -> list[str]:
    """source_key fields and parenthesised dotted keys an agent cited."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("source_key",) and isinstance(v, str):
                out.append(v)
            elif k == "decisive_evidence" and isinstance(v, list):
                out += [x for x in v if isinstance(x, str)]
            else:
                out += _cited_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _cited_keys(v)
    return out


def _norm_key(k: str) -> str:
    k = k.strip().strip("()").removeprefix("factpack.").removeprefix("fact_pack.")
    return re.split(r"\s*[=:<>]", k)[0].strip()


def check_citations(outputs: dict, pack: dict) -> list[str]:
    """Cited keys that do not exist in the pack (a sign of invented data)."""
    valid = flat_keys(pack)
    bad = []
    for role, out in outputs.items():
        for k in _cited_keys(out):
            nk = _norm_key(k)
            if nk and nk not in valid and not nk.upper().startswith("MISSING"):
                bad.append(f"{role}:{k}")
    return bad


def run(pack: dict, *, llm=None, mode: str = "new") -> dict:
    """Run the desk on a fact pack. `llm(system, user, name, schema, model, temp) -> dict`.
    Returns {action, conviction, outputs, telegram, bad_citations, error?}."""
    if llm is None:
        from desk.agents.llm import claude_call as llm
    fast = _cfg("DESK_MODEL_FAST", "claude-haiku-5-5")
    deep = _cfg("DESK_MODEL_DEEP", "claude-haiku-5-5")
    rounds = int(_cfg("DESK_DEBATE_ROUNDS", 2))
    meta = pack.get("meta", {})
    base = {"symbol": meta.get("symbol"), "direction": meta.get("direction"),
            "setup_label": meta.get("setup_label"), "built_utc": meta.get("built_utc"),
            "model": f"{fast}/{deep}", "prompt_version": _cfg("DESK_PROMPT_VERSION", "v1"),
            "mode": mode}
    guard = pack.get("guard") or {}
    if mode == "new" and guard.get("verdict") not in (None, "ACCEPT"):
        return {**base, "action": "SKIP", "conviction": 0, "outputs": {},
                "telegram": ["SKIP: the guard rejected this setup", ", ".join(guard.get("failures", [])),
                             "The desk only reviews setups that pass your rules", "Fix the rule breaks first"],
                "bad_citations": [], "error": "guard_reject"}
    ptxt = _pack_text(pack)
    outs: dict = {}
    try:
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {r: ex.submit(llm, prompt(r), ptxt, r, SCHEMAS[r], fast, 0.0) for r in ANALYSTS}
            for r, f in futs.items():
                outs[r] = f.result()
        analysts = json.dumps({r: outs[r] for r in ANALYSTS}, indent=1)

        if mode == "position":
            pr = llm(prompt("position_review"), f"{ptxt}\n\nANALYST REPORTS:\n{analysts}",
                     "position_review", SCHEMAS["position_review"], deep, 0.0)
            outs["position_review"] = pr
            act = pr.get("action", "HOLD")
            if act not in POSITION_STRICTNESS:
                act = "HOLD"
            bad = check_citations(outs, pack)
            return {**base, "action": act, "conviction": pr.get("conviction"), "outputs": outs,
                    "telegram": [f"{act} ({pr.get('conviction', 0)}/10)", pr.get("reason", ""),
                                 "Thesis still valid" if pr.get("thesis_still_valid") else "Thesis weakening",
                                 "Desk advice only; your stop stays where it is unless you move it tighter"],
                    "bad_citations": bad}

        # Debate: round 1 blind (neither sees the other), later rounds rebut.
        ctx = f"{ptxt}\n\nANALYST REPORTS:\n{analysts}"
        with ThreadPoolExecutor(max_workers=2) as ex:
            fb = ex.submit(llm, prompt("bull"), ctx, "bull", SCHEMAS["bull"], deep, 0.4)
            fr = ex.submit(llm, prompt("bear"), ctx, "bear", SCHEMAS["bear"], deep, 0.4)
            bull, bear = fb.result(), fr.result()
        for _ in range(max(0, rounds - 1)):
            with ThreadPoolExecutor(max_workers=2) as ex:
                fb = ex.submit(llm, prompt("bull"), f"{ctx}\n\nBEAR REPORT TO ANSWER:\n{json.dumps(bear)}",
                               "bull", SCHEMAS["bull"], deep, 0.4)
                fr = ex.submit(llm, prompt("bear"), f"{ctx}\n\nBULL REPORT TO ANSWER:\n{json.dumps(bull)}",
                               "bear", SCHEMAS["bear"], deep, 0.4)
                bull, bear = fb.result(), fr.result()
        outs["bull"], outs["bear"] = bull, bear
        debate = json.dumps({"bull": bull, "bear": bear}, indent=1)

        trader = llm(prompt("trader"), f"{ctx}\n\nDEBATE:\n{debate}", "trader", SCHEMAS["trader"], deep, 0.0)
        outs["trader"] = trader
        t_act = trader.get("action") if trader.get("action") in STRICTNESS else "SKIP"
        if trader.get("option_id") == "grid" and t_act in ("TAKE", "TAKE_REDUCED"):
            t_act = "TAKE_REDUCED"                    # grids failed the backtest: never full size

        risk = llm(prompt("risk"), f"{ctx}\n\nTRADER:\n{json.dumps(trader)}", "risk", SCHEMAS["risk"], deep, 0.0)
        outs["risk"] = risk
        r_act = stricter(risk.get("final_action", "SKIP"), t_act)

        pm = llm(prompt("pm"), f"{ctx}\n\nTRADER:\n{json.dumps(trader)}\n\nRISK:\n{json.dumps(risk)}"
                 f"\n\nCURRENT ACTION AFTER RISK: {r_act}", "pm", SCHEMAS["pm"], deep, 0.0)
        outs["pm"] = pm
        final = stricter(pm.get("approved_action", "SKIP"), r_act)
    except Exception as exc:                          # noqa: BLE001 — a broken run is "no opinion"
        log.warning("desk run failed: %s", exc)
        return {**base, "action": "NO_OPINION", "conviction": None, "outputs": outs,
                "telegram": ["NO OPINION: the desk run failed", str(exc)[:120],
                             "Trade the signal on its own rules", "Check the desk logs"],
                "bad_citations": [], "error": str(exc)}

    bad = check_citations(outs, pack)
    if len(bad) > 2:                                  # invented keys → one notch stricter
        final = {"TAKE": "TAKE_REDUCED", "TAKE_REDUCED": "WAIT"}.get(final, final)
    tg = list(pm.get("telegram") or [])[:4]
    while len(tg) < 4:
        tg.append("")
    tg[0] = f"{final.replace('_', ' ')} ({trader.get('conviction', 0)}/10). " + tg[0]
    return {**base, "action": final, "conviction": trader.get("conviction"),
            "trader_action": t_act, "risk_action": r_act, "outputs": outs, "telegram": tg,
            "bad_citations": bad}
