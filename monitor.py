#!/usr/bin/env python3
"""
QuantCore Monitor — standalone always-on trigger watcher.

Runs OUTSIDE Streamlit (tmux / systemd on a cheap always-on host). On each poll
it evaluates every active trigger armed by the scanner and, when a condition is
met, pushes a Telegram alert to the user's phone and marks the trigger fired.

SIGNAL ONLY: this process reads public market data (ccxt, read-only) and sends
notifications. It never places orders, holds keys, or touches an account.

Usage:
    python monitor.py                 # default 180s poll
    python monitor.py --interval 60   # 1-minute poll
    python monitor.py --once          # single pass then exit (for testing/cron)

Rate limits: symbols are batched per poll (one price fetch for all price
triggers; grouped candle fetches for indicator triggers). ccxt paces each venue.
"""
from __future__ import annotations
import time
import argparse
import json
import datetime
import numpy as np
import pandas as pd

from triggers import db as tdb
from utils import exchange
from utils import telegram
from utils.logger import get_logger

log = get_logger("monitor")

_MIN_INTERVAL = 60          # respect exchange rate limits
_CANDLE_LIMIT = 120


def _rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _fmt_price(p) -> str:
    if p is None:
        return "—"
    p = float(p)
    if p < 0.01:  return f"${p:.6f}"
    if p < 1:     return f"${p:.4f}"
    if p < 100:   return f"${p:.2f}"
    return f"${p:,.2f}"


# One plain-English line per setup: what kind of trade this is.
_SETUP_PLAIN = {
    "Momentum Runner":            "a coin in a strong uptrend making a fresh push higher",
    "Relative Strength Leader":   "a coin that's been beating Bitcoin — a market leader",
    "Donchian Breakout (55d)":    "a breakout to a new 55-day high",
    "Breakdown Short (55d low)":  "a downtrending coin breaking to a new 55-day low",
    "RSI-2 Pullback (Connors)":   "a short, sharp dip inside an uptrend",
    "BB Bounce Setup":            "a dip to the bottom of its normal range",
    "Williams %R Oversold":       "a dip to an oversold level inside an uptrend",
    "Distribution Short":         "a coin that ran up hard, went quiet and is slipping to the bottom of its range",
    "Downtrend Bounce Fade":      "a sharp bounce in a downtrending coin that is losing steam",
}


_NO_GRID = {"Distribution Short", "Downtrend Bounce Fade"}


def _why_plain(trg: dict) -> str:
    """Why it fired, in words (instead of RSI/indicator shorthand)."""
    try:
        cond = json.loads(trg.get("condition_json") or "{}")
    except Exception:                               # noqa: BLE001
        cond = {}
    kind, lvl = cond.get("kind"), cond.get("level")
    if kind == "breakout":
        return (f"Price just pushed above {_fmt_price(lvl)} — the level it was waiting for — "
                f"and the move isn't overheated yet.")
    if kind == "breakdown":
        return (f"Price just dropped below {_fmt_price(lvl)} — the level it was waiting for — "
                f"and it isn't oversold yet.")
    if kind == "mr_reversal":
        return "It had sold off hard and has just started to bounce back up."
    if kind == "mr_reversal_short":
        return "It had run up too far and has just started to turn back down."
    if kind == "enter_now_short":
        return "Yesterday's daily close completed the setup. The research enters right away."
    return "Its trigger condition was met."


def _pct(a, b) -> str:
    return f"{(b / a - 1) * 100:+.1f}%" if a and b else ""


