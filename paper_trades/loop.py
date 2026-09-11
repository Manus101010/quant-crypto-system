"""
Paper Trading Loop
==================
The automated feedback loop that:
  1. Runs the scanner (crypto + stocks)
  2. Opens paper trades for the top high-conviction setups not already open
  3. Checks open positions against current prices → closes at target/stop
  4. Recomputes signal stats (profit factor, win rate, edge decay)
  5. Adjusts conviction multipliers so the scanner learns from outcomes

Called by the APScheduler on a schedule, and also exposed via API for
manual triggering.
"""
from __future__ import annotations
import datetime
import json
from utils.logger import get_logger
from paper_trades import db as pdb
from paper_trades import stats as pstats

log = get_logger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
MAX_AUTO_TRADES_PER_RUN = 3   # max new trades opened per loop run
MIN_CONVICTION          = 65  # only auto-open if conviction ≥ this
MIN_VOL_USD_M           = 1.0 # skip illiquid setups in auto mode
# Don't auto-open SELL/EXIT or WAIT signals — only BUY setups
AUTO_OPEN_ACTIONS       = {"BUY"}
# Setups considered too risky / warning-only for auto trading
SKIP_LABELS             = {"Far Above 200-SMA", "Overextended — Reversion Risk", "Watch — Below Key Levels", "Building Base", "Falling Knife — Avoid"}


def _price_parse(s: str) -> float | None:
    """Parse the first $price from a trade suggestion string."""
    import re
    m = re.search(r'\$([\d,]+\.?\d*)', s or '')
    return float(m.group(1).replace(',', '')) if m else None


def _rr_parse(s: str | None) -> float | None:
    """Parse '6.1:1' → 6.1."""
    if not s:
        return None
    try:
        return float(str(s).split(':')[0])
    except Exception:
        return None


def check_positions() -> dict:
    """
    Fetch current prices for all open paper trades and auto-close any
    that have hit their target or stop.

    Returns summary dict with how many were checked and resolved.
    """
    open_trades = pdb.get_trades(status='open')
    if not open_trades:
        log.info("loop.check_positions: no open trades")
        return {"checked": 0, "resolved": []}

    tickers = list({t["ticker"] for t in open_trades})
    today   = datetime.date.today().isoformat()
    prices  = _fetch_prices(tickers)

    resolved = []
    for trade in open_trades:
        current = prices.get(trade["ticker"])
        if current is None:
            continue

        action = trade["action"]
        status = None
        if action == "BUY":
            if current >= trade["target_price"]:
                status = "target_hit"
            elif current <= trade["stop_price"]:
                status = "stop_hit"
        else:  # SELL/EXIT downside MR
            if current <= trade["target_price"]:
                status = "target_hit"
            elif current >= trade["stop_price"]:
                status = "stop_hit"

        if status:
            try:
                entry_dt = datetime.date.fromisoformat(trade["entry_date"])
                bars = (datetime.date.today() - entry_dt).days
            except Exception:
                bars = None

            pdb.close_trade(trade["id"], current, today, status, bars)
            pnl = ((current - trade["entry_price"]) / trade["entry_price"] * 100
                   if action == "BUY"
                   else (trade["entry_price"] - current) / trade["entry_price"] * 100)
            resolved.append({
                "id":     trade["id"],
                "ticker": trade["ticker"],
                "status": status,
                "entry":  trade["entry_price"],
                "exit":   current,
                "pnl_pct": round(pnl, 2),
            })
            log.info("loop: resolved #%d %s %s %.2f%%", trade["id"], trade["ticker"], status, pnl)

    # After resolving, recompute signal stats so learning is up to date
    if resolved:
        pstats.recompute_all()

    return {"checked": len(open_trades), "resolved": resolved}


