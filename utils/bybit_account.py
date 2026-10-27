"""
Bybit V5 private account reader — STRICTLY READ ONLY.

Signs requests with HMAC SHA256 (X-BAPI-API-KEY, X-BAPI-TIMESTAMP,
X-BAPI-RECV-WINDOW, X-BAPI-SIGN) using a READ ONLY API key from the environment:

    BYBIT_API_KEY, BYBIT_API_SECRET   (create the key with "Read-Only" permission)
    BYBIT_BASE_URL                    (default https://api.bybit.com; api.bytick.com allowed)
    BYBIT_RECV_WINDOW                 (default 5000 ms)

Guardrails:
  * Only GET is allowed. The single exception is Bybit's futures grid bot DETAIL
    query, which Bybit only exposes as `POST /v5/fgridbot/detail` (a read: it takes
    a bot_id and returns the bot's state). That exact path is the only POST in the
    allowlist below; every other non-GET request raises BybitReadOnlyError before
    anything leaves the machine. There is no order, cancel, close, transfer or
    withdrawal code in this module and there never should be.
  * Bybit answers HTTP 403 to US IP addresses (GitHub hosted runners included).
    That case raises BybitGeoBlocked with a message saying the runner must be non US.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import requests

from utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_BASE_URL = "https://api.bybit.com"
ALLOWED_HOSTS = ("api.bybit.com", "api.bytick.com", "api-testnet.bybit.com")
# Read-only queries Bybit only offers as POST. Nothing else may be POSTed.
READ_ONLY_POST_PATHS = frozenset({"/v5/fgridbot/detail"})
_TIMEOUT = 15


class BybitError(RuntimeError):
    """Bybit answered with a non zero retCode or an unexpected HTTP status."""


class BybitReadOnlyError(BybitError):
    """A write (non GET) request was attempted. This client never writes."""


class BybitGeoBlocked(BybitError):
    """HTTP 403 from Bybit: the caller's IP is in a blocked region (e.g. the US)."""


class BybitAuthMissing(BybitError):
    """BYBIT_API_KEY / BYBIT_API_SECRET are not set."""


