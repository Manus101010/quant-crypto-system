"""22 Nov 2026: 5pm set and forget plans (research/ds_practical SET15)."""
import json

import pytest

import trade_digest as td


def test_ds_plan_caps_stop_at_15pct_and_targets_2r():
    p = td.plan_for({"setup_label": "Distribution Short", "direction": "short", "stop": 0.38}, 0.27)
    assert p["stop"] == pytest.approx(0.27 * 1.15) and p["max_hold"] == 30
    assert p["target"] == pytest.approx(0.27 - 2 * (0.27 * 1.15 - 0.27))


def test_ds_plan_keeps_a_tighter_signal_stop():
    p = td.plan_for({"setup_label": "Distribution Short", "direction": "short", "stop": 105.0}, 100.0)
    assert p["stop"] == 105.0 and p["target"] == pytest.approx(90.0)


def test_skip_when_price_already_through_stop_or_target():
    assert td.plan_for({"setup_label": "Distribution Short", "direction": "short", "stop": 1.0}, 1.2) is None
    dbf = {"setup_label": "Downtrend Bounce Fade", "direction": "short", "stop": 1.2, "target": 0.9}
    assert td.plan_for(dbf, 0.85) is None
    assert td.plan_for(dbf, 1.0)["target"] == 0.9


def test_with_plan_overlays_entry_stop_target_and_hold(monkeypatch):
    monkeypatch.setattr(td.tdb, "get_state", lambda k: json.dumps(
        {"entry": 1.0, "stop": 1.15, "target": 0.7, "max_hold": 30}) if k == "plan:7" else None)
    t = td.with_plan({"id": 7, "fired_price": 0.9, "stop": 1.4, "condition_json": "{}"})
    assert (t["fired_price"], t["stop"], t["target"]) == (1.0, 1.15, 0.7)
    assert json.loads(t["condition_json"])["max_hold"] == 30
    assert td.with_plan({"id": 8, "fired_price": 2.0})["fired_price"] == 2.0