def run_scan_and_open(
    universe: str = "crypto",   # "crypto" | "stocks" | "both"
    top_n: int = 100,
    macro_score: float | None = None,
) -> dict:
    """
    Run the scanner and open paper trades for top high-conviction setups
    that aren't already open.

    Returns dict with scan_count, opened, skipped reasons.
    """
    from utils.crypto_universe import get_top_crypto
    from skills.scanner import run_scan, run_crypto_scan, ScanCriteria

    today = datetime.date.today().isoformat()

    # Already-open tickers to avoid doubling up
    open_set = {t["ticker"] for t in pdb.get_trades(status="open")}

    # Get current signal multipliers (learning feedback)
    multipliers = pstats.get_conviction_multipliers()

    results = []

    if universe in ("crypto", "both"):
        tickers = get_top_crypto(top_n)
        df = run_crypto_scan(tickers=tickers, criteria=ScanCriteria(
            min_price=0.0, above_sma200=False, above_sma50=False,
            min_volume_usd_m=MIN_VOL_USD_M,
        ), regime_score=macro_score)
        if not df.empty:
            results.extend(df.to_dict("records"))

    if universe in ("stocks", "both"):
        df = run_scan(criteria=ScanCriteria(min_volume_usd_m=5.0),
                      regime_score=macro_score)
        if not df.empty:
            results.extend(df.to_dict("records"))

    # Apply learning multiplier to conviction scores
    for r in results:
        mult = multipliers.get(r.get("setup_label", ""), 1.0)
        r["_adj_conviction"] = (r.get("conviction") or 0) * mult

    # Sort by adjusted conviction
    results.sort(key=lambda r: -r.get("_adj_conviction", 0))

    # Push high-conviction BUY setups to external webhook (best-effort)
    try:
        from utils import webhooks
        for r in results:
            if (r.get("trade") or {}).get("action") == "BUY" and (r.get("conviction") or 0) >= 80:
                webhooks.send_setup_alert(r)
    except Exception as exc:
        log.warning("loop: webhook alerting failed: %s", exc)

    opened = []
    skipped = []

    # --- Portfolio-level risk control (roadmap #3 §3 Risk Management) ---
    # Per-trade risk lives in skills/risk_manager.py (Kelly + ATR). Here we govern
    # at the portfolio level: scale the number of new trades by the macro regime
    # scalar and a peak-to-trough drawdown governor. `allowed` replaces the
    # hardcoded MAX_AUTO_TRADES_PER_RUN cap below; allowed == 0 means halt.
    from paper_trades import portfolio_risk
    _risk_state = portfolio_risk.risk_state(macro_score)
    allowed = portfolio_risk.max_new_trades(
        MAX_AUTO_TRADES_PER_RUN, macro_score, state=_risk_state
    )
    if allowed == 0:
        log.info("loop: portfolio risk HALT — opening no trades (%s)",
                 _risk_state["drawdown_gov"]["reason"])
        return {
            "scan_count": len(results),
            "opened":     opened,
            "skipped":    skipped,
            "risk_halt":  True,
            "risk_state": _risk_state,
        }

    for r in results:
        if len(opened) >= allowed:
            break

        ticker      = r.get("ticker", "")
        setup_label = r.get("setup_label", "")
        conviction  = r.get("conviction") or 0
        trade       = r.get("trade") or {}
        action      = trade.get("action", "")
        vol         = r.get("vol_usd_m") or 0

        # Filters
        if ticker in open_set:
            skipped.append({"ticker": ticker, "reason": "already open"})
            continue
        if action not in AUTO_OPEN_ACTIONS:
            skipped.append({"ticker": ticker, "reason": f"action={action}"})
            continue
        if setup_label in SKIP_LABELS:
            skipped.append({"ticker": ticker, "reason": "setup excluded"})
            continue
        if conviction < MIN_CONVICTION:
            skipped.append({"ticker": ticker, "reason": f"conviction={conviction:.0f} < {MIN_CONVICTION}"})
            continue

        # Parse prices from trade suggestion
        entry_p  = _price_parse(trade.get("entry",  "")) or r.get("price")
        target_p = _price_parse(trade.get("target", ""))
        stop_p   = _price_parse(trade.get("stop",   ""))

        if not entry_p or not target_p or not stop_p:
            skipped.append({"ticker": ticker, "reason": "could not parse prices"})
            continue

        trade_id = pdb.open_trade(
            ticker         = ticker,
            setup_label    = setup_label,
            setup_category = r.get("setup_category", ""),
            action         = action,
            entry_price    = entry_p,
            target_price   = target_p,
            stop_price     = stop_p,
            predicted_rr   = _rr_parse(trade.get("rr")),
            conviction     = conviction,
            macro_score    = macro_score,
            trade_note     = trade.get("note", ""),
            entry_date     = today,
        )
        open_set.add(ticker)
        opened.append({
            "id":           trade_id,
            "ticker":       ticker,
            "setup_label":  setup_label,
            "conviction":   conviction,
            "action":       action,
            "entry":        entry_p,
            "target":       target_p,
            "stop":         stop_p,
        })
        log.info("loop: opened #%d %s %s conv=%.0f", trade_id, action, ticker, conviction)

    return {
        "scan_count": len(results),
        "opened":     opened,
        "skipped":    skipped[:10],   # truncate for readability
        "risk_halt":  False,
        "risk_state": _risk_state,
    }


def full_loop(universe: str = "crypto", top_n: int = 100, macro_score: float | None = None) -> dict:
    """
    Run the full loop in one call: check positions → scan → open new trades → recompute stats.
    Returns a combined result dict written to the loop log.
    """
    log.info("loop: starting full loop (universe=%s, top_n=%d)", universe, top_n)

    check_result = check_positions()
    scan_result  = run_scan_and_open(universe=universe, top_n=top_n, macro_score=macro_score)
    loop_stats   = pstats.get_summary()

    result = {
        "run_at":       datetime.datetime.now().isoformat(timespec="seconds"),
        "universe":     universe,
        "positions":    check_result,
        "scan":         scan_result,
        "signal_stats": loop_stats,
    }

    # Persist to loop log table
    pdb.log_loop_run(result)
    log.info("loop: done — checked=%d resolved=%d opened=%d",
             check_result["checked"], len(check_result["resolved"]), len(scan_result["opened"]))
    return result


def _fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch latest prices from Bybit (crypto) or yfinance (stocks)."""
    import yfinance as yf
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
            log.warning("loop._fetch_prices bybit: %s", exc)

    if stocks:
        try:
            raw = yf.download(stocks, period="2d", interval="1d",
                              progress=False, auto_adjust=True)
            closes = raw["Close"] if hasattr(raw["Close"], "columns") else raw[["Close"]]
            for t in stocks:
                if t in closes.columns:
                    prices[t] = float(closes[t].dropna().iloc[-1])
        except Exception as exc:
            log.warning("loop._fetch_prices yfinance: %s", exc)

    return prices
