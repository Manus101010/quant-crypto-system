"""6 Nov 2026: brief and alerts are short, Pionex first, and never show dollar results."""
import re

import morning_brief as mb
import monitor


def test_brief_is_short_and_has_no_dollar_results(monkeypatch):
    monkeypatch.setattr(mb.tdb, "init_db", lambda: None)
    monkeypatch.setattr(mb.tdb, "get_triggers_since", lambda c: [
        {"status": "fired", "outcome": None, "direction": "short", "symbol": "GOAT-USD",
         "fired_price": 0.0612, "stop": 0.0671, "tp": 0.0494},
        {"status": "fired", "outcome": "stop", "direction": "short", "symbol": "OLD-USD",
         "fired_price": 1.0, "stop": 1.1},
    ])
    monkeypatch.setattr(mb, "_btc_line", lambda: "BTC 76,326: below its 50 day average, so shorts only.")
    monkeypatch.setattr(mb, "_movers_short", lambda: "<b>Movers:</b> nothing clean in today's top gainers and losers.")
    monkeypatch.setattr(mb, "_week_short", lambda: "")

    class _O:
        @staticmethod
        def live_stats(taken_only=False):
            return {"total": {"n": 9, "win_rate": 0.22, "total_r": -4.0}}
    import triggers
    monkeypatch.setattr(triggers, "outcomes", _O, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "triggers.outcomes", _O)
    txt = mb.build_brief()
    assert "GOAT" in txt and "OLD" not in txt and "Pionex" in txt
    assert "/guard" not in txt and "Deactivated" not in txt and "Deployment" not in txt
    assert not re.search(r"\$-|−\$|\+\$|\(\$-", txt)      # no dollar results
    assert "R per trade" in txt and len(txt) < 1200


def test_alert_card_is_pionex_and_compact(monkeypatch):
    monkeypatch.setattr(monitor, "_risk_block", lambda: "")
    monkeypatch.setattr(monitor, "_backtest_stats", lambda l: "Past 669 trades: 41% won, winners averaged 2.0x the risk.")
    trg = {"symbol": "GOAT-USD", "direction": "short", "setup_label": "Distribution Short",
           "stop": 0.0671, "tp": 0.0494}
    txt = monitor._alert_text(trg, 0.0612, "x")
    assert "Pionex" in txt and "Bybit" not in txt and "/took GOAT" in txt
    assert txt.count("\n") <= 14
