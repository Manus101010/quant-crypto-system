from __future__ import annotations
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import watcher  # noqa: E402
from guard.ledger import Ledger  # noqa: E402

FIX = json.loads(watcher.DEFAULT_FIXTURE.read_text())
# 02:00 UTC = 13:00 Sydney: after the 07:00 slot, before 15:30
NOON = datetime(2026, 10, 27, 2, 0, tzinfo=timezone.utc)


def _run(snap, mem=None, regime=None, now=NOON, **kw):
    mem = mem or watcher.MemState()
    sent = []
    res = watcher.poll(snap, ledger=Ledger(mem.get, mem.set), state_get=mem.get,
                       state_set=mem.set, send=sent.append, regime=regime, now=now, **kw)
    return res, sent, mem


def test_normalise_skips_grid_symbol_positions():
    snap = copy.deepcopy(FIX)
    snap["positions"].append({"symbol": "DOODUSDT", "side": "Sell", "size": "210560",
                              "avgPrice": "0.002096", "markPrice": "0.0020221"})
    items = watcher.normalise(snap)
    assert [(i["kind"], i["symbol"]) for i in items] == [("grid", "DOODUSDT"), ("position", "HYPEUSDT")]
    g = items[0]
    assert g["side"] == "short" and g["grids"] == 200 and g["hi"] == 0.0025


def test_fixture_poll_alerts():
    res, sent, mem = _run(copy.deepcopy(FIX))
    keys = {a["key"] for a in res["alerts"]}
    assert "nostop:fixture-dood" in keys and "nostop:HYPEUSDT:short" in keys
    assert any(k.startswith("unissued:grid:DOODUSDT") for k in keys)
    assert "openrisk" in keys                  # no stops => full margins count as risk
    assert res["open_risk"] > 125
    # 07:00 summary is due at 13:00 Sydney and is sent once
    assert res["summary"] and "Guard summary" in res["summary"]
    res2, sent2, _ = _run(copy.deepcopy(FIX), mem=mem)
    assert sent2 == []                          # deduped: nothing new, summary already sent


def test_grid_edge_and_liq_alerts():
    snap = copy.deepcopy(FIX)
    g = snap["grids"][0]
    g["mark_price"] = "0.00235"                # 6.4% under the top
    g["liquidation_price"] = "0.0026"          # 10.6% away < 15%
    g["stop_loss_price"] = "0.00252"
    res, sent, _ = _run(snap)
    keys = {a["key"] for a in res["alerts"]}
    assert "edgetop:fixture-dood" in keys
    assert "liq:fixture-dood" in keys
    assert "nostop:fixture-dood" not in keys


def test_daily_cap_and_regime_flip():
    snap = copy.deepcopy(FIX)
    snap["closed_pnl"] = [{"symbol": "SOLUSDT", "closedPnl": "-130", "orderId": "a"}]
    mem = watcher.MemState()
    mem.set("guard:btc_regime", "RISK-ON")
    res, sent, _ = _run(snap, mem=mem, regime={"label": "RISK-OFF", "detail": "x"})
    keys = {a["key"] for a in res["alerts"]}
    assert any(k.startswith("cap:") for k in keys)
    assert any(k.startswith("regime:RISK-OFF") for k in keys)
    assert any("Daily loss cap hit" in s for s in sent)


def test_issued_grid_not_tagged():
    snap = copy.deepcopy(FIX)
    mem = watcher.MemState()
    L = Ledger(mem.get, mem.set)
    L.issue({"symbol": "DOODUSDT", "type": "grid", "mode": "short", "lo": 0.0016, "hi": 0.0025,
             "grids": 200, "investment": 263.8642}, NOON)
    res, _, _ = _run(snap, mem=mem)
    keys = {a["key"] for a in res["alerts"]}
    assert not any(k.startswith("unissued:grid:DOODUSDT") for k in keys)


def test_due_summary_slots():
    assert watcher.due_summary(datetime(2026, 10, 26, 19, 0, tzinfo=timezone.utc), set()) is None  # 06:00
    s = watcher.due_summary(datetime(2026, 10, 26, 20, 5, tzinfo=timezone.utc), set())            # 07:05
    assert s == "2026-10-27 07:00"
    assert watcher.due_summary(datetime(2026, 10, 26, 20, 5, tzinfo=timezone.utc), {s}) is None
    assert watcher.due_summary(datetime(2026, 10, 27, 10, 40, tzinfo=timezone.utc), set()) == "2026-10-27 21:30"


def test_main_dry_run(capsys):
    assert watcher.main(["--once", "--dry-run", "--summary"]) == 0
    out = capsys.readouterr().out
    assert "No stop" in out and "Guard summary" in out


def test_load_snapshot_live_uses_client():
    c = MagicMock()
    c.wallet_balance.return_value = {"totalEquity": "1"}
    c.positions.return_value = []
    c.futures_grid_bots.return_value = []
    c.closed_pnl.return_value = []
    snap = watcher.load_snapshot(client=c)
    assert snap["wallet"]["totalEquity"] == "1"
    c.positions.assert_called_once_with("linear", "USDT")


def test_registered_grid_position_not_revenge_and_detail_error_alert():
    # Bot detail failed (e.g. read only key not allowed) -> only the linear position is seen.
    snap = copy.deepcopy(FIX)
    snap["grids"] = []
    snap["grid_errors"] = [{"bot_id": "777", "kind": "permission", "error": "retCode 10005"}]
    snap["positions"].append({"symbol": "DOODUSDT", "side": "Sell", "size": "210560",
                              "avgPrice": "0.002096", "markPrice": "0.0020221",
                              "liqPrice": "0.0031673", "positionIM": "263.86"})
    mem = watcher.MemState()
    Ledger(mem.get, mem.set).add_grid_bot("777", "DOOD")
    res, sent, _ = _run(snap, mem=mem)
    keys = {a["key"] for a in res["alerts"]}
    assert not any("DOODUSDT" in k and k.startswith("unissued") for k in keys)
    assert "griderr:777:permission" in keys
    assert "nostop:DOODUSDT:short" in keys       # still watched as a plain position
    assert any(k.startswith("unissued:position:HYPEUSDT") for k in keys)
    dood = [i for i in res["items"] if i["symbol"] == "DOODUSDT"][0]
    assert dood["kind"] == "grid_position"


def test_registry_ids_merge():
    mem = watcher.MemState()
    L = Ledger(mem.get, mem.set)
    L.add_grid_bot("1", "dood")
    L.add_grid_bot("2")
    assert L.grid_bot_ids(["2", "3"]) == ["1", "2", "3"]
    assert L.grid_bots()["1"]["symbol"] == "DOODUSDT"
    assert L.remove_grid_bot("2") and not L.remove_grid_bot("9")