def _alert_text(trg: dict, price: float, reason: str) -> str:
    short = (trg.get("direction") or "long") == "short"
    coin = trg["symbol"].replace("-USD", "")
    label = trg.get("setup_label") or "setup"
    stop, target = trg.get("stop"), trg.get("target")
    try:
        from triggers.scan import _management_params
        m = _management_params(label) or {}
    except Exception:                               # noqa: BLE001
        m = {}
    trailing = bool(m.get("trailing")) and not target
    hold = m.get("max_hold")

    head = (f"🔴 <b>SHORT signal — {coin}</b>  (Bybit USDT perp)" if short
            else f"🟢 <b>LONG signal — {coin}</b>  (Bybit USDT perp)")
    lines = [head, f"<i>{label}: {_SETUP_PLAIN.get(label, 'a validated setup')}.</i>", "",
             f"<b>Why now:</b> {_why_plain(trg)}",
             f"<b>Price now:</b> {_fmt_price(price)}", "", "📋 <b>The plan</b>"]
    lines.append(f"• {'Sell (short) around' if short else 'Buy around'}: {_fmt_price(price)}")
    if stop:
        loss = abs(price - stop) / price * 100
        lines.append(f"• Stop loss: {_fmt_price(stop)}  (−{loss:.1f}%) — "
                     f"{'buy back' if short else 'sell'} if it gets here; that caps your loss")
    part = m.get("partial") or {}
    if part.get("at_r") and stop:
        dist = abs(price - stop)
        ppx = price - part["at_r"] * dist if short else price + part["at_r"] * dist
        lines.append(f"• Take <b>{part.get('frac', 0.5) * 100:.0f}% profit at {_fmt_price(ppx)}</b> "
                     f"({_pct(price, ppx)}, +{part['at_r']:g}× your risk)"
                     + (", then move your stop to your entry — the rest can't lose"
                        if part.get("breakeven") else ""))
    if trailing:
        lines.append(("• For the rest: no" if part.get("at_r") else "• No")
                     + " fixed target — a <b>trailing stop</b> follows the price "
                     f"{'down' if short else 'up'} and locks in profit (Bybit does this for "
                     "you — see below).")
    elif target:
        lines.append(f"• Take profit: {_fmt_price(target)}  ({_pct(price, target)})")
        if stop and abs(price - stop):
            ratio = abs(target - price) / abs(price - stop)
            lines.append(f"• Reward vs risk: about {ratio:.1f} to 1 — the win is {ratio:.1f}× the loss")
    if hold:
        lines.append(f"• Time limit: close it after {hold} days if nothing's hit")
    pj = _projection_line(trg, price, label)
    if pj:
        lines.append(pj)
    bb = _bybit_block(trg, price, m)
    if bb:
        lines += ["", bb]
    sz = _sizing_line(trg, price)
    if sz:
        lines += ["", sz]
    # Oct 2026 research: for the new research setups a plain position with a stop
    # beat every grid tested, so no grid suggestion is attached to them.
    gb = "" if label in _NO_GRID else _grid_block(trg, price, m)
    if gb:
        lines += ["", gb]
    # Bitcoin backdrop in words (a warning, never a block).
    try:
        from utils import btc_regime
        lab = btc_regime.get_btc_regime()["label"]
        if lab == btc_regime.RISK_ON:
            txt = ("headwind — Bitcoin is trending up, shorts are fighting it" if short
                   else "tailwind — Bitcoin is trending up")
        elif lab == btc_regime.RISK_OFF:
            txt = ("tailwind — Bitcoin is weak" if short
                   else "headwind — Bitcoin is weak, be extra careful with buys")
        else:
            txt = "neutral — Bitcoin is mixed, no strong push either way"
        lines.append(f"🧭 Market: {txt}")
    except Exception as exc:                        # noqa: BLE001 — never block an alert
        log.debug("btc_regime stamp failed: %s", exc)
    try:
        from utils import events
        for w in (events.coin_warning(trg["symbol"], 7), events.macro_warning(3)):
            if w:
                lines.append(w)
    except Exception as exc:                        # noqa: BLE001 — never block an alert
        log.debug("event warnings failed: %s", exc)
    lines.append("\n<i>Signal only — you decide and place the trade. "
                 "Tap \"Took it\" on the scanner if you enter.</i>")
    return "\n".join(lines)


