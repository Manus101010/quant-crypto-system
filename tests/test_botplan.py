"""/bot grid planner: offline."""
from __future__ import annotations
from desk import botplan


def t(close, ema20, ema50, stack, slope, dist, chg=0.0, atr=1.0, sh=None, sl=None):
    return {"close": close, "ema20": ema20, "ema50": ema50, "ema_stack": stack,
            "ema50_slope_pct_10bars": slope, "dist_from_ema50_atr": dist, "change_pct_10bars": chg,
            "atr14": atr, "swing_high_20": sh, "swing_low_20": sl, "rsi14": 50}


BTC_DOWN = t(70000, 71000, 72000, "bear", -1, -1)


def test_stretched_rolling_over_is_short():
    c = botplan.classify(None, t(100, 102, 95, "mixed", 1, 2, chg=-3), t(100, 90, 80, "bull", 2, 5),
                         None, BTC_DOWN, False)
    assert c["mode"] == "short" and "rolled over" in c["reason"]


def test_stretched_still_ripping_waits():
    c = botplan.classify(None, t(100, 95, 90, "bull", 2, 2, chg=5), t(100, 90, 80, "bull", 2, 5),
                         None, BTC_DOWN, False)
    assert c["mode"] is None and "Wait" in c["reason"]


def test_range_never_neutral():
    c = botplan.classify(None, t(100, 100, 100, "mixed", 0, 0), t(100, 100, 100, "mixed", 0, 0.2),
                         None, BTC_DOWN, True)
    assert c["mode"] is None and "Neutral" in c["reason"]


def test_uptrend_blocked_by_long_gate():
    c = botplan.classify(None, t(100, 99, 97, "bull", 1, 1), t(100, 98, 95, "bull", 1, 1.5),
                         None, BTC_DOWN, False)
    assert c["mode"] is None and "long gate" in c["reason"]


def test_plan_fits_rules_and_formats(monkeypatch):
    monkeypatch.setattr("utils.breadth.long_gate", lambda: (False, ""))
    from triggers import db
    monkeypatch.setattr(db, "set_state", lambda k, v: None)
    data = {"15m": t(1.0, 1.01, 1.0, "bear", -1, -1), "1h": t(1.0, 1.02, 1.03, "bear", -1, -1, chg=-2,
            atr=0.02, sh=1.08, sl=0.95), "4h": t(1.0, 1.05, 1.1, "bear", -2, -2), "1d": None,
            "btc4": BTC_DOWN}
    p = botplan.plan("TESTUSDT", 50, data=data)
    assert p["mode"] == "short"
    g = p["grid"]
    assert g["hi"] > 1.0 > g["lo"] and g["stop"] > g["hi"] and g["leverage"] == 3
    assert g["worst_loss"] <= 12.5 + 1e-6
    txt = botplan.text(p)
    assert "Short grid" in txt and "Not edge tested" in txt and "—" not in txt.split("Trend")[0]


def test_price_text():
    assert botplan._p(0.000012345) == "0.000012345"
    assert botplan._p(1.28291) == "1.2829"
