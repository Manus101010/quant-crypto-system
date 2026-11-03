"""3 Nov 2026: a stale AUTO decay row blocked the two live research setups."""
from triggers import scan


def test_auto_decay_rows_ignored_for_protected_setups(monkeypatch):
    rows = [
        {"setup_label": "Distribution Short", "reason": "PF 0.91 / n 60 on 2026-10-12"},
        {"setup_label": "Downtrend Bounce Fade", "reason": "PF 0.88 / n 41 on 2026-10-19"},
        {"setup_label": "Momentum Runner", "reason": "PF 0.80 / n 70 on 2026-10-19"},
        {"setup_label": "Distribution Short X", "reason": "switched off by hand"},
    ]
    monkeypatch.setattr(scan.tdb, "get_deactivations", lambda: rows)
    off = scan.effective_deactivated()
    assert "Distribution Short" not in off and "Downtrend Bounce Fade" not in off
    assert "Momentum Runner" in off and "Distribution Short X" in off


def test_manual_switch_off_still_counts(monkeypatch):
    monkeypatch.setattr(scan.tdb, "get_deactivations",
                        lambda: [{"setup_label": "Distribution Short", "reason": "manual: paused"}])
    assert scan.effective_deactivated() == {"Distribution Short"}
