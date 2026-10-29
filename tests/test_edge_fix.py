"""Offline tests for the 28 Oct 2026 live edge fix (docs/edge_fix/CHANGES.md).

No network: every exchange / Telegram / feature call is monkeypatched, and the
trigger store is a temporary SQLite file.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("yfinance", types.ModuleType("yfinance"))   # scanner imports it

import config  # noqa: E402
from skills import new_setups  # noqa: E402
from skills import scanner  # noqa: E402
from triggers import db as tdb  # noqa: E402
from triggers import outcomes  # noqa: E402
from triggers import scan as tscan  # noqa: E402
import monitor  # noqa: E402

DS, DBF, BDS = "Distribution Short", "Downtrend Bounce Fade", "Breakdown Short (55d low)"


@pytest.fixture
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(tdb, "DB_PATH", tmp_path / "trading.db")
    tdb.init_db()
    return tmp_path / "trading.db"


def _ds_frame():
    """Synthetic coin that runs up then goes quiet: fires Distribution Short."""
    rng = np.random.default_rng(0)
    n = 320
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    r = np.concatenate([rng.normal(0.006, 0.04, 230), rng.normal(-0.0015, 0.004, n - 230)])
    c = 100 * np.exp(np.cumsum(r))
    h = c * (1 + np.abs(rng.normal(0, 0.01, n)))
    lo = c * (1 - np.abs(rng.normal(0, 0.01, n)))
    df = pd.DataFrame({"open": c, "high": h, "low": lo, "close": c, "volume": 1e5}, index=idx)
    btc = pd.Series(np.linspace(50000, 90000, n), index=idx)
    return df, btc


# ── 1. Distribution Short 2R take profit ──────────────────────────────────────
def test_detect_sets_tp_r_only_on_distribution_short():
    df, btc = _ds_frame()
    out = new_setups.detect(df, btc)
    ds = out["label"] == DS
    assert ds.any()
    assert (out.loc[ds, "tp_r"] == 2.0).all()
    assert out.loc[~ds, "tp_r"].isna().all()


def test_latest_carries_tp_r_and_signal_close():
    df, btc = _ds_frame()
    first = new_setups.detect(df, btc).query("label == @DS").index[0]
    sig = new_setups.latest(df.loc[:first], btc)
    assert sig["label"] == DS and sig["tp_r"] == 2.0
    assert sig["close"] == pytest.approx(float(df.loc[first, "close"]))


def test_restop_math():
    stop, tp = new_setups.restop(100.0, 2.0, 3.5, 2.0, short=True)
    assert stop == pytest.approx(107.0) and tp == pytest.approx(86.0)
    stop, tp = new_setups.restop(100.0, 2.0, 3.5, None, short=False)
    assert stop == pytest.approx(93.0) and tp is None
    assert new_setups.restop(100.0, 2.0, None, 2.0) == (None, None)     # DBF: level stop


def test_new_setup_trade_restops_from_live_price_and_sets_tp():
    ns = {"label": DS, "stop": 120.0, "target": None, "trail_atr": 3.5, "max_hold": 60,
          "atr": 4.0, "tp_r": 2.0, "close": 100.0}
    tr = scanner.new_setup_trade(ns, 102.0)
    p = tr["plan"]
    assert p["entry"] == 102.0 and p["signal_close"] == 100.0
    assert p["stop"] == pytest.approx(102.0 + 14.0)
    assert p["tp"] == pytest.approx(102.0 - 28.0)
    assert p["signal_stop"] == 120.0
    assert "take profit" in tr["target"] and "2R" in tr["target"]


def test_simulate_short_hits_tp_before_trail(monkeypatch):
    t = {"id": 1, "symbol": "X-USD", "setup_label": DS, "direction": "short",
         "fired_at": "2026-10-01T01:00:00", "fired_price": 100.0, "stop": 107.0,
         "target": None, "tp": None,
         "condition_json": json.dumps({"atr": 2.0, "tp": 86.0, "trail_atr": 3.5})}
    idx = pd.to_datetime(["2026-10-02", "2026-10-03", "2026-10-04"])
    df = pd.DataFrame({"open": [100, 96, 90], "high": [101, 97, 91], "low": [95, 90, 85],
                       "close": [96, 91, 86]}, index=idx)
    p = outcomes._simulate(t, df)
    assert p["outcome"] == "target" and p["exit_price"] == pytest.approx(86.0)
    assert p["r_multiple"] == pytest.approx(2.0)


def test_trade_tp_prefers_column_then_condition_json():
    assert outcomes.trade_tp({"tp": 5.0, "condition_json": json.dumps({"tp": 6.0})}) == 5.0
    assert outcomes.trade_tp({"tp": None, "condition_json": json.dumps({"tp": 6.0})}) == 6.0
    assert outcomes.trade_tp({"condition_json": None}) is None


# ── 2. trail from the stored signal ATR ───────────────────────────────────────
def test_bybit_trail_entry_for_distribution_short():
    assert config.BYBIT_TRAIL[DS] == {"k_atr": 3.5, "activate_r": 0.0}


def _trail_trade(cond):
    return {"id": 2, "symbol": "X-USD", "setup_label": DS, "direction": "short",
            "fired_at": "2026-10-01T01:00:00", "fired_price": 100.0, "stop": 120.0,
            "target": None, "condition_json": json.dumps(cond)}


def test_simulate_trails_at_3_5_signal_atr():
    idx = pd.to_datetime(["2026-10-02", "2026-10-03"])
    df = pd.DataFrame({"open": [99, 92], "high": [95, 98], "low": [90, 91],
                       "close": [92, 97]}, index=idx)
    # stored signal ATR 2 -> trail 7 off the best low 90 -> 97, hit on day 2
    p = outcomes._simulate(_trail_trade({"atr": 2.0}), df)
    assert p["outcome"] == "trail" and p["exit_price"] == pytest.approx(97.0)
    assert p["r_multiple"] == pytest.approx(0.15)
    # no stored ATR: falls back to risk / stop_mult (20 / 3.5) x 3.5 = 20 -> still open
    p2 = outcomes._simulate(_trail_trade({}), df)
    assert p2["outcome"] is None and p2["trail_stop"] == pytest.approx(110.0)


# ── 3. entry / stop alignment and drift bounds ────────────────────────────────
def _ds_row(price, signal_close=100.0, atr=2.0, label=DS, ticker="AAA-USD"):
    ns = {"label": label, "stop": signal_close + 3.5 * atr, "target": None, "trail_atr": 3.5,
          "max_hold": 60, "atr": atr, "tp_r": 2.0, "close": signal_close}
    return {"ticker": ticker, "price": price, "setup_label": label, "setup_category": "momentum",
            "conviction": 80, "trade": scanner.new_setup_trade(ns, price),
            "fwd_flags": {"liquid_5m_180d": True, "btc_below_50d": False}}


def test_armed_plan_restops_and_blocks_drift():
    ok = tscan._armed_plan(_ds_row(101.0))
    assert ok["stop"] == pytest.approx(108.0) and ok["tp"] == pytest.approx(87.0)
    assert ok["drift_blocked"] is None and ok["rr"] == 2.0
    assert tscan._armed_plan(_ds_row(103.5))["drift_blocked"] == "bounced"
    assert tscan._armed_plan(_ds_row(96.5))["drift_blocked"] == "moved"


def test_evaluate_enter_now_short_drift_and_stop_cap():
    cond = {"kind": "enter_now_short", "entry": 100.5, "stop": 107.5, "target": None,
            "max_drift": 0.03, "max_drift_up": 0.03, "signal_close": 100.0,
            "atr": 2.0, "trail_atr": 3.5, "tp_r": 2.0, "max_stop_pct": 50.0}
    trg = {"condition_json": json.dumps(cond), "condition_type": "enter_now_short",
           "condition_value": 100.5}
    ind = lambda p: {"price": p, "prev": p, "rsi2_now": 50, "rsi2_prev": 50, "rsi14_now": 50}  # noqa: E731
    assert monitor._evaluate(trg, ind(101.0))[0] == "fire"
    v, why = monitor._evaluate(trg, ind(103.2))
    assert v == "invalidate" and "bounced" in why
    assert monitor._evaluate(trg, ind(96.9))[0] == "invalidate"
    cond2 = {**cond, "max_stop_pct": 5.0}                 # 3.5 x 2 / 101 = 6.9% > 5%
    trg2 = {**trg, "condition_json": json.dumps(cond2)}
    v, why = monitor._evaluate(trg2, ind(101.0))
    assert v == "invalidate" and "re-anchored" in why


def test_evaluate_upper_bound_only_for_restopped_plans():
    """Review fix: the 3% upper drift bound applies only where the scan stored it
    (re-stopped Distribution Short plans). Old triggers and DBF (level stop, no
    upper bound in its research) keep the pre-change behaviour."""
    ind = {"price": 103.5, "prev": 103.5, "rsi2_now": 50, "rsi2_prev": 50, "rsi14_now": 50}
    old = {"kind": "enter_now_short", "entry": 100.0, "stop": 130.0, "target": None,
           "max_drift": 0.03}
    assert monitor._evaluate({"condition_json": json.dumps(old)}, ind)[0] == "fire"
    dbf = {**old, "signal_close": 100.0, "atr": 2.0, "trail_atr": None, "max_drift_up": None}
    assert monitor._evaluate({"condition_json": json.dumps(dbf)}, ind)[0] == "fire"
    ds = {**old, "signal_close": 100.0, "atr": 2.0, "trail_atr": 3.5, "max_drift_up": 0.03,
          "max_stop_pct": 50.0}
    assert monitor._evaluate({"condition_json": json.dumps(ds)}, ind)[0] == "invalidate"


def test_restop_rejects_non_finite():
    from skills.new_setups import restop
    assert restop(100.0, float("nan"), 3.5, 2.0) == (None, None)
    assert restop(100.0, 2.0, float("inf"), 2.0) == (None, None)
    assert restop(None, 2.0, 3.5, 2.0) == (None, None)


def test_fired_today_counts_parses_trimmed_microseconds(monkeypatch):
    import datetime as dt
    rows = [{"fired_at": "2026-10-28T01:02:03.12345+00:00", "direction": "short",
             "condition_json": "{}"},
            {"fired_at": "2026-10-28T01:02:03", "direction": "short", "condition_json": "{}"}]
    monkeypatch.setattr(monitor.tdb, "get_fired_trades", lambda open_only=False: rows)
    now = dt.datetime(2026, 10, 28, 2, 0, tzinfo=dt.timezone.utc)
    assert monitor._fired_today_counts(now)["short"] == 2


def test_fire_plan_reanchors_stop_and_tp():
    trg = {"direction": "short", "condition_json": json.dumps(
        {"kind": "enter_now_short", "atr": 2.0, "trail_atr": 3.5, "tp_r": 2.0})}
    fp = monitor._fire_plan(trg, 98.0)
    assert fp["stop"] == pytest.approx(105.0) and fp["tp"] == pytest.approx(84.0)
    dbf = {"direction": "short", "condition_json": json.dumps(
        {"kind": "enter_now_short", "atr": 2.0, "trail_atr": None})}
    assert monitor._fire_plan(dbf, 98.0) == {}


# ── 4. retired setups ─────────────────────────────────────────────────────────
def test_retired_setups_never_validated(monkeypatch):
    from backtesting import crypto_validation as cv
    stats = {BDS: {"profit_factor": 3.0, "n": 500}, DS: {"profit_factor": 2.0, "n": 778}}
    assert cv.validated_setups(stats) == {DS}
    monkeypatch.setattr(cv, "load_validation", lambda: {"validated": [BDS, DS]})
    assert cv.validated_labels() == {DS}
    assert BDS in config.RETIRED_SETUPS


def _patch_scan_env(monkeypatch, rows):
    import utils.breadth
    import utils.exchange
    from backtesting import crypto_validation as cv
    monkeypatch.setattr(tscan, "get_top_crypto", lambda n: [r["ticker"] for r in rows])
    monkeypatch.setattr(tscan, "run_crypto_scan", lambda **kw: pd.DataFrame(rows))
    monkeypatch.setattr(cv, "validated_labels", lambda: {DS, BDS, DBF})
    monkeypatch.setattr(utils.exchange, "get_funding_rates", lambda syms: {})
    monkeypatch.setattr(utils.breadth, "long_gate", lambda: (True, ""))


def test_scan_does_not_arm_retired_and_stores_plan_extras(tmpdb, monkeypatch):
    bds = {"ticker": "BBB-USD", "price": 1.0, "setup_label": BDS, "setup_category": "momentum",
           "conviction": 95, "atr_14": 0.02,
           "trade": {"action": "SELL", "entry": "Short near $1.0000", "stop": "$1.05",
                     "target": "$0.85"}}
    rows = [_ds_row(100.5, ticker="AAA-USD"), _ds_row(104.0, ticker="CCC-USD"), bds]
    _patch_scan_env(monkeypatch, rows)
    res = tscan.run_scan_and_arm(top_n=5, max_stop_pct=25.0)
    armed = {a["symbol"] for a in res["armed"]}
    assert armed == {"AAA-USD"}                       # BDS retired, CCC bounced 4%
    assert BDS in res["gated_out_setups"]
    assert any(w["setup_label"] == BDS and w["retired"] for w in res["watch_only"])
    trg = tdb.get_triggers("active")[0]
    cond = json.loads(trg["condition_json"])
    assert cond["signal_close"] == 100.0 and cond["atr"] == 2.0 and cond["tp_r"] == 2.0
    assert cond["tp"] == pytest.approx(100.5 - 14.0)
    assert cond["max_drift_up"] == pytest.approx(0.03)
    assert cond["max_stop_pct"] == 50.0
    assert cond["fwd"]["liquid_5m_180d"] is True
    assert trg["stop"] == pytest.approx(107.5)


# ── 6. forensics bugs ─────────────────────────────────────────────────────────
def test_setup_base_has_research_shorts():
    assert scanner._SETUP_BASE[DS] > scanner._SETUP_BASE["Momentum Runner"]
    assert scanner._SETUP_BASE[DBF] >= 60
    assert scanner.conviction_score(DS, 50, 0, None, None, None, 1.0, "momentum") > 25


def test_drop_forming_bar():
    idx = pd.date_range("2026-10-25", periods=4, freq="D")
    df = pd.DataFrame({"close": [1, 2, 3, 4]}, index=idx)
    now = pd.Timestamp("2026-10-28 05:00", tz="UTC")
    assert len(scanner._drop_forming(df, now)) == 3
    assert len(scanner._drop_forming(df.iloc[:3], now)) == 3


def test_scan_classifies_on_closed_bar_and_keeps_live_price(monkeypatch):
    import utils.btc_regime as br
    monkeypatch.setattr(br, "btc_return", lambda n, force=False: None)
    monkeypatch.setattr(br, "btc_daily_close", lambda force=False: None)
    seen = {}

    def fake_classify(price, *a, **k):
        seen["price"] = price
        return "Confirmed Uptrend", "desc", "momentum"
    monkeypatch.setattr(scanner, "classify_setup", fake_classify)
    today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
    idx = pd.date_range(end=today, periods=120, freq="D")
    c = np.linspace(1, 2, 120)
    c[-1] = 5.0                                        # forming bar spikes
    df = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                       "volume": 1e7}, index=idx)
    out = scanner._run_from_bybit({"X-USD": df}, ["X-USD"],
                                  scanner.ScanCriteria(min_price=0.0, above_sma200=False,
                                                       above_sma50=False, min_volume_usd_m=0))
    assert seen["price"] == pytest.approx(c[-2])       # classified on the closed bar
    row = out.iloc[0]
    assert row["price"] == pytest.approx(5.0)          # entries price off the live bar
    assert row["close_price"] == pytest.approx(c[-2])
    assert row["fwd_flags"]["listed_days_min"] == 119


def test_sub_cent_price_round_trip():
    p = 0.000012345
    assert scanner._fmt_p(p) in ("$0.00001234", "$0.00001235")   # 4 significant digits
    assert abs(tscan._num(scanner._fmt_p(p)) / p - 1) < 5e-4
    plan = tscan._armed_plan(_ds_row(p, signal_close=p, atr=p * 0.05))
    assert plan["entry"] == p                           # numeric, never parsed from text
    assert plan["stop"] == pytest.approx(p * (1 + 3.5 * 0.05))


def test_close_alert_reports_actual_dollar_risk():
    # 9% stop: worst 9.45% -> leverage floor int(0.25 / 0.0945) = 2 -> $100 position
    pos = outcomes.planned_position(100.0, 109.0)
    assert pos["leverage"] == 2 and pos["risk_usd"] == pytest.approx(9.0)
    t = {"symbol": "BTC-USD", "fired_price": 100.0, "stop": 109.0, "setup_label": DS}
    txt = outcomes._close_text(t, {"r_multiple": -1.0, "outcome": "stop",
                                   "exit_price": 109.0, "bars_held": 3})
    assert "$9.00" in txt and "$12" not in txt and "2x" in txt
    wide = outcomes.planned_position(100.0, 130.0)     # 30% stop: 1x, smaller position
    assert wide["leverage"] == 1 and wide["margin"] < config.POSITION_MARGIN_USD
    assert wide["worst_loss"] == pytest.approx(config.RISK_PER_TRADE_USD)


# ── storage ───────────────────────────────────────────────────────────────────
def test_sqlite_mark_fired_writes_plan_extras(tmpdb):
    tid = tdb.add_trigger("X-USD", "enter_now_short", 100.0, condition_json="{}",
                          setup_label=DS, direction="short", stop=107.0)
    tdb.mark_fired(tid, 101.0, note="r", extra={"stop": 108.0, "tp": 87.0,
                                                "condition_json": '{"basket_cap": true}',
                                                "status": "hacked"})
    t = tdb.get_fired_trades()[0]
    assert t["stop"] == 108.0 and t["tp"] == 87.0 and t["status"] == "fired"
    assert outcomes.is_basket_capped(t)


class _FakeQuery:
    def __init__(self, client, patch):
        self.client, self.patch = client, patch

    def eq(self, *a):
        return self

    def execute(self):
        self.client.calls.append(dict(self.patch))
        if "tp" in self.patch and not self.client.has_tp:
            raise Exception("{'code': 'PGRST204', 'message': \"Could not find the 'tp' "
                            "column of 'triggers' in the schema cache\"}")
        return types.SimpleNamespace(data=[])


class _FakeClient:
    def __init__(self, has_tp):
        self.has_tp, self.calls = has_tp, []

    def table(self, name):
        return types.SimpleNamespace(update=lambda patch: _FakeQuery(self, patch))


def test_supabase_tolerates_missing_tp_column(monkeypatch):
    from triggers import supastore
    fake = _FakeClient(has_tp=False)
    monkeypatch.setattr(supastore, "_client", fake)
    monkeypatch.setattr(supastore, "_missing_cols", set())
    supastore.mark_fired(1, 100.0, note="x", extra={"stop": 107.0, "tp": 86.0})
    assert fake.calls[-1]["stop"] == 107.0 and "tp" not in fake.calls[-1]
    n = len(fake.calls)
    supastore.set_outcome(1, {"tp": 86.0, "trail_stop": 105.0})
    assert len(fake.calls) == n + 1 and "tp" not in fake.calls[-1]   # skipped, no retry
    ok = _FakeClient(has_tp=True)
    monkeypatch.setattr(supastore, "_client", ok)
    monkeypatch.setattr(supastore, "_missing_cols", set())
    supastore.mark_fired(2, 100.0, extra={"tp": 86.0})
    assert ok.calls[-1]["tp"] == 86.0 and len(ok.calls) == 1


def test_supabase_other_errors_still_raise(monkeypatch):
    from triggers import supastore

    class Boom(_FakeClient):
        def table(self, name):
            def upd(patch):
                q = _FakeQuery(self, patch)
                q.execute = lambda: (_ for _ in ()).throw(Exception("network down"))
                return q
            return types.SimpleNamespace(update=upd)
    monkeypatch.setattr(supastore, "_client", Boom(True))
    monkeypatch.setattr(supastore, "_missing_cols", set())
    with pytest.raises(Exception, match="network down"):
        supastore.mark_fired(1, 100.0, extra={"tp": 1.0})


# ── 7 + 8. basket cap and forward-test flags through a monitor poll ───────────
def _poll_env(monkeypatch, sent):
    import guard.ledger
    import utils.btc_regime
    import utils.events
    import features.derivs
    import features.snapshot
    from utils import exchange, telegram
    monkeypatch.setattr(outcomes, "update_open_trades", lambda notify=True: {})
    idx = pd.date_range(end=pd.Timestamp.now("UTC").tz_localize(None).normalize(), periods=60)
    c = 100.0 + np.sin(np.arange(60)) * 0.5
    c[-1] = 100.0                                    # fire price
    df = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c,
                       "volume": 1e6}, index=idx)
    monkeypatch.setattr(exchange, "get_ohlcv_batch",
                        lambda syms, **kw: {s: df for s in syms})
    monkeypatch.setattr(exchange, "in_perp_universe", lambda s, v: True)
    monkeypatch.setattr(telegram, "send_message", lambda text, **kw: sent.append(text) or True)
    monkeypatch.setattr(telegram, "is_configured", lambda: True)
    monkeypatch.setattr(features.snapshot, "snapshot", lambda *a, **k: {"oi_chg_24h": 1.0})
    monkeypatch.setattr(features.snapshot, "alert_line", lambda s: "")
    monkeypatch.setattr(features.derivs, "oi_change_okx", lambda s, h=72: 4.2)
    monkeypatch.setattr(utils.btc_regime, "get_btc_regime",
                        lambda force=False: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(utils.events, "coin_warning", lambda s, d=7: "")
    monkeypatch.setattr(utils.events, "macro_warning", lambda d=3: "")
    issued = []

    class FakeLedger:
        def issue(self, *a, **k):
            issued.append(a)

        def day(self):
            return {}

        def max_loss_for_next(self):
            return None
    monkeypatch.setattr(guard.ledger, "Ledger", FakeLedger)
    return issued


def _arm_ds(sym):
    cond = {"kind": "enter_now_short", "entry": 100.0, "stop": 107.0, "target": None,
            "max_drift": 0.03, "max_drift_up": 0.03, "signal_close": 100.0, "atr": 2.0,
            "trail_atr": 3.5, "tp_r": 2.0, "tp": 86.0, "max_stop_pct": 50.0,
            "fwd": {"liquid_5m_180d": False, "btc_below_50d": True}}
    return tdb.add_trigger(sym, "enter_now_short", 100.0, condition_json=json.dumps(cond),
                           setup_label=DS, direction="short", entry=100.0, stop=107.0,
                           expires_at="2999-01-01")


def test_basket_cap_limits_tradeable_fires_per_direction(tmpdb, monkeypatch):
    sent = []
    issued = _poll_env(monkeypatch, sent)
    # one short already alerted earlier today (Sydney) and one yesterday
    old = _arm_ds("OLD-USD")
    tdb.mark_fired(old, 100.0)
    yday = _arm_ds("YDAY-USD")
    tdb.mark_fired(yday, 100.0)
    with tdb._conn() as con:
        con.execute("UPDATE triggers SET fired_at=? WHERE id=?",
                    ((datetime.utcnow() - timedelta(days=2)).isoformat(), yday))
    ids = [_arm_ds(f"C{i}-USD") for i in range(4)]
    res = monitor.poll_once()
    assert res["fired"] == 4 and res["basket_capped"] == 2
    rows = {t["id"]: t for t in tdb.get_fired_trades()}
    capped = [i for i in ids if outcomes.is_basket_capped(rows[i])]
    assert len(capped) == 2                            # 1 earlier + 2 new = cap 3
    assert sum("basket cap" in s for s in sent) == 2
    assert len(issued) == 2                            # guard sees tradeable alerts only
    for i in ids:
        t = rows[i]
        assert t["stop"] == pytest.approx(107.0)       # re-anchored at fire price 100
        assert t["tp"] == pytest.approx(86.0)
        fwd = json.loads(t["condition_json"])["fwd"]
        assert fwd["oi_chg_72h"] == 4.2 and fwd["oi_3d_rising"] is True
        assert fwd["btc_below_50d"] is True and fwd["liquid_5m_180d"] is False
    tradeable_txt = [s for s in sent if "basket cap" not in s]
    assert any("Take profit" in s and "$86.00" in s for s in tradeable_txt)
    assert any("Take-profit" in s for s in tradeable_txt)          # Bybit order form
    feats = json.loads(tdb.get_state(f"features:{ids[0]}"))
    assert feats["fwd_oi_3d_rising"] is True


def test_live_stats_reports_basket_cap_separately(tmpdb, monkeypatch):
    a, b = _arm_ds("A-USD"), _arm_ds("B-USD")
    tdb.mark_fired(a, 100.0)
    tdb.mark_fired(b, 100.0, extra={"condition_json": json.dumps({"basket_cap": True})})
    tdb.set_outcome(a, {"outcome": "stop", "r_multiple": -1.0})
    tdb.set_outcome(b, {"outcome": "target", "r_multiple": 2.0})
    st = outcomes.live_stats()
    assert st["total"]["n"] == 2 and st["total"]["total_r"] == pytest.approx(1.0)
    assert st["tradeable"]["total_r"] == pytest.approx(-1.0)
    assert st["basket_cap"]["n"] == 1


def test_fwd_flags_liquidity_rule():
    idx = pd.date_range("2025-01-01", periods=200)
    dfc = pd.DataFrame({"close": 1.0}, index=idx)
    f = scanner.fwd_flags(dfc, pd.Series(6e6, index=idx), True)
    assert f["liquid_5m_180d"] is True and f["btc_below_50d"] is True
    assert scanner.fwd_flags(dfc.iloc[:150], pd.Series(6e6, index=idx[:150]),
                             None)["liquid_5m_180d"] is False
    assert scanner.fwd_flags(dfc, pd.Series(4e6, index=idx), False)["liquid_5m_180d"] is False


# ── 5. validation file ────────────────────────────────────────────────────────
def test_validation_file_distribution_short_recomputed():
    v = json.loads((Path(config.DATA_DIR) / "crypto_validation.json").read_text())
    s = v["stats"][DS]
    assert s["n"] == 778 and s["profit_factor"] == 2.01 and s["expectancy_r"] == 0.312
    assert s["oos_tp2r"]["n"] == 292 and s["oos_tp2r"]["profit_factor"] == 2.36
    assert "shorts.md" in s["note"]
    assert BDS not in v["validated"] and DS in v["validated"]


def test_revalidate_never_auto_deactivates_research_setup(monkeypatch):
    """Review fix: the old per-bar harness must not switch off Distribution Short
    (validated on the shorts study harness); it is reported instead."""
    import revalidate as rv
    stats = {"Distribution Short": {"n": 40, "profit_factor": 0.6, "win_rate": 0.4},
             "Squeeze Breakout": {"n": 30, "profit_factor": 0.6, "win_rate": 0.3}}
    monkeypatch.setattr(rv, "validate_per_setup", lambda **k: {"stats": stats})
    monkeypatch.setattr(rv, "validated_labels",
                        lambda: {"Distribution Short", "Squeeze Breakout"})
    monkeypatch.setattr(rv.tdb, "init_db", lambda: None)
    monkeypatch.setattr(rv.tdb, "get_deactivated", lambda: set())
    monkeypatch.setattr(rv.tdb, "last_edge_action", lambda s: None)
    off = []
    monkeypatch.setattr(rv.tdb, "deactivate_setup", lambda s, *a, **k: off.append(s))
    monkeypatch.setattr(rv.tdb, "add_edge_history", lambda rows: None)
    sent = []
    monkeypatch.setattr(rv.telegram, "is_configured", lambda: True)
    monkeypatch.setattr(rv.telegram, "send_message", lambda m: sent.append(m))
    out = rv.run_revalidation()
    assert off == ["Squeeze Breakout"]
    assert [d["setup"] for d in out["manual_review"]] == ["Distribution Short"]
    assert any("research-validated" in m and "Distribution Short" in m for m in sent)


def test_save_validation_keeps_locked_entries(tmp_path, monkeypatch):
    import json as _json
    from backtesting import crypto_validation as cv
    p = tmp_path / "v.json"
    p.write_text(_json.dumps({"stats": {"Distribution Short": {"n": 778, "locked": True}},
                              "validated": ["Distribution Short"]}))
    monkeypatch.setattr(cv, "_SAVE_PATH", p)
    cv.save_validation({"stats": {"Distribution Short": {"n": 40}, "X": {"n": 1}}, "validated": ["X"]})
    out = _json.loads(p.read_text())
    assert out["stats"]["Distribution Short"]["n"] == 778 and out["stats"]["X"]["n"] == 1
    assert "Distribution Short" in out["validated"]


def test_desk_guard_accepts_wide_stop_sized_down(monkeypatch):
    from desk.agents import factpack
    from utils import exchange
    monkeypatch.setattr(exchange, "get_ohlcv", lambda *a, **k: None)
    pack = factpack.build("SOL-USD", "short", entry=100.0, stop=140.0)   # 40% stop
    assert pack["guard"]["verdict"] == "ACCEPT"
    assert pack["guard_options"]["plain"]["leverage"] == 1
    assert pack["guard_options"]["plain"]["risk_usd"] <= 12.5


def test_live_volume_factor_scales_setup_floors():
    from skills import new_setups as ns
    import config
    assert config.LIVE_VOLUME_FACTOR == 13.4
    assert abs(config.AUTO_SCAN_PARAMS["min_vol_usd_m"] - 0.5 / 13.4) < 1e-9
    old = ns.QV_SOURCE_FACTOR
    try:
        ns.QV_SOURCE_FACTOR = 13.4
        assert ns.DIST_MIN_QV / ns.QV_SOURCE_FACTOR < 40_000
    finally:
        ns.QV_SOURCE_FACTOR = old