def _projection_line(trg: dict, price: float, label: str) -> str:
    """What to expect, from this setup's backtest: odds of a win, the typical
    winner as a multiple of the risk → a price and $ figure for THIS trade."""
    try:
        from backtesting.crypto_validation import load_validation
        from triggers.outcomes import portfolio_heat
        st_ = ((load_validation() or {}).get("stats") or {}).get(label)
        stop = trg.get("stop")
        if not st_ or not stop or not st_.get("avg_loss"):
            return ""
        wr = st_["win_rate"]
        win_r = st_["avg_win"] / abs(st_["avg_loss"])        # typical winner, in R
        short = (trg.get("direction") or "long") == "short"
        dist = abs(price - stop)
        px = price - win_r * dist if short else price + win_r * dist
        risk = portfolio_heat()["next_risk"] or portfolio_heat()["risk_per_trade"]
        odds = f"{wr * 100:.0f}% of trades"
        days = st_.get("median_bars_held")
        return (f"📈 <b>What to expect</b> (backtest, {st_['n']:,} past trades): {odds} win. "
                f"Winners averaged ~{win_r:.1f}× the risk → around {_fmt_price(px)} "
                f"({_pct(price, px)}), ≈ +${win_r * risk:,.0f}"
                + (f", usually within ~{days:.0f} days" if days else "")
                + f". The rest usually hit the stop (≈ −${risk:,.0f}).")
    except Exception as exc:                        # noqa: BLE001
        log.debug("projection failed: %s", exc)
        return ""


def _bybit_block(trg: dict, price: float, m: dict) -> str:
    """Exact order setup on Bybit: TP/SL on the order, the partial take-profit,
    and Bybit's native trailing stop (distance = the initial risk, as tested).
    Size/leverage come from _sizing_line (your $-margin rules)."""
    try:
        stop, target = trg.get("stop"), trg.get("target")
        if not stop or not price:
            return ""
        short = (trg.get("direction") or "long") == "short"
        dist = abs(price - stop)
        part = m.get("partial") or {}
        trailing = bool(m.get("trailing")) and not target
        f = _fmt_price
        out = [f"⚙️ <b>On Bybit</b> — open a <b>{'Short' if short else 'Long'}</b> "
               "(isolated margin) and set on the order:",
               f"• <b>Stop-loss {f(stop)}</b>" + (f" · <b>Take-profit {f(target)}</b>" if target else "")]
        if part.get("at_r"):
            ppx = price - part["at_r"] * dist if short else price + part["at_r"] * dist
            out.append(f"• Partial take-profit: close <b>{part.get('frac', 0.5) * 100:.0f}% at "
                       f"{f(ppx)}</b>, then move the stop-loss to your entry")
        if trailing:
            out.append(f"• <b>Trailing stop</b>: distance <b>{f(dist)}</b> "
                       f"({dist / price * 100:.1f}%) — Bybit moves it with the price automatically")
        out.append("Bybit closes the trade at the stop by itself — no need to watch it.")
        return "\n".join(out)
    except Exception as exc:                        # noqa: BLE001 — never block an alert
        log.debug("bybit block failed: %s", exc)
        return ""


def _grid_block(trg: dict, price: float, m: dict) -> str:
    """Optional Bybit futures grid-bot version of the same trade (same stop, same
    worst-case $ loss)."""
    try:
        from desk.gridplan import grid_for_signal
        from triggers.outcomes import portfolio_heat
        risk = portfolio_heat()["next_risk"]
        if risk <= 0:
            return ""
        stop = trg.get("stop")
        atr = abs(price - stop) / float(m.get("stop_mult") or 3.0) if stop else None
        g = grid_for_signal(trg.get("direction") or "long", price, stop,
                            trg.get("target"), atr, risk)
        if not g.get("ok"):
            return f"🤖 <b>Grid bot:</b> not suggested here ({g.get('note', '')})."
        f = _fmt_price
        below = "below" if g["mode"] == "Long" else "above"
        gap = abs(g["stop_loss"] - g["liq_est"]) / g["stop_loss"] * 100
        tp = (f"• Take-profit price: {f(g['take_profit'])}" if g["take_profit"] else
              "• Take-profit price: leave empty (trailing trade — I'll tell you when to stop it)")
        return "\n".join([
            "🤖 <b>Or run it as a Bybit futures grid bot</b> (profits from the swings):",
            f"• Mode: <b>{g['mode']}</b> · Leverage: <b>{g['leverage']}×</b> (isolated)",
            f"• Price range: {f(g['lower'])} – {f(g['upper'])} · <b>{g['grids']} grids</b> "
            f"(~{g['step_pct']:.1f}% apart, ~{g['net_per_grid_pct']:.1f}% ≈ "
            f"${g['notional'] / g['grids'] * g['net_per_grid_pct'] / 100:,.2f} profit per completed swing)",
            f"• Investment: about <b>${g['margin']:,.0f}</b>",
            f"• Stop-loss price: <b>{f(g['stop_loss'])}</b> (set it in the bot's TP/SL settings)",
            tp,
            f"• Liquidation ≈ {f(g['liq_est'])} ({gap:.0f}% {below} your stop, so the stop hits first). "
            "Check the bot's own figure is also past your stop before starting.",
            f"Worst case (every grid order filled, then stopped): lose ~${g['worst_loss']:.0f}. "
            "Tick \"Took it\" and I'll message you to shut the bot off if the stop is hit.",
        ])
    except Exception as exc:                        # noqa: BLE001 — never block an alert
        log.debug("grid block failed: %s", exc)
        return ""


