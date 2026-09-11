"""
Paper Trades API
Endpoints for opening, monitoring, and closing paper trades.
The /check endpoint fetches current prices and auto-marks target/stop hits.
"""
from __future__ import annotations
import datetime
import yfinance as yf
from fastapi import APIRouter
from pydantic import BaseModel
from paper_trades.db import (
    init_db, open_trade, close_trade, get_trades, get_trade,
    delete_trade, get_performance_stats,
)
from utils.logger import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/paper_trades")
init_db()


class OpenTradeRequest(BaseModel):
    ticker:          str
    setup_label:     str
    setup_category:  str
    action:          str
    entry_price:     float
    target_price:    float
    stop_price:      float
    predicted_rr:    float | None = None
    conviction:      float
    macro_score:     float | None = None
    trade_note:      str = ""
    entry_date:      str = ""          # defaults to today if blank


class CloseTradeRequest(BaseModel):
    exit_price: float
    status:     str       # target_hit | stop_hit | manual_close | expired
    exit_date:  str = ""  # defaults to today


@router.get("")
def list_trades(status: str | None = None):
    return {"trades": get_trades(status)}


@router.post("")
def create_trade(req: OpenTradeRequest):
    entry_date = req.entry_date or datetime.date.today().isoformat()
    trade_id = open_trade(
        ticker        = req.ticker.upper(),
        setup_label   = req.setup_label,
        setup_category= req.setup_category,
        action        = req.action,
        entry_price   = req.entry_price,
        target_price  = req.target_price,
        stop_price    = req.stop_price,
        predicted_rr  = req.predicted_rr,
        conviction    = req.conviction,
        macro_score   = req.macro_score,
        trade_note    = req.trade_note,
        entry_date    = entry_date,
    )
    log.info("paper_trade opened: #%d %s %s @ %.4f", trade_id, req.action, req.ticker, req.entry_price)
    return {"id": trade_id, "status": "opened"}


@router.put("/{trade_id}/close")
def close_trade_endpoint(trade_id: int, req: CloseTradeRequest):
    exit_date = req.exit_date or datetime.date.today().isoformat()
    ok = close_trade(trade_id, req.exit_price, exit_date, req.status)
    if not ok:
        return {"error": "Trade not found"}
    return {"id": trade_id, "status": req.status}


@router.delete("/{trade_id}")
def delete_trade_endpoint(trade_id: int):
    delete_trade(trade_id)
    return {"deleted": trade_id}


@router.get("/stats")
def stats():
    return get_performance_stats()


@router.get("/live")
def live_prices():
    """
    Return open trades enriched with current price, live P&L %, and
    progress toward target/stop — read-only, never closes anything.
    """
    open_trades = get_trades(status="open")
    if not open_trades:
        return {"trades": []}

    tickers = list({t["ticker"] for t in open_trades})
    prices: dict[str, float] = {}

    crypto = [t for t in tickers if t.endswith("-USD")]
    stocks = [t for t in tickers if not t.endswith("-USD")]

    if crypto:
        try:
            from utils.bybit import fetch_ohlcv
            data = fetch_ohlcv(crypto, days=3)
            for ticker, df in data.items():
                if not df.empty:
                    prices[ticker] = float(df["close"].iloc[-1])
        except Exception as exc:
            log.warning("live: bybit failed — %s", exc)

    if stocks:
        try:
            raw = yf.download(stocks, period="2d", interval="1d",
                              progress=False, auto_adjust=True)
            closes = raw["Close"] if hasattr(raw["Close"], "columns") else raw[["Close"]]
            for t in stocks:
                if t in closes.columns:
                    prices[t] = float(closes[t].dropna().iloc[-1])
        except Exception as exc:
            log.warning("live: yfinance failed — %s", exc)

    enriched = []
    for trade in open_trades:
        t = dict(trade)
        current = prices.get(t["ticker"])
        t["current_price"] = current

        if current is not None:
            entry  = t["entry_price"]
            target = t["target_price"]
            stop   = t["stop_price"]
            action = t["action"]

            # P&L % from entry
            if action == "BUY":
                t["live_pnl_pct"]      = round((current - entry) / entry * 100, 2)
                # How far through the entry→target range (0–100, can exceed)
                total_range            = target - stop
                t["progress_pct"]      = round((current - stop) / total_range * 100, 1) if total_range else 50
                t["pct_to_target"]     = round((target - current) / current * 100, 2)
                t["pct_to_stop"]       = round((current - stop)   / current * 100, 2)
            else:  # SELL/EXIT downside MR
                t["live_pnl_pct"]      = round((entry - current) / entry * 100, 2)
                total_range            = stop - target
                t["progress_pct"]      = round((stop - current) / total_range * 100, 1) if total_range else 50
                t["pct_to_target"]     = round((current - target) / current * 100, 2)
                t["pct_to_stop"]       = round((stop - current)   / current * 100, 2)

            # Days held so far
            try:
                entry_dt         = datetime.date.fromisoformat(t["entry_date"])
                t["days_held"]   = (datetime.date.today() - entry_dt).days
            except Exception:
                t["days_held"]   = None
        else:
            t["live_pnl_pct"] = None
            t["progress_pct"] = None
            t["pct_to_target"] = None
            t["pct_to_stop"]   = None
            t["days_held"]     = None

        enriched.append(t)

    return {"trades": enriched, "prices": prices}


