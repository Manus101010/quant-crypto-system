"""22 Nov 2026: 5pm set and forget plans (research/ds_practical SET15)."""
import json

import pytest

import trade_digest as td


DS = {"setup_label": "Distribution Short", "direction": "short",
      "condition_json": json.dumps({"atr": 0.02})}


def test_ds_plan_signal_stop_2r_target_and_bybit_trail():
    p = td.plan_for({**DS, "stop": 0.38}, 0.27)
    assert p["stop"] == 0.38 and p["max_hold"] == 60
    assert p["target"] == pytest.approx(0.27 - 2 * 0.11) and p["trail"] == pytest.approx(0.07)


def test_ds_plan_needs_atr_for_the_trail():
    assert td.plan_for({**DS, "stop": 105.0, "condition_json": "{}"}, 100.0) is None


def test_skip_when_price_already_through_stop_or_target():
    assert td.plan_for({**DS, "stop": 1.0}, 1.2) is None
    dbf = {"setup_label": "Downtrend Bounce Fade", "direction": "short", "stop": 1.2, "target": 0.7}
    assert td.plan_for(dbf, 0.65) is None                    # already past its target
    assert td.plan_for(dbf, 1.0)["target"] == 0.7            # 0.3 reward for 0.2 risk
    assert td.plan_for({**dbf, "target": 0.9}, 1.0) is None  # under 1R of room left
    assert td.plan_for({**DS, "stop": 1.005}, 1.0) is None   # stop under 1% away


def test_with_plan_overlays_entry_stop_target_and_hold(monkeypatch):
    monkeypatch.setattr(td.tdb, "get_state", lambda k: json.dumps(
        {"entry": 1.0, "stop": 1.15, "target": 0.7, "max_hold": 30,
         "at": "2026-11-23T06:01:30"}) if k == "plan:7" else None)
    t = td.with_plan({"id": 7, "fired_price": 0.9, "stop": 1.4, "tp": 0.5,
                      "fired_at": "2026-11-23T00:06:10", "condition_json": '{"tp": 0.5}'})
    assert (t["fired_price"], t["stop"], t["target"], t["tp"]) == (1.0, 1.15, 0.7, 0.7)
    assert json.loads(t["condition_json"]) == {"tp": 0.7, "max_hold": 30}
    assert td.with_plan({"id": 8, "fired_price": 2.0})["fired_price"] == 2.0


def test_graded_from_the_5pm_hour_not_the_11am_fire(monkeypatch):
    monkeypatch.setattr(td.tdb, "get_state", lambda k: json.dumps(
        {"entry": 1.0, "stop": 1.15, "target": 0.7, "max_hold": 30, "at": "2026-11-23T06:01:30"}))
    assert td.with_plan({"id": 1, "fired_at": "2026-11-23T00:06:10"})["fired_at"] == "2026-11-23T06:00:00"


def test_plans_saved_only_after_delivery(monkeypatch):
    saved = []
    monkeypatch.setattr(td.tdb, "set_state", lambda k, v: saved.append(k))
    monkeypatch.setattr(td.tdb, "set_outcome", lambda i, p: saved.append(("outcome", i, p["outcome"])))
    monkeypatch.setattr(td, "pending", lambda now=None: [
        {"id": 5, "symbol": "A-USD", "direction": "short", "setup_label": "Distribution Short", "condition_json": "{\"quiet\": true, \"atr\": 0.05}",
         "stop": 1.3, "fired_at": "2026-11-23T00:06:00"},
        {"id": 6, "symbol": "B-USD", "direction": "short", "setup_label": "Distribution Short",
         "stop": 0.9, "fired_at": "2026-11-23T00:06:00"}])
    import datetime as dt
    msg, recs = td.prepare(dt.datetime(2026, 11, 23, 6, 1), prices={"A-USD": 1.0, "B-USD": 1.0})
    assert "Short A" in msg and "B" in msg.split("Skipped")[1] and saved == []
    td.commit(recs)
    assert "plan:5" in saved and "digest_skip:6" in saved and ("outcome", 6, "skipped") in saved


def test_stale_fire_is_skipped(monkeypatch):
    monkeypatch.setattr(td, "pending", lambda now=None: [
        {"id": 9, "symbol": "A-USD", "direction": "short", "setup_label": "Distribution Short",
         "stop": 1.3, "fired_at": "2026-11-21T00:06:00"}])
    import datetime as dt
    msg, recs = td.prepare(dt.datetime(2026, 11, 23, 6, 1), prices={"A-USD": 1.0})
    assert recs == [("skip", 9, None)]


def test_awaiting_only_quiet_uncapped_untaken_recent(monkeypatch):
    import datetime as dt
    monkeypatch.setattr(td.tdb, "get_state", lambda k: None)
    now = dt.datetime(2026, 11, 23, 6, 0)
    base = {"id": 1, "outcome": None, "fired_at": "2026-11-23T00:06:00",
            "condition_json": json.dumps({"quiet": True})}
    assert td.awaiting_digest(base, now)
    assert not td.awaiting_digest({**base, "condition_json": "{}"}, now)            # old instant alert
    assert not td.awaiting_digest({**base, "condition_json": json.dumps(
        {"quiet": True, "basket_cap": True})}, now)                                  # capped: graded as paper
    assert not td.awaiting_digest({**base, "taken": True}, now)
    assert not td.awaiting_digest({**base, "fired_at": "2026-11-20T00:06:00"}, now)  # over 48h


def test_with_plan_trailing_keeps_trail_on_and_tp_in_tp(monkeypatch):
    monkeypatch.setattr(td.tdb, "get_state", lambda k: json.dumps(
        {"entry": 1.0, "stop": 1.3, "target": 0.4, "trail": 0.15, "max_hold": 60,
         "at": "2026-11-23T06:01:30"}))
    t = td.with_plan({"id": 3, "fired_at": "2026-11-23T00:06:10", "condition_json": "{}"})
    c = json.loads(t["condition_json"])
    assert t["target"] is None and t["tp"] == 0.4 and c["native_trail"] and c["max_hold"] == 60


def test_three_slots_each_once(monkeypatch):
    import datetime as dt
    from triggers import autoscan
    state = {}
    monkeypatch.setattr(autoscan.tdb, "get_state", lambda k: state.get(k))
    utc = dt.timezone.utc
    # 3:30pm Sydney (AEDT, UTC+11) = 04:30 UTC; 7pm = 08:00 UTC
    k, slot = autoscan._digest_due(dt.datetime(2026, 11, 24, 4, 40, tzinfo=utc))
    assert k == "digest:15:30" and slot.hour == 4 and slot.minute == 30
    state[k] = slot.isoformat()
    assert autoscan._digest_due(dt.datetime(2026, 11, 24, 5, 0, tzinfo=utc)) is None
    k2, _ = autoscan._digest_due(dt.datetime(2026, 11, 24, 8, 5, tzinfo=utc))
    assert k2 == "digest:19:00"
    assert autoscan._digest_due(dt.datetime(2026, 11, 24, 12, 0, tzinfo=utc)) is None   # past catch up