def _sizing_line(trg: dict, price: float) -> str:
    """How much to buy so a stop-out loses your set risk (fits the heat budget)."""
    try:
        from triggers.outcomes import portfolio_heat
        h = portfolio_heat()
        stop = trg.get("stop")
        if not stop or not price:
            return ""
        frac = abs(price - stop) / price
        if frac <= 0:
            return ""
        budget = (f"🔥 Money at risk in trades you've taken: ${h['open_risk']:.0f} "
                  f"of your ${h['cap']:.0f} limit")
        if h["next_risk"] <= 0:
            return (f"{budget}\n⚠️ <b>You're at your limit</b> — skip this one, or wait "
                    f"until an open trade is closed or safe.")
        from config import POSITION_MARGIN_USD, MAX_LOSS_PCT_OF_MARGIN, MAX_LEVERAGE
        coin = trg["symbol"].replace("-USD", "")
        # Fixed margin, leverage chosen so the stop loses at most MAX_LOSS_PCT of it.
        lev = int(min(MAX_LEVERAGE, (MAX_LOSS_PCT_OF_MARGIN / 100) / frac))
        if lev < 1:
            return (f"💰 <b>Size:</b> skip. The stop is {frac * 100:.1f}% away, more than "
                    f"your {MAX_LOSS_PCT_OF_MARGIN:.0f}% max loss even at 1x.\n{budget}")
        pos = POSITION_MARGIN_USD * lev
        loss = pos * frac
        if loss > h["next_risk"] + 1e-9:
            return (f"{budget}\n⚠️ <b>You're at your limit</b> — skip this one, or wait "
                    f"until an open trade is closed or safe.")
        tgt = trg.get("target")
        win = f", hit the target and you make ~${pos * abs(tgt - price) / price:,.2f}" if tgt else ""
        return (f"💰 <b>Size:</b> <b>${POSITION_MARGIN_USD:,.0f} margin at {lev}x</b> "
                f"(isolated) = a ${pos:,.0f} position in {coin}\n"
                f"    If the stop hits you lose ~${loss:,.2f} "
                f"({loss / POSITION_MARGIN_USD * 100:.0f}% of the margin){win}.\n{budget}")
    except Exception as exc:                        # noqa: BLE001
        log.debug("sizing line failed: %s", exc)
        return ""


def _management_note(setup_label: str | None = None) -> str:
    """Per-setup trade management from the saved validation (breakouts trail; the
    rest take a fixed target)."""
    m = None
    try:
        from backtesting.crypto_validation import load_validation
        v = load_validation() or {}
        if setup_label:
            m = (v.get("management_by_setup") or {}).get(setup_label)
        if not m and not v.get("management_by_setup"):
            m = (v.get("meta", {}).get("params", {}) or {}).get("management")
        if not m and setup_label:
            from backtesting.crypto_optimize import management_for
            m = management_for(setup_label)
    except Exception:
        m = None
    if not m:
        return "Manage per the Validation page."
    if m.get("note"):
        return m["note"]
    if m.get("trailing"):
        return f"Trail a {m['stop_mult']}×ATR stop, let winners run (hold ≤{m['max_hold']}d)."
    return (f"{m['stop_mult']}×ATR stop, take profit at {m['target_r']}R "
            f"(hold ≤{m['max_hold']}d).")