@router.post("/check")
def check_open_trades():
    """
    Fetch current prices for all open trades and auto-close any that have
    hit their target or stop loss. Returns a summary of what was resolved.
    """
    open_trades = get_trades(status="open")
    if not open_trades:
        return {"checked": 0, "resolved": []}

    # Batch-fetch current prices
    tickers = list({t["ticker"] for t in open_trades})
    today = datetime.date.today().isoformat()

    # Try Bybit first for crypto (BTC-USD style), yfinance for stocks
    prices: dict[str, float] = {}
    crypto = [t for t in tickers if t.endswith("-USD")]
    stocks = [t for t in tickers if not t.endswith("-USD")]

    if crypto:
        try:
            from utils.bybit import fetch_ohlcv
            data = fetch_ohlcv(crypto, days=3)
            for ticker, df in data.items():
                if not df.empty:
                    prices[ticker] = float(df["close"].iloc[-1])
        except Exception as exc:
            log.warning("check: bybit fetch failed — %s", exc)

    if stocks:
        try:
            raw = yf.download(stocks, period="2d", interval="1d",
                              progress=False, auto_adjust=True)
            closes = raw["Close"] if hasattr(raw["Close"], "columns") else raw[["Close"]]
            for t in stocks:
                col = t if t in closes.columns else None
                if col:
                    prices[t] = float(closes[col].dropna().iloc[-1])
        except Exception as exc:
            log.warning("check: yfinance fetch failed — %s", exc)

    resolved = []
    for trade in open_trades:
        current = prices.get(trade["ticker"])
        if current is None:
            continue

        action = trade["action"]
        target = trade["target_price"]
        stop   = trade["stop_price"]
        entry  = trade["entry_price"]
        status = None

        if action == "BUY":
            if current >= target:
                status = "target_hit"
            elif current <= stop:
                status = "stop_hit"
        else:  # SELL/EXIT (downside MR)
            if current <= target:
                status = "target_hit"
            elif current >= stop:
                status = "stop_hit"

        if status:
            # Estimate bars held (rough calendar days)
            try:
                entry_dt = datetime.date.fromisoformat(trade["entry_date"])
                bars = (datetime.date.today() - entry_dt).days
            except Exception:
                bars = None

            close_trade(trade["id"], current, today, status, bars)
            pnl = (current - entry) / entry * 100 if action == "BUY" else (entry - current) / entry * 100
            resolved.append({
                "id":     trade["id"],
                "ticker": trade["ticker"],
                "status": status,
                "entry":  entry,
                "exit":   current,
                "pnl_pct": round(pnl, 2),
            })
            log.info("paper_trade resolved: #%d %s %s (%.2f%%)", trade["id"], trade["ticker"], status, pnl)

    return {"checked": len(open_trades), "resolved": resolved}
