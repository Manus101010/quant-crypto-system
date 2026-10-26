from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guard import preflight as pf  # noqa: E402
from guard.ledger import Ledger, sydney_day, norm_symbol  # noqa: E402

DOOD = dict(mode="short", lo=0.0016, hi=0.0025, grids=200, leverage=5, investment=263.8642)
TICK = 0.0000001


def _rules(v):
    return {f["rule"] for f in v.failures}


# ── preflight: plain ──────────────────────────────────────────────────────────
def test_plain_accept():
    # 2% stop at 10x: loss 50*10*(2%+0.15%) = $10.75 <= $12.50, liq ~9.5% >= 4%
    v = pf.check_plain("long", 100, 98, 10, 50)
    assert v.ok, v.failures
    assert v.metrics["loss_at_stop"] == pytest.approx(10.75)


def test_plain_loss_cap_suggests_leverage_and_stop():
    v = pf.check_plain("short", 100, 104, 10, 50, tick=0.01)
    assert not v.ok and "loss_cap" in _rules(v)
    assert v.suggestion["max_leverage"] == 6          # 300 x 4.15% = $12.45 <= $12.50
    assert v.suggestion["tightest_ok_stop"] == pytest.approx(102.35)


def test_plain_no_stop_and_min_margin():
    v = pf.check_plain("long", 100, None, 5, 40)
    assert {"no_stop", "min_margin"} <= _rules(v)


def test_plain_liq_rule():
    v = pf.check_plain("long", 100, 96, 15, 50)   # liq ~6.2% < 2 x 4%
    assert "liq_distance" in _rules(v)


def test_plain_daily_and_open_risk():
    v = pf.check_plain("long", 100, 98, 10, 50, daily_realised_pnl=-125)
    assert "daily_loss_cap" in _rules(v)
    v = pf.check_plain("long", 100, 98, 10, 50, open_risk_usd=120)
    assert "open_risk_cap" in _rules(v)
    v = pf.check_plain("long", 100, 98, 10, 50, daily_realised_pnl=-120)
    assert "daily_loss_room" in _rules(v)


def test_plain_1r_lock():
    v = pf.check_plain("long", 100, 98, 10, 50, max_loss_usd=8)
    assert "loss_cap" in _rules(v)


def test_liq_price_formula():
    # short 1 unit at 100, margin 20, mmr 0 -> liq 120
    assert pf.liq_price("short", 1, 100, 20, 0) == pytest.approx(120)
    assert pf.liq_price("long", 1, 100, 20, 0) == pytest.approx(80)


# ── preflight: grid ───────────────────────────────────────────────────────────
def test_grid_stop_must_be_beyond_edge():
    v = pf.check_grid(**DOOD, stop=0.0024, entry=0.002096)
    assert "stop_inside_range" in _rules(v)
    v = pf.check_grid("long", 90, 110, 10, 3, 50, stop=91, entry=100)
    assert "stop_inside_range" in _rules(v)


def test_grid_min_leverage():
    v = pf.check_grid("long", 95, 105, 10, 2, 50, stop=94, entry=100)
    assert "min_grid_leverage" in _rules(v)


def test_dood_live_grid_rejected_with_fix():
    dr = pf.infer_deploy_ratio("short", 0.0016, 0.0025, 200, 0.002096, 263.8642, 5, 210560,
                               mark=0.0020221)
    mmr = pf.implied_mmr("short", 210560, 0.002096, 263.8642, 0.0031673)
    v = pf.check_grid(**DOOD, stop=None, entry=0.002096, deploy_ratio=dr, mmr=mmr, tick=TICK,
                      live_liq=0.0031673)
    assert not v.ok
    assert {"no_stop", "loss_cap", "liq_distance"} <= _rules(v)
    assert v.metrics["loss_at_stop"] > 0.25 * 263.8642
    top = v.suggestion["range_edge"]
    assert 0.002096 < top["edge"] < 0.0025
    assert top["stop"] >= top["edge"]
    # relaunching with the suggested top and stop passes the loss and liq rules
    v2 = pf.check_grid("short", 0.0016, top["edge"], 200, 5, 263.8642, top["stop"], 0.002096,
                       deploy_ratio=dr, mmr=mmr, tick=TICK)
    assert not ({"loss_cap", "liq_distance", "stop_inside_range", "no_stop"} & _rules(v2)), v2.failures


def test_grid_worst_case_monotone_in_stop():
    a = pf.grid_worst_case("short", 0.0016, 0.0025, 200, 0.0021, 263.86, 5, 0.0026)["loss_at_stop"]
    b = pf.grid_worst_case("short", 0.0016, 0.0025, 200, 0.0021, 263.86, 5, 0.0030)["loss_at_stop"]
    assert b > a > 0


def test_round_tick():
    assert pf.round_tick(0.00251234, TICK, "up") == 0.0025124
    assert pf.round_tick(0.00251234, TICK, "down") == 0.0025123