def _indicators(df: pd.DataFrame) -> dict | None:
    """Live indicator bundle from candles: price, prior close, RSI(2), RSI(14), 20d mean."""
    if len(df) < 25:
        return None
    close = df["close"]
    rsi2 = _rsi_series(close, 2).dropna()
    rsi14 = _rsi_series(close, 14).dropna()
    if len(rsi2) < 2 or len(rsi14) < 1:
        return None
    return {
        "price":     float(close.iloc[-1]),
        "prev":      float(close.iloc[-2]),
        "rsi2_now":  float(rsi2.iloc[-1]),
        "rsi2_prev": float(rsi2.iloc[-2]),
        "rsi14_now": float(rsi14.iloc[-1]),
        "mean20":    float(close.iloc[-20:].mean()),
    }


def _evaluate(trg: dict, ind: dict) -> tuple[str, str]:
    """
    Returns (verdict, reason) where verdict is 'fire' | 'invalidate' | 'wait'.
    Multi-factor confirmation per setup kind; auto-invalidates on a stop hit.
    """
    import json as _json
    cond = _json.loads(trg["condition_json"]) if trg.get("condition_json") else {}
    kind = cond.get("kind")
    price, prev = ind["price"], ind["prev"]
    stop = cond.get("stop")

    if kind == "mr_reversal":
        if stop and price <= stop:
            return ("invalidate", f"stop {_fmt_price(stop)} hit before the bounce")
        lvl = cond.get("rsi2_level", 12.0)
        mean = cond.get("mean")
        turned    = ind["rsi2_prev"] < lvl <= ind["rsi2_now"]      # RSI(2) turning up
        green     = price > prev                                    # price confirming
        below_mean = mean is None or price < mean                   # still in reversion zone
        above_stop = stop is None or price > stop
        if turned and green and below_mean and above_stop:
            return ("fire", f"RSI2 {ind['rsi2_prev']:.0f}→{ind['rsi2_now']:.0f}↑, green bar, "
                            f"below mean {_fmt_price(mean)}")
        return ("wait", "")

    if kind == "mr_reversal_short":
        # Overbought bounce rolls over (SHORT): RSI(2) turns back DOWN through the
        # level + red bar + still above the mean + below the stop. Stop is ABOVE.
        if stop and price >= stop:
            return ("invalidate", f"stop {_fmt_price(stop)} hit before the roll-over")
        lvl = cond.get("rsi2_level", 88.0)
        mean = cond.get("mean")
        turned    = ind["rsi2_prev"] > lvl >= ind["rsi2_now"]      # RSI(2) turning down
        red       = price < prev                                    # price confirming down
        above_mean = mean is None or price > mean                   # still stretched up
        below_stop = stop is None or price < stop
        if turned and red and above_mean and below_stop:
            return ("fire", f"RSI2 {ind['rsi2_prev']:.0f}→{ind['rsi2_now']:.0f}↓, red bar, "
                            f"above mean {_fmt_price(mean)}")
        return ("wait", "")

    if kind == "breakout":
        if stop and price <= stop:
            return ("invalidate", f"stop {_fmt_price(stop)} hit before breakout")
        lvl, rmax = cond.get("level"), cond.get("rsi_max", 80)
        if lvl is not None and price >= lvl and ind["rsi14_now"] < rmax:
            return ("fire", f"broke {_fmt_price(lvl)}, RSI14 {ind['rsi14_now']:.0f} (&lt;{rmax})")
        return ("wait", "")

    if kind == "enter_now_short":
        # skills/new_setups.py: the research entered on the signal close with no
        # extra confirmation, so fire on the first poll unless price has already
        # run more than `max_drift` past the entry or reached the stop/target.
        if stop and price >= stop:
            return ("invalidate", f"stop {_fmt_price(stop)} hit before entry")
        entry, tgt = cond.get("entry"), cond.get("target")
        if tgt is not None and price <= tgt:
            return ("invalidate", f"already at the target {_fmt_price(tgt)}")
        if entry and price < entry * (1 - cond.get("max_drift", 0.03)):
            return ("invalidate", f"moved more than {cond.get('max_drift', 0.03) * 100:.0f}% "
                                  f"below the signal price before you could enter")
        return ("fire", "research setup on the daily close; enter now")

    if kind == "breakdown":
        if stop and price >= stop:
            return ("invalidate", f"stop {_fmt_price(stop)} hit")
        lvl, rmin = cond.get("level"), cond.get("rsi_min", 20)
        if lvl is not None and price <= lvl and ind["rsi14_now"] > rmin:
            return ("fire", f"broke {_fmt_price(lvl)} down, RSI14 {ind['rsi14_now']:.0f} (&gt;{rmin})")
        return ("wait", "")

    # ── Legacy single-factor fallback (older triggers) ────────────────────────
    ct, cv = trg["condition_type"], trg["condition_value"]
    if ct == "price_below" and price <= cv:
        return ("fire", f"price {_fmt_price(price)} ≤ {_fmt_price(cv)}")
    if ct == "price_above" and price >= cv:
        return ("fire", f"price {_fmt_price(price)} ≥ {_fmt_price(cv)}")
    if ct == "rsi_cross_up" and ind["rsi14_now"] >= cv:
        return ("fire", f"RSI reclaimed {cv:.0f}")
    return ("wait", "")