def _base_url() -> str:
    url = (os.getenv("BYBIT_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    host = url.split("://", 1)[-1].split("/", 1)[0]
    if host not in ALLOWED_HOSTS:
        raise BybitError(f"BYBIT_BASE_URL host {host!r} not allowed; use one of {ALLOWED_HOSTS}")
    return url


def sign(secret: str, timestamp: str, api_key: str, recv_window: str, payload: str) -> str:
    """Bybit V5 signature: HMAC_SHA256(secret, timestamp + key + recv_window + payload),
    where payload is the query string for GET and the raw JSON body for POST."""
    msg = f"{timestamp}{api_key}{recv_window}{payload}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


class BybitAccount:
    """Minimal read-only V5 client. Inject `session` in tests."""

    def __init__(self, api_key: str | None = None, api_secret: str | None = None,
                 base_url: str | None = None, recv_window: int | None = None,
                 session: requests.Session | None = None) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("BYBIT_API_KEY", "")
        self.api_secret = api_secret if api_secret is not None else os.getenv("BYBIT_API_SECRET", "")
        self.base_url = (base_url or _base_url()).rstrip("/")
        self.recv_window = str(recv_window or os.getenv("BYBIT_RECV_WINDOW") or 5000)
        self.session = session or requests.Session()

    # ── transport ────────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, params: dict | None = None) -> dict:
        method = method.upper()
        if method != "GET" and not (method == "POST" and path in READ_ONLY_POST_PATHS):
            raise BybitReadOnlyError(f"refused {method} {path}: this client is read only")
        if not (self.api_key and self.api_secret):
            raise BybitAuthMissing("set BYBIT_API_KEY and BYBIT_API_SECRET (read only key)")
        params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        ts = str(int(time.time() * 1000))
        if method == "GET":
            payload = urlencode(sorted(params.items()))
            url = f"{self.base_url}{path}" + (f"?{payload}" if payload else "")
            body = None
        else:
            payload = json.dumps(params, separators=(",", ":"))
            url = f"{self.base_url}{path}"
            body = payload
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": self.recv_window,
            "X-BAPI-SIGN": sign(self.api_secret, ts, self.api_key, self.recv_window, payload),
            "Content-Type": "application/json",
        }
        r = self.session.request(method, url, headers=headers, data=body, timeout=_TIMEOUT)
        if r.status_code == 403:
            raise BybitGeoBlocked(
                "Bybit returned HTTP 403 (region block). Bybit refuses US IP addresses, "
                "including GitHub hosted runners. Run the watcher on a NON US host "
                "(e.g. your Mac as a self hosted runner, or a free non US VM).")
        if r.status_code != 200:
            raise BybitError(f"HTTP {r.status_code} from {path}: {r.text[:200]}")
        data = r.json()
        if data.get("retCode", 0) != 0:
            raise BybitError(f"{path} retCode {data.get('retCode')}: {data.get('retMsg')}")
        return data.get("result") if "result" in data else data

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params)

    # ── account ──────────────────────────────────────────────────────────────
    def wallet_balance(self, account_type: str = "UNIFIED", coin: str | None = None) -> dict:
        """GET /v5/account/wallet-balance. Returns the first account in result.list."""
        res = self._get("/v5/account/wallet-balance", {"accountType": account_type, "coin": coin})
        lst = (res or {}).get("list") or []
        return lst[0] if lst else {}

    def positions(self, category: str = "linear", settle_coin: str = "USDT",
                  symbol: str | None = None) -> list[dict]:
        """GET /v5/position/list (all pages). Only rows with size > 0."""
        out: list[dict] = []
        cursor = None
        for _ in range(20):
            res = self._get("/v5/position/list", {"category": category, "settleCoin": settle_coin,
                                                  "symbol": symbol, "limit": 200, "cursor": cursor})
            out += [p for p in (res.get("list") or []) if float(p.get("size") or 0) > 0]
            cursor = res.get("nextPageCursor")
            if not cursor:
                break
        return out

    def closed_pnl(self, category: str = "linear", start_ms: int | None = None,
                   end_ms: int | None = None, symbol: str | None = None,
                   limit: int = 100) -> list[dict]:
        """GET /v5/position/closed-pnl (max 7 day window per Bybit)."""
        res = self._get("/v5/position/closed-pnl", {"category": category, "startTime": start_ms,
                                                    "endTime": end_ms, "symbol": symbol,
                                                    "limit": limit})
        return res.get("list") or []

    def executions(self, category: str = "linear", start_ms: int | None = None,
                   symbol: str | None = None, limit: int = 100) -> list[dict]:
        """GET /v5/execution/list."""
        res = self._get("/v5/execution/list", {"category": category, "startTime": start_ms,
                                               "symbol": symbol, "limit": limit})
        return res.get("list") or []

    # ── futures grid bots ────────────────────────────────────────────────────
    def futures_grid_detail(self, bot_id: str) -> dict:
        """POST /v5/fgridbot/detail {bot_id} (read only query; the one allowlisted POST).
        Returns the `detail` object (min_price, max_price, cell_number, leverage,
        total_investment, current_position, entry_price, mark_price,
        liquidation_price, stop_loss_price, m_m_rate, tick_size, status, ...)."""
        res = self._request("POST", "/v5/fgridbot/detail", {"bot_id": str(bot_id)})
        if isinstance(res, dict) and res.get("status_code", 0) not in (0, None):
            raise BybitError(f"fgridbot/detail status_code {res.get('status_code')}: "
                             f"{res.get('debug_msg')}")
        return (res or {}).get("detail") or res or {}

    def futures_grid_bots(self, bot_ids: list[str] | None = None) -> list[dict]:
        """Details for registered bot ids. Bybit's futures grid API has NO list endpoint
        (only validate/create/close/detail), so ids come from a registry: `bot_ids`, or
        BYBIT_GRID_BOT_IDS (comma separated). Per bot failures (e.g. a read only key not
        permitted to call fgridbot/detail) are collected in self.grid_errors, not raised."""
        ids = bot_ids if bot_ids is not None else [
            s.strip() for s in os.getenv("BYBIT_GRID_BOT_IDS", "").split(",") if s.strip()]
        out: list[dict] = []
        self.grid_errors: list[dict] = []
        for bid in ids:
            try:
                d = self.futures_grid_detail(bid)
                d.setdefault("bot_id", bid)
                out.append(d)
            except BybitGeoBlocked:
                raise
            except BybitError as exc:
                kind = "permission" if is_permission_error(exc) else "error"
                self.grid_errors.append({"bot_id": bid, "kind": kind, "error": str(exc)})
                log.warning("bybit_account: grid %s detail failed (%s): %s", bid, kind, exc)
        return out


# retCodes Bybit uses for key/permission problems (10003 invalid key, 10004 sign,
# 10005 permission denied, 10010 IP not whitelisted, 10007 auth fail) plus HTTP 401.
_PERMISSION_CODES = ("10003", "10004", "10005", "10007", "10010", "HTTP 401")


def is_permission_error(exc: Exception) -> bool:
    msg = str(exc)
    return any(code in msg for code in _PERMISSION_CODES) or "permission" in msg.lower()
