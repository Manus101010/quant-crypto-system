"""Desk layer tests: offline, with a fake LLM."""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
import pytest

from desk.agents import run as desk_run, store, report
from desk.agents.factpack import technicals, flat_keys
from desk.agents.schemas import stricter

PACK = {"meta": {"symbol": "SOLUSDT", "direction": "long", "setup_label": "Distribution Short",
                 "trigger_id": 7, "built_utc": "2026-10-28T00:00:00+00:00"},
        "technicals": {"4h": {"ema_stack": "bull", "rsi14": 55.0}},
        "features": {"funding_pct_7d": 96},
        "guard": {"verdict": "ACCEPT", "failures": [], "metrics": {}},
        "guard_options": {"plain": {"id": "plain"}, "grid": {"id": "grid"}}, "missing": []}

BASE = {
    "technical": {"bias": "long", "setup_quality": 6, "timeframe_alignment": {"15m": "up", "1h": "up", "4h": "up", "1d": "flat"},
                  "late_entry": False, "evidence": [{"point": "stack", "source_key": "technicals.4h.ema_stack"}],
                  "invalidation": "x", "confidence": 0.6},
    "onchain": {"bias": "neutral", "flow_signal": "unknown", "supply_risk": "unknown", "manipulation_risk": "low",
                "evidence": [], "missing": ["holders"], "confidence": 0.3},
    "positioning": {"crowded_side": "longs", "trade_side_crowded": True, "move_driver": "new_positions",
                    "squeeze_risk_against_trade": "medium", "prereg_rule_a": None, "prereg_rule_b": None,
                    "evidence": [{"point": "funding", "source_key": "features.funding_pct_7d"}], "confidence": 0.7},
    "macro": {"btc_regime": "chop", "event_risk_72h": [], "narrative": "unknown", "backdrop_supports_trade": True,
              "evidence": [], "confidence": 0.5},
    "bull": {"thesis": "t", "top_evidence": [], "rebuttals": [], "what_would_change_my_mind": "x", "conviction": 6},
    "bear": {"thesis": "t", "top_risks": [], "rebuttals": [], "what_would_change_my_mind": "x", "conviction": 5},
    "trader": {"action": "TAKE", "option_id": "plain", "wait_condition": None, "reason": "r",
               "decisive_evidence": ["features.funding_pct_7d"], "conviction": 7},
    "risk": {"final_action": "TAKE", "unscored_risks": [], "chasing_flag": False},
    "pm": {"approved_action": "TAKE", "book_note": "ok", "telegram": ["a", "b", "c", "d"]},
    "position_review": {"action": "HOLD", "option_id": None, "reason": "r", "thesis_still_valid": True, "conviction": 5},
}


class FakeLLM:
    def __init__(self, **over):
        self.over, self.calls = over, []

    def __call__(self, system, user, name, schema, model, temp):
        self.calls.append((name, user))
        val = self.over.get(name, BASE[name])
        if isinstance(val, Exception):
            raise val
        return json.loads(json.dumps(val))


def test_stricter():
    assert stricter("TAKE", "SKIP") == "SKIP"
    assert stricter("WAIT", "TAKE_REDUCED") == "WAIT"
    assert stricter("BOGUS", "TAKE") == "BOGUS"   # unknown counts as strictest


def test_full_run_take_and_call_counts():
    llm = FakeLLM()
    res = desk_run.run(PACK, llm=llm)
    assert res["action"] == "TAKE" and res["conviction"] == 7
    names = [c[0] for c in llm.calls]
    assert names.count("bull") == 2 and names.count("bear") == 2       # 2 debate rounds
    assert res["bad_citations"] == []


def test_debate_round_one_is_blind():
    llm = FakeLLM()
    desk_run.run(PACK, llm=llm)
    bulls = [u for n, u in llm.calls if n == "bull"]
    assert "BEAR REPORT" not in bulls[0] and "BEAR REPORT" in bulls[1]


def test_veto_only_cannot_loosen():
    res = desk_run.run(PACK, llm=FakeLLM(trader=dict(BASE["trader"], action="SKIP")))
    assert res["action"] == "SKIP"                                    # risk/pm said TAKE: ignored
    res = desk_run.run(PACK, llm=FakeLLM(risk=dict(BASE["risk"], final_action="WAIT")))
    assert res["action"] == "WAIT"


def test_grid_never_full_size():
    res = desk_run.run(PACK, llm=FakeLLM(trader=dict(BASE["trader"], option_id="grid")))
    assert res["action"] == "TAKE_REDUCED"


def test_guard_reject_skips_without_llm():
    llm = FakeLLM()
    pack = dict(PACK, guard={"verdict": "REJECT", "failures": ["loss_cap"], "metrics": {}})
    res = desk_run.run(pack, llm=llm)
    assert res["action"] == "SKIP" and llm.calls == []


def test_failure_is_no_opinion():
    res = desk_run.run(PACK, llm=FakeLLM(trader=RuntimeError("api down")))
    assert res["action"] == "NO_OPINION"


def test_invented_citations_downgrade():
    bad_ev = [{"point": "p", "source_key": f"made.up.{i}"} for i in range(3)]
    res = desk_run.run(PACK, llm=FakeLLM(technical=dict(BASE["technical"], evidence=bad_ev)))
    assert len(res["bad_citations"]) == 3 and res["action"] == "TAKE_REDUCED"


def test_position_mode():
    res = desk_run.run(PACK, llm=FakeLLM(), mode="position")
    assert res["action"] == "HOLD" and "position_review" in res["outputs"]


def test_technicals_and_flat_keys():
    n = 300
    c = pd.Series(100 + np.cumsum(np.sin(np.arange(n) / 5)))
    df = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000.0})
    t = technicals(df)
    assert t["ema_stack"] in ("bull", "bear", "mixed") and 0 <= t["rsi14"] <= 100
    assert technicals(df.iloc[:30]) is None
    assert "technicals.4h.ema_stack" in flat_keys(PACK)


def test_telegram_text_escapes():
    res = {"symbol": "SOLUSDT", "direction": "long", "setup_label": "<x>", "action": "SKIP",
           "telegram": ["SKIP <b>", "b", "c", "d"], "bad_citations": []}
    txt = report.telegram_text(res)
    assert "&lt;x&gt;" in txt and "SKIP &lt;b&gt;" in txt


def test_scorecard_and_memory(monkeypatch):
    state = {}
    from triggers import db
    monkeypatch.setattr(db, "get_state", lambda k: state.get(k))
    monkeypatch.setattr(db, "set_state", lambda k, v: state.__setitem__(k, v))
    trades = []
    for i in range(10):
        act = "TAKE" if i % 2 == 0 else "SKIP"
        r = 1.0 if act == "TAKE" else -1.0
        store.save(i, {"action": act, "setup_label": "S", "symbol": "SOLUSDT"})
        trades.append({"id": i, "r_multiple": r, "outcome": "target" if r > 0 else "stop",
                       "fired_at": f"2026-10-{i + 10:02d}"})
    sc = store.scorecard(trades)
    assert sc["approved"]["avg_r"] == 1.0 and sc["vetoed"]["avg_r"] == -1.0
    assert not sc["passes_gate"] and sc["needs_n"] == 50
    monkeypatch.setattr(db, "get_fired_trades", lambda open_only=False: trades)
    mem = store.memory_for("S")
    assert len(mem) == 5 and all(m["desk_was_right"] for m in mem)