def _regime_vetoes(trg: dict) -> bool:
    """
    Whether the BTC regime veto hooks (config, both default off) block this fire.
    Longs vetoed while RISK-OFF (BTC_REGIME_VETO); shorts vetoed while RISK-ON
    (SHORT_VETO_IN_RISK_ON). v1 has both off → always returns False.
    """
    import config
    d0 = trg.get("direction") or "long"
    if d0 == "long" and getattr(config, "BTC_200D_LONG_GATE", False):
        try:
            from utils.breadth import long_gate
            ok_, why = long_gate()
            if not ok_:
                log.info("long gate closed: %s", why)
                return True                       # BTC 200d&50d + alt breadth gate
        except Exception:                         # noqa: BLE001 — fail open, log
            log.warning("long gate: unavailable")
    long_veto = getattr(config, "BTC_REGIME_VETO", False)
    short_veto = getattr(config, "SHORT_VETO_IN_RISK_ON", False)
    if not (long_veto or short_veto):
        return False
    try:
        from utils import btc_regime
        label = btc_regime.get_btc_regime()["label"]
    except Exception:                             # noqa: BLE001
        return False
    d = trg.get("direction") or "long"
    if d == "long" and long_veto and label == btc_regime.RISK_OFF:
        return True
    if d == "short" and short_veto and label == btc_regime.RISK_ON:
        return True
    return False


def poll_once() -> dict:
    """One evaluation pass over all active triggers. Returns a summary."""
    now_iso = datetime.datetime.utcnow().isoformat()
    tdb.expire_stale(now_iso)

    # Follow already-fired signals to their exit (live track record). Isolated so
    # a tracking hiccup never blocks new alerts.
    try:
        from triggers import outcomes
        track = outcomes.update_open_trades()
    except Exception as exc:                       # noqa: BLE001
        log.warning("outcome tracking failed — %s", exc)
        track = {}

    active = tdb.get_triggers("active")
    if not active:
        return {"active": 0, "fired": 0, "invalidated": 0, **track}

    symbols = sorted({t["symbol"] for t in active})
    # The trading venue first (Bybit perps — prices match what you trade), then
    # the usual venue chain for anything it did not return.
    from config import CANDLE_VENUE
    candles = exchange.get_ohlcv_batch(symbols, timeframe="1d", limit=_CANDLE_LIMIT,
                                       exchange=CANDLE_VENUE)
    missing = [s_ for s_ in symbols if s_ not in candles]
    if missing:
        candles.update(exchange.get_ohlcv_batch(missing, timeframe="1d", limit=_CANDLE_LIMIT))

    fired = invalidated = 0
    for t in active:
        df = candles.get(t["symbol"])
        if df is None:
            continue
        ind = _indicators(df)
        if ind is None:
            continue
        verdict, reason = _evaluate(t, ind)
        if verdict == "fire" and _regime_vetoes(t):
            # Veto hooks (both default off): skip firing in the adverse regime.
            log.info("VETOED #%d %s — BTC regime veto (%s)", t["id"], t["symbol"],
                     t.get("direction"))
            continue
        if verdict == "fire":
            text = _alert_text(t, ind["price"], reason)
            delivered = telegram.send_message(text)
            # Mark fired if delivered (or Telegram is a no-op); leave active to
            # retry on a transient send failure so a real alert isn't lost.
            if delivered or not telegram.is_configured():
                tdb.mark_fired(t["id"], ind["price"], note=reason)
                fired += 1
                log.info("FIRED #%d %s — %s", t["id"], t["symbol"], reason)
            else:
                log.warning("trigger #%d met but Telegram send failed; will retry", t["id"])
        elif verdict == "invalidate":
            tdb.set_status(t["id"], "invalidated")
            invalidated += 1
            log.info("INVALIDATED #%d %s — %s", t["id"], t["symbol"], reason)

    return {"active": len(active), "fired": fired, "invalidated": invalidated, **track}


