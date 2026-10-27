from __future__ import annotations
import hashlib
import hmac
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import bybit_account as ba  # noqa: E402


def _resp(status=200, body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body if body is not None else {"retCode": 0, "result": {"list": []}}
    r.text = json.dumps(body or {})
    return r


def _client(resp):
    s = MagicMock()
    s.request.return_value = resp
    return ba.BybitAccount("KEY", "SECRET", base_url="https://api.bybit.com", session=s), s


def test_sign_matches_reference():
    want = hmac.new(b"SECRET", b"1700000000000KEY5000category=linear", hashlib.sha256).hexdigest()
    assert ba.sign("SECRET", "1700000000000", "KEY", "5000", "category=linear") == want


def test_get_sends_signed_headers_and_sorted_query():
    c, s = _client(_resp(body={"retCode": 0, "result": {"list": [{"symbol": "X", "size": "1"},
                                                                 {"symbol": "Y", "size": "0"}]}}))
    out = c.positions()
    assert [p["symbol"] for p in out] == ["X"]
    method, url = s.request.call_args.args
    h = s.request.call_args.kwargs["headers"]
    assert method == "GET"
    assert url.startswith("https://api.bybit.com/v5/position/list?category=linear&limit=200&settleCoin=USDT")
    query = url.split("?", 1)[1]
    assert h["X-BAPI-SIGN"] == ba.sign("SECRET", h["X-BAPI-TIMESTAMP"], "KEY", "5000", query)
    assert h["X-BAPI-API-KEY"] == "KEY" and h["X-BAPI-RECV-WINDOW"] == "5000"


def test_refuses_writes():
    c, s = _client(_resp())
    for m, p in [("POST", "/v5/order/create"), ("POST", "/v5/fgridbot/create"),
                 ("DELETE", "/v5/x"), ("PUT", "/v5/fgridbot/detail"),
                 ("POST", "/v5/asset/withdraw/create")]:
        with pytest.raises(ba.BybitReadOnlyError):
            c._request(m, p, {})
    s.request.assert_not_called()


def test_grid_detail_is_only_allowed_post():
    body = {"retCode": 0, "result": {"status_code": 0, "detail": {"bot_id": "1", "min_price": "0.0016"}}}
    c, s = _client(_resp(body=body))
    d = c.futures_grid_detail("1")
    assert d["min_price"] == "0.0016"
    method, url = s.request.call_args.args
    assert method == "POST" and url.endswith("/v5/fgridbot/detail")
    h = s.request.call_args.kwargs["headers"]
    assert h["X-BAPI-SIGN"] == ba.sign("SECRET", h["X-BAPI-TIMESTAMP"], "KEY", "5000",
                                       s.request.call_args.kwargs["data"])


def test_geoblock_message():
    c, _ = _client(_resp(status=403, body={}))
    with pytest.raises(ba.BybitGeoBlocked, match="NON US"):
        c.wallet_balance()


def test_retcode_error():
    c, _ = _client(_resp(body={"retCode": 10003, "retMsg": "invalid key"}))
    with pytest.raises(ba.BybitError, match="10003"):
        c.wallet_balance()


def test_missing_keys(monkeypatch):
    c = ba.BybitAccount("", "", base_url="https://api.bybit.com", session=MagicMock())
    with pytest.raises(ba.BybitAuthMissing):
        c.wallet_balance()


def test_base_url_allowlist(monkeypatch):
    monkeypatch.setenv("BYBIT_BASE_URL", "https://api.bytick.com")
    assert ba._base_url() == "https://api.bytick.com"
    monkeypatch.setenv("BYBIT_BASE_URL", "https://evil.example.com")
    with pytest.raises(ba.BybitError):
        ba._base_url()


def test_wallet_and_grid_ids_from_env(monkeypatch):
    body = {"retCode": 0, "result": {"list": [{"totalEquity": "500"}]}}
    c, _ = _client(_resp(body=body))
    assert c.wallet_balance()["totalEquity"] == "500"
    monkeypatch.setenv("BYBIT_GRID_BOT_IDS", "a, b")
    c2, s2 = _client(_resp(body={"retCode": 0, "result": {"status_code": 0, "detail": {"bot_id": "a"}}}))
    assert len(c2.futures_grid_bots()) == 2
    assert s2.request.call_count == 2


def test_grid_permission_error_collected_not_raised():
    c, _ = _client(_resp(body={"retCode": 10005, "retMsg": "Permission denied for current apikey"}))
    assert c.futures_grid_bots(["9"]) == []
    assert c.grid_errors[0]["kind"] == "permission" and c.grid_errors[0]["bot_id"] == "9"


def test_grid_geoblock_still_raises():
    c, _ = _client(_resp(status=403, body={}))
    with pytest.raises(ba.BybitGeoBlocked):
        c.futures_grid_bots(["9"])
