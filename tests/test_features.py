"""Offline tests for the features/ package. All HTTP is mocked."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features import _http, coinalyze, coinglass, derivs, dex, hyperliquid, snapshot, whales  # noqa: E402


# ── fake HTTP layer ─────────────────────────────────────────────────────────
class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._p = payload

    def json(self):
        if self._p is None:
            raise ValueError("no json")
        return self._p


class FakeSession:
    """Routes by URL substring. Records every call."""

    def __init__(self, routes: dict, post_routes: dict | None = None):
        self.routes = routes
        self.post_routes = post_routes or {}
        self.calls: list[tuple[str, dict | None, dict | None]] = []

    def _match(self, routes, url):
        best = None
        for k, v in routes.items():
            if k in url and (best is None or len(k) > len(best[0])):
                best = (k, v)
        return best[1] if best else None

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        r = self._match(self.routes, url)
        if r is None:
            return FakeResp(404, None)
        if callable(r):
            r = r(url, params)
        return r if isinstance(r, FakeResp) else FakeResp(200, r)

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json, None))
        r = self._match(self.post_routes, url)
        return r if isinstance(r, FakeResp) else FakeResp(200 if r is not None else 404, r)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    _http.cache_clear()
    _http._blocked.clear()
    _http._limiters.clear()
    monkeypatch.delenv("COINGLASS_API_KEY", raising=False)
    monkeypatch.delenv("WHALE_ALERT_API_KEY", raising=False)
    monkeypatch.delenv("COINALYZE_API_KEY", raising=False)
    monkeypatch.setattr(_http.RateLimiter, "wait", lambda self: None)
    yield


def install(monkeypatch, routes, post_routes=None) -> FakeSession:
    fs = FakeSession(routes, post_routes)
    monkeypatch.setattr(_http, "_session", fs)
    monkeypatch.setattr(hyperliquid, "_session", fs)
    return fs


H = 3_600_000
NOW = 1_793_030_400_000


def okx_routes(core="SOL", funding=0.0003, hist_rates=None, oi_growth=0.0, ls=2.0, ls_hist=None):
    inst = f"{core}-USDT-SWAP"
    hist_rates = hist_rates if hist_rates is not None else [0.0001] * 90
    ls_hist = ls_hist if ls_hist is not None else [1.5] * 99
    oi_rows = []
    for i in range(100):                    # newest first; OI grows toward now
        coin = 1000.0 * (1 + oi_growth) ** (-i)
        oi_rows.append([str(NOW - i * H), str(coin * 10), str(coin), str(coin * 100)])
    return {
        "/api/v5/public/instruments": {"code": "0", "data": [
            {"instId": inst, "state": "live"}, {"instId": "BTC-USDT-SWAP", "state": "live"}]},
        "/api/v5/public/funding-rate-history": {"code": "0", "data": [
            {"fundingTime": str(NOW - i * 8 * H), "fundingRate": str(r), "realizedRate": str(r)}
            for i, r in enumerate(hist_rates)]},
        "/api/v5/public/funding-rate": {"code": "0", "data": [
            {"fundingRate": str(funding), "fundingTime": str(NOW), "nextFundingTime": str(NOW + 8 * H)}]},
        "open-interest-history": {"code": "0", "data": oi_rows},
        "long-short-account-ratio-contract": {"code": "0", "data": [
            [str(NOW - i * H), str(v)] for i, v in enumerate([ls] + ls_hist)]},
        "taker-volume-contract": {"code": "0", "data": [
            [str(NOW - i * H), "100", "150"] for i in range(25)]},
        "/api/v5/market/ticker": {"code": "0", "data": [{"last": "100.0"}]},
    }


# ── helpers ─────────────────────────────────────────────────────────────────
def test_split_symbol():
    assert _http.split_symbol("1000PEPE-USD") == ("1000PEPE", "PEPE")
    assert _http.split_symbol("SOLUSDT") == ("SOL", "SOL")
    assert _http.split_symbol("BTC-USD") == ("BTC", "BTC")
    assert _http.split_symbol("1000000MOG-USD") == ("1000000MOG", "MOG")
    assert _http.split_symbol("10000SATS-USD") == ("10000SATS", "SATS")
    assert _http.split_symbol("0G-USD") == ("0G", "0G")


def test_pct_rank_and_fnum():
    assert _http.pct_rank(5, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == 45.0
    assert _http.pct_rank(5, [1, 2]) is None
    assert _http.fnum("1.5") == 1.5 and _http.fnum(None) is None and _http.fnum("x") is None
    assert _http.fnum(float("nan")) is None


def test_get_json_marks_geo_block(monkeypatch):
    fs = install(monkeypatch, {"api.bybit.com": FakeResp(403, {"x": 1})})
    assert _http.get_json("https://api.bybit.com/v5/x", host="api.bybit.com") is None
    assert _http.is_blocked("api.bybit.com")
    n = len(fs.calls)
    assert _http.get_json("https://api.bybit.com/v5/x", host="api.bybit.com") is None
    assert len(fs.calls) == n                      # skipped without a request


def test_get_json_never_raises(monkeypatch):
    class Boom:
        def get(self, *a, **k):
            raise ConnectionError("down")
    monkeypatch.setattr(_http, "_session", Boom())
    assert _http.get_json("https://x.y/z") is None


# ── derivs ──────────────────────────────────────────────────────────────────
def test_derivs_okx_full(monkeypatch):
    install(monkeypatch, okx_routes(funding=0.0003, oi_growth=0.01, ls=2.0))
    d = derivs.get("SOL-USD")
    assert d["derivs_src"] == "okx"
    assert d["funding_rate"] == pytest.approx(0.0003)
    assert d["funding_interval_h"] == 8.0
    assert d["funding_8h"] == pytest.approx(0.0003)
    assert d["funding_pct_7d"] == 100.0            # above every historical rate
    assert d["oi_chg_1h"] == pytest.approx(1.0, abs=0.01)
    assert d["oi_chg_24h"] == pytest.approx((1.01 ** 24 - 1) * 100, abs=0.05)
    assert d["ls_ratio"] == 2.0 and d["ls_pct_4d"] >= 99
    assert d["taker_ratio_1h"] == pytest.approx(1.5)
    assert d["taker_ratio_24h"] == pytest.approx(1.5)
    assert d["oi_usd"] == pytest.approx(100000.0)


def test_derivs_4h_funding_normalised(monkeypatch):
    r = okx_routes(funding=0.00005)
    r["/api/v5/public/funding-rate"]["data"][0]["nextFundingTime"] = str(NOW + 4 * H)
    install(monkeypatch, r)
    d = derivs.get("SOL-USD")
    assert d["funding_interval_h"] == 4.0
    assert d["funding_8h"] == pytest.approx(0.0001)


def test_derivs_mexc_fallback_when_not_on_okx(monkeypatch):
    routes = {
        "/api/v5/public/instruments": {"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "state": "live"}]},
        "contract/funding_rate/history": {"success": True, "data": {"resultList": [
            {"settleTime": NOW - i * 8 * H, "fundingRate": 0.0001} for i in range(30)]}},
        "contract/funding_rate/NEWC_USDT": {"success": True, "data": {"fundingRate": -0.001, "collectCycle": 8}},
        "api.bybit.com": FakeResp(403, {}),
    }
    install(monkeypatch, routes)
    d = derivs.get("NEWC-USD")
    assert d["derivs_src"] == "mexc"
    assert d["funding_8h"] == pytest.approx(-0.001)
    assert d["funding_pct_7d"] is not None and d["funding_pct_7d"] < 10
    assert d["oi_chg_24h"] is None and d["ls_ratio"] is None
    assert _http.is_blocked("api.bybit.com")


def test_derivs_bybit_when_reachable(monkeypatch):
    routes = {
        "/api/v5/public/instruments": {"code": "0", "data": []},
        "contract.mexc.com": FakeResp(500, None),
        "/v5/market/tickers": {"retCode": 0, "result": {"list": [
            {"fundingRate": "0.0002", "fundingIntervalHour": "8", "openInterestValue": "5000000"}]}},
        "/v5/market/funding/history": {"retCode": 0, "result": {"list": [
            {"fundingRateTimestamp": str(NOW - i * 8 * H), "fundingRate": "0.0001"} for i in range(30)]}},
        "/v5/market/open-interest": {"retCode": 0, "result": {"list": [
            {"timestamp": str(NOW - i * H), "openInterest": str(100 - i)} for i in range(30)]}},
        "/v5/market/account-ratio": {"retCode": 0, "result": {"list": [
            {"timestamp": str(NOW - i * H), "buyRatio": "0.6", "sellRatio": "0.4"} for i in range(30)]}},
    }
    install(monkeypatch, routes)
    d = derivs.get("XYZ-USD")
    assert d["derivs_src"] == "bybit"
    assert d["oi_usd"] == 5_000_000
    assert d["oi_chg_1h"] == pytest.approx((100 / 99 - 1) * 100, abs=0.01)
    assert d["ls_ratio"] == pytest.approx(1.5)


def test_derivs_total_outage_returns_none_fields(monkeypatch):
    install(monkeypatch, {})
    d = derivs.get("SOL-USD")
    assert all(d[k] is None for k in derivs.FIELDS)
    assert d["derivs_src"] is None


def test_derivs_cache(monkeypatch):
    fs = install(monkeypatch, okx_routes())
    derivs.get("SOL-USD")
    n = len(fs.calls)
    derivs.get("SOL-USD")
    assert len(fs.calls) == n


# ── coinalyze ───────────────────────────────────────────────────────────────
CZ_MARKETS = [
    {"symbol": "SOLUSDT.6", "exchange": "Bybit", "symbol_on_exchange": "SOLUSDT",
     "base_asset": "SOL", "quote_asset": "USDT", "is_perpetual": True,
     "has_long_short_ratio_data": True, "has_buy_sell_data": True},
    {"symbol": "SOLUSDT_PERP.A", "exchange": "Binance", "symbol_on_exchange": "SOLUSDT",
     "base_asset": "SOL", "quote_asset": "USDT", "is_perpetual": True},
    {"symbol": "1000PEPEUSDT.6", "exchange": "Bybit", "symbol_on_exchange": "1000PEPEUSDT",
     "base_asset": "PEPE", "quote_asset": "USDT", "is_perpetual": True},
    {"symbol": "SOLUSD.6", "exchange": "Bybit", "symbol_on_exchange": "SOLUSD",
     "base_asset": "SOL", "quote_asset": "USD", "is_perpetual": True},
]


def cz_routes(pct_units=True):
    k = 1.0 if pct_units else 0.01                   # value as Coinalyze would send it
    t0 = int(time.time()) - 100 * 3600

    def hist(url, params):
        syms = params["symbols"].split(",")
        if "funding-rate-history" in url:
            return [{"symbol": s, "history": [{"t": t0 + i * 3600, "c": 0.01 * k} for i in range(720)]}
                    for s in syms]
        if "open-interest-history" in url:
            usd = params.get("convert_to_usd") == "true"
            return [{"symbol": s, "history": [{"t": t0 + i * 3600, "c": (1000 + 10 * i) * (100 if usd else 1)}
                                              for i in range(48)]} for s in syms]
        if "liquidation-history" in url:
            return [{"symbol": s, "history": [{"t": t0 + i * 3600, "l": 10000, "s": 5000} for i in range(25)]}
                    for s in syms]
        if "long-short-ratio-history" in url:
            return [{"symbol": s, "history": [{"t": t0 + i * 3600, "r": 1 + i / 100} for i in range(96)]}
                    for s in syms]
        if "ohlcv-history" in url:
            return [{"symbol": s, "history": [{"t": t0 + i * 3600, "v": 100, "bv": 60} for i in range(26)]}
                    for s in syms]
        return []

    return {
        "api.coinalyze.net/v1/future-markets": CZ_MARKETS,
        "api.coinalyze.net/v1/funding-rate-history": hist,
        "api.coinalyze.net/v1/predicted-funding-rate": [{"symbol": "SOLUSDT.6", "value": 0.02 * k}],
        "api.coinalyze.net/v1/funding-rate": [{"symbol": "SOLUSDT.6", "value": 0.03 * k}],
        "api.coinalyze.net/v1/open-interest-history": hist,
        "api.coinalyze.net/v1/liquidation-history": hist,
        "api.coinalyze.net/v1/long-short-ratio-history": hist,
        "api.coinalyze.net/v1/ohlcv-history": hist,
    }


def test_coinalyze_disabled_without_key(monkeypatch):
    fs = install(monkeypatch, cz_routes())
    assert coinalyze.get("SOL-USD") == {}
    assert fs.calls == []


def test_coinalyze_resolve():
    assert coinalyze.resolve("SOL", "Bybit", CZ_MARKETS)["symbol"] == "SOLUSDT.6"
    assert coinalyze.resolve("1000PEPE", "Bybit", CZ_MARKETS)["symbol"] == "1000PEPEUSDT.6"
    assert coinalyze.resolve("SOL", "Binance", CZ_MARKETS)["symbol"] == "SOLUSDT_PERP.A"
    assert coinalyze.resolve("DOGE", "Bybit", CZ_MARKETS) is None


@pytest.mark.parametrize("pct_units", [True, False])
def test_coinalyze_features(monkeypatch, pct_units):
    monkeypatch.setenv("COINALYZE_API_KEY", "k")
    fs = install(monkeypatch, cz_routes(pct_units))
    f = coinalyze.get("SOL-USD")
    assert f["funding_rate"] == pytest.approx(0.0003)          # unit detection both ways
    assert f["pred_funding_8h"] == pytest.approx(0.0002)
    assert f["funding_pct_7d"] == 100.0
    assert f["oi_usd"] == pytest.approx((1000 + 470) * 100)
    assert f["oi_chg_1h"] == pytest.approx((1470 / 1460 - 1) * 100, abs=0.01)
    assert f["oi_chg_24h"] == pytest.approx((1470 / 1230 - 1) * 100, abs=0.01)
    assert f["oi_usd_agg"] == pytest.approx(2 * 1470 * 100)
    assert f["liq_long_24h"] == 2 * 24 * 10000 and f["liq_short_24h"] == 2 * 24 * 5000
    assert f["liq_skew_24h"] == pytest.approx(1 / 3, abs=1e-3)
    assert f["ls_ratio"] == pytest.approx(1.95) and f["ls_pct_4d"] >= 99
    assert f["taker_ratio_1h"] == pytest.approx(1.5)
    assert all(h.get("api_key") == "k" for _, _, h in fs.calls if h)


# ── coinglass ───────────────────────────────────────────────────────────────
def test_coinglass_disabled_without_key(monkeypatch):
    fs = install(monkeypatch, {})
    assert coinglass.get("BTC") == {}
    assert fs.calls == []


def test_coinglass_with_key(monkeypatch):
    monkeypatch.setenv("COINGLASS_API_KEY", "secret")
    t = NOW
    routes = {
        "funding-rate/oi-weight-history": {"code": "0", "data": [
            {"time": t - i * 4 * H, "close": "0.01"} for i in range(50)]},
        "open-interest/aggregated-history": {"code": "0", "data": [
            {"time": t - i * 4 * H, "close": str(1000 - i)} for i in range(10)]},
        "liquidation/aggregated-history": {"code": "0", "data": [
            {"time": t - i * 4 * H, "aggregated_long_liquidation_usd": 300,
             "aggregated_short_liquidation_usd": 100} for i in range(6)]},
        "global-long-short-account-ratio/history": {"code": "0", "data": [
            {"time": t - i * 4 * H, "global_account_long_short_ratio": 2.0 - i / 100} for i in range(20)]},
        "aggregated-taker-buy-sell-volume/history": {"code": "0", "data": [
            {"time": t - i * 4 * H, "aggregated_buy_volume_usd": 120,
             "aggregated_sell_volume_usd": 100} for i in range(6)]},
    }
    fs = install(monkeypatch, routes)
    f = coinglass.get("BTC-USD")
    assert f["cg_funding_oiw"] == pytest.approx(0.0001)
    assert f["cg_oi_usd"] == 1000
    assert f["cg_oi_chg_4h"] == pytest.approx((1000 / 999 - 1) * 100, abs=1e-3)
    assert f["cg_liq_skew"] == pytest.approx(0.5)
    assert f["cg_ls_ratio"] == 2.0
    assert f["cg_taker_ratio_24h"] == pytest.approx(1.2)
    assert all(h and h.get("CG-API-KEY") == "secret" for _, _, h in fs.calls)
    assert all("4h" == p.get("interval") for _, p, _ in fs.calls)


# ── dex ─────────────────────────────────────────────────────────────────────
def pair(sym, price, liq, v1, v24, b1, s1, created=None, addr="addr1"):
    return {"baseToken": {"symbol": sym, "address": addr}, "priceUsd": str(price),
            "liquidity": {"usd": liq}, "volume": {"h1": v1, "h6": v24 / 4, "h24": v24},
            "txns": {"h1": {"buys": b1, "sells": s1}, "h6": {"buys": b1 * 6, "sells": s1 * 6},
                     "h24": {"buys": b1 * 24, "sells": s1 * 24}},
            "priceChange": {"h1": 5.0, "h24": 20.0}, "pairCreatedAt": created}


def test_dex_filters_impostors_and_flags_hype(monkeypatch):
    created = (time.time() - 10 * 86400) * 1000
    pairs = [pair("WIF", 0.18, 2e6, 60_000, 240_000, 80, 20, created),     # real, hot
             pair("WIF", 0.0001, 5e6, 1e6, 1e7, 1, 1),                    # impostor price
             pair("WIFE", 0.18, 1e6, 1e6, 1e7, 1, 1)]                     # different symbol
    install(monkeypatch, {"latest/dex/search": {"pairs": pairs},
                          "token-boosts": [{"tokenAddress": "zzz"}]})
    f = dex.get("WIF-USD", ref_price=0.18)
    assert f["dex_pairs"] == 1.0 and f["dex_price_checked"] == 1.0
    assert f["dex_vol_exp_1h"] == pytest.approx(6.0)
    assert f["dex_buy_ratio_h1"] == pytest.approx(0.8)
    assert f["dex_age_days"] == pytest.approx(10.0, abs=0.1)
    assert f["dex_boosted"] == 0.0
    flags = snapshot.derive_flags(f)
    assert flags["dex_hype"] == 1.0


def test_dex_boost_detected(monkeypatch):
    install(monkeypatch, {"latest/dex/search": {"pairs": [pair("ABC", 1.0, 1e5, 1, 24, 1, 1, addr="AbC")]},
                          "token-boosts/latest": [{"tokenAddress": "abc"}],
                          "token-boosts/top": []})
    f = dex.get("ABC", ref_price=1.0)
    assert f["dex_boosted"] == 1.0


def test_dex_unchecked_needs_liquidity(monkeypatch):
    install(monkeypatch, {"latest/dex/search": {"pairs": [pair("ABC", 1.0, 1e3, 1, 24, 1, 1)]}})
    f = dex.get("ABC")
    assert f["dex_pairs"] == 0.0 and f["dex_price_checked"] == 0.0


def test_dex_outage(monkeypatch):
    install(monkeypatch, {})
    f = dex.get("ABC", 1.0)
    assert f["dex_pairs"] == 0.0 and f["dex_vol_h24"] is None


# ── whales ──────────────────────────────────────────────────────────────────
def test_whales_disabled_without_key(monkeypatch):
    fs = install(monkeypatch, {})
    assert whales.get("BTC") == {}
    assert fs.calls == []


def test_whales_summarise_alerts():
    now = 1_800_000_000
    alerts = [
        {"timestamp": now - 3600, "from": "unknown wallet", "to": "binance",
         "amounts": [{"symbol": "BTC", "value_usd": 2e6}]},
        {"timestamp": now - 7200, "from": "coinbase", "to": "unknown wallet",
         "amounts": [{"symbol": "BTC", "value_usd": 5e5}]},
        {"timestamp": now - 7200, "from": "unknown wallet", "to": "kraken",
         "amounts": [{"symbol": "ETH", "value_usd": 9e6}]},                 # other coin
        {"timestamp": now - 90000, "from": "unknown wallet", "to": "binance",
         "amounts": [{"symbol": "BTC", "value_usd": 9e6}]},                 # too old
        {"timestamp": now - 60, "from": "binance", "to": "okx",
         "amounts": [{"symbol": "BTC", "value_usd": 9e6}]},                 # exch to exch
    ]
    f = whales.summarise_alerts(alerts, "BTC-USD", hours=24, now=now)
    assert f["whale_to_exch_usd"] == 2e6
    assert f["whale_from_exch_usd"] == 5e5
    assert f["whale_netflow_usd"] == 1.5e6 and f["whale_n"] == 2


def test_whales_enterprise_rest(monkeypatch):
    monkeypatch.setenv("WHALE_ALERT_API_KEY", "wa")
    txs = {"transactions": [{"sub_transactions": [{
        "symbol": "BTC", "unit_price_usd": "80000",
        "inputs": [{"amount": "-20", "owner": "unknown"}],
        "outputs": [{"amount": "20", "owner": "binance", "owner_type": "exchange"}]}]}]}
    install(monkeypatch, {"/status": [{"name": "bitcoin", "symbols": ["BTC"]}],
                          "height_at_time": {"height": 100}, "/bitcoin/transactions": txs})
    f = whales.get("BTC")
    assert f["whale_to_exch_usd"] == pytest.approx(1.6e6) and f["whale_n"] == 1


# ── hyperliquid ─────────────────────────────────────────────────────────────
def test_hyperliquid(monkeypatch):
    payload = [{"universe": [{"name": "BTC"}, {"name": "kPEPE"}]},
               [{"funding": "0.0000125", "openInterest": "10", "markPx": "80000", "premium": "-0.0003",
                 "dayNtlVlm": "1e9"},
                {"funding": "0.00005", "openInterest": "1000000", "markPx": "0.004", "premium": "0",
                 "dayNtlVlm": "1e7"}]]
    install(monkeypatch, {}, {"api.hyperliquid.xyz": payload})
    f = hyperliquid.get("BTC-USD")
    assert f["hl_funding_8h"] == pytest.approx(0.0001) and f["hl_oi_usd"] == 800000
    assert hyperliquid.get("1000PEPE-USD")["hl_funding_8h"] == pytest.approx(0.0004)


# ── snapshot ────────────────────────────────────────────────────────────────
def test_derive_flags_crowded_and_squeeze():
    crowded = {"funding_pct_7d": 95, "ls_pct_4d": 95, "funding_8h": 0.0005,
               "oi_chg_1h": 1, "oi_chg_4h": 2, "oi_chg_24h": 8}
    f = snapshot.derive_flags(crowded)
    assert f["crowded_longs"] == 1.0 and f["flush_risk"] == 1.0 and f["crowded_shorts"] == 0.0
    clamp = dict(crowded, funding_8h=0.0001)              # p95 but only at the clamp
    assert snapshot.derive_flags(clamp)["crowded_longs"] == 0.0
    short = {"funding_pct_7d": 5, "ls_pct_4d": 5, "funding_8h": -0.0004,
             "oi_chg_1h": 6, "oi_chg_4h": 0, "oi_chg_24h": 6}
    g = snapshot.derive_flags(short)
    assert g["crowded_shorts"] == 1.0 and g["squeeze_risk"] == 1.0 and g["oi_spike"] == 1.0
    empty = snapshot.derive_flags({})
    assert all(v is None for v in empty.values())


def test_snapshot_okx_only(monkeypatch):
    routes = okx_routes(funding=0.0003, oi_growth=0.0)
    routes["latest/dex/search"] = {"pairs": []}
    install(monkeypatch, routes, {"api.hyperliquid.xyz": [{"universe": []}, []]})
    s = snapshot.snapshot("SOL-USD", "short")
    assert s["symbol"] == "SOL-USD" and s["direction"] == "short"
    assert s["funding_8h"] == pytest.approx(0.0003)
    assert s["pos_src"] == "okx"
    assert "okx" in s["sources"]
    for k in snapshot.FLAGS:
        assert k in s
    # funding p100 above the clamp AND L/S 2.0 above its 1.5 history: crowded
    assert s["crowded_longs"] == 1.0 and s["flush_risk"] == 0.0     # OI flat
    line = snapshot.alert_line(s)
    assert line.startswith("Pos: fund +0.030%")
    js = snapshot.to_json(s)
    assert '"funding_8h":0.0003' in js


def test_snapshot_coinalyze_primary(monkeypatch):
    monkeypatch.setenv("COINALYZE_API_KEY", "k")
    routes = {**okx_routes(funding=0.0009), **cz_routes()}
    install(monkeypatch, routes, {"api.hyperliquid.xyz": [{"universe": []}, []]})
    s = snapshot.snapshot("SOL-USD")
    assert s["pos_src"] == "coinalyze"
    assert s["funding_8h"] == pytest.approx(0.0003)        # Coinalyze wins
    assert s["okx_funding_8h"] == pytest.approx(0.0009)    # OKX kept for comparison
    assert s["liq_long_24h"] == 480000
    assert "liq 24h" in snapshot.alert_line(s)


def test_snapshot_never_raises_and_times_out(monkeypatch):
    def slow(*a, **k):
        time.sleep(2)
        return {"funding_8h": 1.0}
    monkeypatch.setattr(derivs, "get", slow)
    monkeypatch.setattr(dex, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(hyperliquid, "get", lambda *a, **k: {})
    monkeypatch.setattr(snapshot, "ref_price", lambda c: None)
    t = time.time()
    s = snapshot.snapshot("SOL-USD", budget=0.3)
    assert time.time() - t < 1.5
    assert s["funding_8h"] is None and s["crowded_longs"] is None
    assert snapshot.alert_line(s) == ""


def test_alert_line_flags():
    s = {"funding_8h": 0.0006, "funding_pct_7d": 97, "oi_chg_24h": 12.3, "ls_ratio": 3.1,
         "ls_pct_4d": 96, "taker_ratio_24h": 1.1, "crowded_longs": 1.0, "flush_risk": 1.0}
    line = snapshot.alert_line(s)
    assert "fund +0.060% (p97)" in line and "OI 24h +12.3%" in line
    assert "crowded longs" in line and "flush risk" in line
    assert snapshot.alert_line(None) == ""


# ── research/features_eval ──────────────────────────────────────────────────
def test_eval_ledger_join():
    from research import features_eval as fe
    trades = []
    rng = np.random.default_rng(0)
    for i in range(30):
        cl = 1.0 if i % 3 == 0 else 0.0
        trades.append({"id": i, "setup_label": "Distribution Short", "direction": "short",
                       "r_multiple": (1.5 if cl else -0.5) + rng.normal(0, 0.01),
                       "features_json": snapshot.to_json({"crowded_longs": cl, "funding_pct_7d": i * 3,
                                                          "oi_chg_24h": None})})
    trades.append({"id": 99, "r_multiple": None, "features_json": "{}"})      # open
    trades.append({"id": 98, "r_multiple": 1.0, "features_json": None})       # no snapshot
    res = fe.run_ledger(trades)
    assert res["closed"] == 31 and res["with_features"] == 30
    rows = {(r["feature"], r["bucket"]): r for r in res["rows"]}
    hit = [r for (f, b), r in rows.items() if f == "crowded_longs" and r["n"] == 10]
    assert hit and hit[0]["exp_r"] == pytest.approx(1.5, abs=0.05)
    assert ("oi_chg_24h", "missing") in rows


def test_eval_hist_features_no_lookahead():
    from research import features_eval as fe
    days = pd.date_range("2025-01-01", periods=60, freq="D")
    oi = pd.DataFrame({0: days.astype("int64") // 10**6, 1: 0, 2: np.arange(60) + 100.0, 3: 0}, index=days)
    ls = pd.DataFrame({0: 0, 1: np.linspace(1, 2, 60)}, index=days)
    fund = pd.Series(0.0001, index=pd.date_range("2024-12-01", periods=300, freq="8h"))
    day = days[40]
    f = fe.hist_features(day, oi, ls, fund)
    assert f["oi_chg_1d"] == pytest.approx((140 / 139 - 1) * 100)
    assert f["ls_pct_30d"] > 95                       # rising series -> top of range
    assert f["fund_3d_8h"] == pytest.approx(0.0001)
    # later data must not change the reading
    oi2 = oi.copy(); oi2.iloc[41:, 2] = 1e9
    assert fe.hist_features(day, oi2, ls, fund)["oi_chg_1d"] == f["oi_chg_1d"]


def test_eval_analyse_backtest_filters():
    from research import features_eval as fe
    rows = []
    for i in range(40):
        rows.append({"setup": "Distribution Short", "day": pd.Timestamp("2025-01-01") + pd.Timedelta(days=i),
                     "r": 2.0 if i % 2 else -1.0, "oi_chg_7d": 20.0 if i % 2 == 0 else 0.0,
                     "oi_chg_3d": 1.0, "ls_pct_30d": 50.0, "fund_3d_8h": 0.0001, "fund_pct_30d": 50.0,
                     "oi_chg_1d": 0.0, "oi_chg_30d": 0.0, "ls_chg_3d": 0.0})
    res = fe.analyse_backtest(pd.DataFrame(rows), verbose=False)
    blk = res["by_setup"]["Distribution Short"]
    assert blk["base"]["n"] == 40 and blk["base"]["pf"] == 2.0
    skip = [f for f in blk["filters"] if f["filter"] == "skip OI 7d up >= 10%"][0]
    assert skip["n"] == 20 and skip["pf"] == float("inf")