def main() -> None:
    ap = argparse.ArgumentParser(description="QuantCore trigger monitor")
    ap.add_argument("--interval", type=int, default=180, help="poll seconds (min 60)")
    ap.add_argument("--once", action="store_true", help="single pass then exit")
    ap.add_argument("--heartbeat-telegram-hours", type=float, default=0.0,
                    help="send a 'still alive' Telegram every N hours (0 = off)")
    ap.add_argument("--max-minutes", type=float, default=0.0,
                    help="exit cleanly after N minutes (0 = run forever); lets a "
                         "CI job poll on a loop and hand over to the next run")
    ap.add_argument("--quiet-start", action="store_true",
                    help="don't send the 'Monitor started' Telegram (relay runs)")
    args = ap.parse_args()
    interval = max(args.interval, _MIN_INTERVAL)

    tdb.init_db()
    if not telegram.is_configured():
        log.warning("Telegram not configured — alerts will be logged only. "
                    "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.")

    if args.once:
        log.info("monitor: single pass — %s", poll_once())
        return

    n_active = len(tdb.get_triggers("active"))
    log.info("monitor: starting, poll every %ds, %d active triggers. Ctrl-C to stop.",
             interval, n_active)
    if not args.quiet_start:
        telegram.send_message(f"🟢 <b>Monitor started</b> — watching {n_active} armed "
                              f"trigger(s), polling every {interval}s.")
    deadline = time.time() + args.max_minutes * 60 if args.max_minutes else None
    hb_secs = args.heartbeat_telegram_hours * 3600
    last_hb = time.time()
    try:
        while True:
            # Scheduled Scan & Arm (6:50am / daily close / 3pm) — before the poll
            # so newly armed triggers are evaluated straight away.
            try:
                from triggers import autoscan
                autoscan.run_due()
            except Exception as exc:                # noqa: BLE001 — never kill the loop
                log.error("autoscan error: %s", exc)
            try:
                s = poll_once()
                # Heartbeat: ONE line every poll, so a quiet loop is distinguishable
                # from a dead one (this is what "nothing is watching" rules out).
                log.info("poll %s UTC · %d active · %d fired · %d invalidated",
                         datetime.datetime.utcnow().strftime("%H:%M:%S"),
                         s["active"], s["fired"], s["invalidated"])
                if hb_secs and time.time() - last_hb >= hb_secs:
                    telegram.send_message(f"💓 <b>Monitor alive</b> — {s['active']} "
                                          f"active trigger(s), still watching.")
                    last_hb = time.time()
            except Exception as exc:                # noqa: BLE001 — keep the loop alive
                log.error("poll error: %s", exc)
            # Wake early for a scheduled scan so it runs on time, not up to 15 min late.
            nap = interval
            try:
                from triggers import autoscan
                nap = min(interval, autoscan.seconds_to_next() + 5)
            except Exception:                       # noqa: BLE001
                pass
            if deadline and time.time() + nap > deadline:
                log.info("monitor: max runtime reached — exiting for hand-over.")
                return
            time.sleep(max(nap, _MIN_INTERVAL))
    except KeyboardInterrupt:
        log.info("monitor: stopped.")


if __name__ == "__main__":
    main()
