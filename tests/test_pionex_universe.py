"""6 Nov 2026: Pionex universe, MEXC candle mapping, alert slippage direction."""
import pandas as pd

import monitor
from utils import exchange as X


def test_short_skip_cap_is_below_entry(monkeypatch):
    monkeypatch.setattr(monitor, "_risk_block", lambda: "")
    monkeypatch.setattr(monitor, "_backtest_stats", lambda l: "")
    txt = monitor._alert_text({"symbol": "GOAT-USD", "direction": "short", "stop": 0.0671,
                               "tp": 0.0494, "setup_label": "Distribution Short"}, 0.0612, "x")
    assert "skip if below $0.0610" in txt          # 0.0612 x (1 - 0.3%) = 0.06102
    txt = monitor._alert_text({"symbol": "SOL-USD", "direction": "long", "stop": 90.0,
                               "setup_label": "x"}, 100.0, "x")
    assert "skip if above $100.30" in txt


def test_pionex_filter_keeps_crypto_drops_stocks():
    rows = [{"symbol": f"{b}_USDT_PERP", "status": "TRADING"} for b in
            ("BTC", "AVAX", "ARX", "AAPLX", "NVDAX", "XAU", "ANTHROPIC", "CBRS", "PEPE")]
    rows.append({"symbol": "BTC_USDC_PERP", "status": "TRADING"})
    assert X.pionex_crypto_bases(rows) == ["ARX", "AVAX", "BTC", "PEPE"]


def test_alias_and_unit_mapping(monkeypatch):
    calls = []
    monkeypatch.setattr(X, "_ensure_perp_map", lambda v: None)
    monkeypatch.setitem(X._perp_info, "mexc:FILECOIN-USD", ("FILECOIN_USDT", 1.0))
    monkeypatch.setitem(X._perp_info, "mexc:1000BONK-USD", ("1000BONK_USDT", 1.0))
    df = pd.DataFrame({"open": [10.0], "high": [10.0], "low": [10.0], "close": [10.0], "volume": [5.0]})

    def fake(sym, tf, lim, ex):
        calls.append(sym)
        return df.copy()
    monkeypatch.setattr(X, "_perp_ohlcv", fake)
    assert not X._fallback_perp_ohlcv("FIL-USD", "1d", 10).empty and calls[-1] == "FILECOIN-USD"
    out = X._fallback_perp_ohlcv("BONK-USD", "1d", 10)
    assert calls[-1] == "1000BONK-USD" and out["close"].iloc[0] == 0.01   # price / 1000


def test_old_bybit_triggers_stay_perp_only(monkeypatch):
    monkeypatch.setattr(X, "_saved_universe", lambda v: ["1000TAG-USD"] if v == "bybit" else [])
    monkeypatch.setattr(X, "list_perp_symbols", lambda v="mexc", quote="USDT": ["BTC-USD"])
    assert X.in_perp_universe("1000TAG-USD", "pionex") and X.in_perp_universe("BTC-USD", "pionex")
    assert not X.in_perp_universe("FOO-USD", "pionex")