def test_propose_grid_compliant():
    r = pf.propose_grid("long", 100, 3, investment=50, tick=0.01)
    assert r["ok"], r
    p = r["plan"]
    assert p["leverage"] >= 3 and p["stop"] <= p["lo"]
    assert r["verdict"]["metrics"]["loss_at_stop"] <= 12.5 + 1e-6
    r = pf.propose_grid("short", 0.0020221, 0.00012, investment=263.8642, tick=TICK, mmr=0.0574)
    assert r["ok"], r
    assert r["plan"]["stop"] >= r["plan"]["hi"]


def test_parse_guard_command():
    g = pf.parse_guard_command("short DOODUSDT grid 0.0016 0.0025 200 5x 263.86")
    assert g == {"direction": "short", "symbol": "DOODUSDT", "type": "grid", "lo": 0.0016,
                 "hi": 0.0025, "grids": 200, "leverage": 5.0, "investment": 263.86,
                 "stop": None, "entry": None}
    g = pf.parse_guard_command("short DOODUSDT grid 0.0016 0.0025 200 5x 263.86 sl 0.00252 @0.0021")
    assert g["stop"] == 0.00252 and g["entry"] == 0.0021
    p = pf.parse_guard_command("long BTCUSDT 65000 63000 10x 50")
    assert p["type"] == "plain" and p["stop"] == 63000
    with pytest.raises(ValueError):
        pf.parse_guard_command("short")


def test_format_verdict_lists_failures():
    v = pf.check_grid(**DOOD, stop=None, entry=0.002096)
    txt = pf.format_verdict(v, "DOODUSDT")
    assert "REJECT" in txt and "no_stop" in txt and "loss_cap" in txt


# ── ledger ────────────────────────────────────────────────────────────────────
class Mem:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def set(self, k, v):
        self.d[k] = v


def _ledger():
    m = Mem()
    return Ledger(m.get, m.set), m


def test_sydney_day_boundary():
    # 13:30 UTC on 27 Oct = 00:30 on 28 Oct in Sydney (AEDT, UTC+11)
    assert sydney_day(datetime(2026, 10, 27, 13, 30, tzinfo=timezone.utc)) == "2026-10-28"
    assert sydney_day(datetime(2026, 10, 27, 12, 30, tzinfo=timezone.utc)) == "2026-10-27"


def test_norm_symbol():
    assert norm_symbol("DOOD-USD") == norm_symbol("dood") == norm_symbol("DOODUSDT") == "DOODUSDT"


def test_issue_and_match_grid_and_unissued():
    L, _ = _ledger()
    now = datetime(2026, 10, 27, 1, tzinfo=timezone.utc)
    L.issue({"symbol": "DOOD-USD", "type": "grid", "mode": "short", "lo": 0.0016, "hi": 0.0022,
             "grids": 200, "investment": 263.86}, now)
    live_ok = {"kind": "grid", "symbol": "DOODUSDT", "side": "short", "lo": 0.0016, "hi": 0.002205,
               "grids": 200, "margin": 263.86}
    live_bad = dict(live_ok, hi=0.0025)
    assert L.match(live_ok, now)
    assert L.match(live_bad, now) is None
    new = L.tag_unissued([live_bad], now)
    assert len(new) == 1 and new[0]["tag"] == "unissued"
    assert L.tag_unissued([live_bad], now) == []          # only once


def test_stopout_locks_next_issue_to_1r():
    L, _ = _ledger()
    now = datetime(2026, 10, 27, 1, tzinfo=timezone.utc)
    start_ms = int(datetime(2026, 10, 26, 14, tzinfo=timezone.utc).timestamp() * 1000)
    day = L.apply_closed([{"symbol": "HYPEUSDT", "closedPnl": "-12.5", "orderId": "o1",
                           "updatedTime": str(start_ms + 1000)}], now)
    assert day["realised"] == -12.5 and day["stopouts"] == 1
    assert L.max_loss_for_next() == 12.5
    rec = L.issue({"symbol": "SOLUSDT", "type": "plain", "direction": "long", "entry": 1,
                   "margin": 50}, now)
    assert rec["size_locked"] and rec["max_loss_usd"] == 12.5
    assert L.lock() is None
    # same row again is not double counted
    assert L.apply_closed([{"symbol": "HYPEUSDT", "closedPnl": "-12.5", "orderId": "o1",
                            "updatedTime": str(start_ms + 1000)}], now)["realised"] == -12.5


def test_unissued_pnl_split_and_cap_once():
    L, m = _ledger()
    now = datetime(2026, 10, 27, 1, tzinfo=timezone.utc)
    L.tag_unissued([{"kind": "position", "symbol": "PEPEUSDT", "side": "long", "entry": 1,
                     "margin": 50}], now)
    day = L.apply_closed([{"symbol": "PEPEUSDT", "closedPnl": "-130", "orderId": "x"}], now)
    assert day["realised_unissued"] == -130 and day["realised_issued"] == 0
    assert L.mark_cap_hit(now) is True and L.mark_cap_hit(now) is False
    assert json.loads(m.d["guard:day:2026-10-27"])["cap_hit"] is True
