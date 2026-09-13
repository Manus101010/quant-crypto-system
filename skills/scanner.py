"""
Stock & Crypto Scanner
Screens a watchlist for candidates meeting configurable technical criteria.
Returns results with plain-English setup labels for frontend display.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import yfinance as yf
from utils.logger import get_logger

log = get_logger(__name__)

# ── Default watchlists ────────────────────────────────────────────────────────

DEFAULT_STOCK_WATCHLIST = [
    # Mega-cap tech
    "AAPL", "MSFT", "GOOGL", "GOOG", "NVDA", "META", "AMZN", "TSLA", "NFLX",
    # Financials
    "JPM", "BAC", "GS", "WFC", "MS", "BRK-B", "V", "MA", "AXP", "SCHW",
    # Healthcare
    "UNH", "JNJ", "LLY", "ABBV", "PFE", "MRK", "TMO", "ABT", "ISRG", "GILD",
    # Consumer Discretionary
    "HD", "WMT", "COST", "TGT", "NKE", "MCD", "SBUX", "LOW", "TJX", "BKNG",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX",
    # Semis & Hardware
    "AMD", "QCOM", "INTC", "AVGO", "TXN", "MU", "AMAT", "LRCX", "KLAC",
    # Software & Cloud
    "ADBE", "CRM", "NOW", "ORCL", "SNOW", "PLTR", "PANW", "CRWD", "ZS",
    # Industrials
    "HON", "CAT", "DE", "LMT", "RTX", "UPS", "FDX", "GE", "MMM",
    # Telecom / Media
    "CMCSA", "DIS", "T", "VZ", "PARA",
    # REITs & Utilities
    "AMT", "PLD", "NEE", "DUK",
    # Broad ETFs
    "SPY", "QQQ", "IWM", "GLD", "TLT", "XLF", "XLK", "XLE", "XLV",
]

DEFAULT_CRYPTO_WATCHLIST = [
    "BTC-USD",  "ETH-USD",  "BNB-USD",  "SOL-USD",  "XRP-USD",
    "ADA-USD",  "AVAX-USD", "DOT-USD",  "MATIC-USD","LINK-USD",
    "UNI-USD",  "ATOM-USD", "LTC-USD",  "BCH-USD",  "DOGE-USD",
    "SHIB-USD", "FTM-USD",  "NEAR-USD", "ALGO-USD", "XLM-USD",
    "VET-USD",  "MANA-USD", "SAND-USD", "CRO-USD",  "HBAR-USD",
    "ICP-USD",  "XTZ-USD",  "APE-USD",  "AXS-USD",  "EGLD-USD",
]

# Backward-compat alias
DEFAULT_WATCHLIST = DEFAULT_STOCK_WATCHLIST


# ── Criteria ──────────────────────────────────────────────────────────────────

class ScanCriteria:
    def __init__(
        self,
        min_price: float = 0.0,
        min_volume_usd_m: float = 0.5,    # $500k avg daily volume
        above_sma200: bool = True,
        above_sma50: bool = False,
        min_rsi: float = 0.0,
        max_rsi: float = 100.0,
        min_momentum_3m: float | None = None,
    ):
        self.min_price        = min_price
        self.min_volume_usd_m = min_volume_usd_m
        self.above_sma200     = above_sma200
        self.above_sma50      = above_sma50
        self.min_rsi          = min_rsi
        self.max_rsi          = max_rsi
        self.min_momentum_3m  = min_momentum_3m


# ── Mean-reversion metrics ────────────────────────────────────────────────────

def _bollinger(s: pd.Series, period: int = 20, width: float = 2.0):
    """Return (upper, middle, lower, %B, bandwidth%) for latest bar."""
    if len(s) < period:
        return None, None, None, None, None
    mid   = float(s.iloc[-period:].mean())
    std   = float(s.iloc[-period:].std(ddof=0))
    upper = mid + width * std
    lower = mid - width * std
    rng   = upper - lower
    bb_pct = (float(s.iloc[-1]) - lower) / rng if rng else 0.5
    bw_pct = rng / mid * 100 if mid else 0          # bandwidth as % of price
    return upper, mid, lower, bb_pct, bw_pct


def _zscore(s: pd.Series, period: int = 20) -> float | None:
    """Z-score of the latest price vs. its rolling mean/std."""
    if len(s) < period:
        return None
    window = s.iloc[-period:]
    mu, sigma = float(window.mean()), float(window.std(ddof=0))
    if sigma == 0:
        return 0.0
    return float((float(s.iloc[-1]) - mu) / sigma)


def _williams_r(s: pd.Series, period: int = 14) -> float | None:
    """Williams %R — ranges from -100 (oversold) to 0 (overbought)."""
    if len(s) < period:
        return None
    window = s.iloc[-period:]
    high_h = float(window.max())
    low_l  = float(window.min())
    if high_h == low_l:
        return -50.0
    return float((high_h - float(s.iloc[-1])) / (high_h - low_l) * -100)


def _rsi2(series: pd.Series) -> float | None:
    """
    Larry Connors' 2-period RSI — the proven mean-reversion trigger.
    RSI(2) < 10 above the 200-day MA has a ~75% historical bounce rate.
    Far more predictive of a snap-back than RSI(14) < 30.
    """
    if len(series) < 5:
        return None
    return _rsi(series, 2)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float | None:
    """
    Average True Range — the asset's typical daily move, used for
    volatility-adaptive stops. A 2×ATR stop adjusts automatically:
    wide for volatile names, tight for calm ones (cuts drawdowns ~32%).
    """
    if len(close) < period + 1:
        return None
    high  = pd.to_numeric(high, errors="coerce")
    low   = pd.to_numeric(low, errors="coerce")
    close = pd.to_numeric(close, errors="coerce")
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, min_periods=period).mean().iloc[-1]
    return float(atr) if pd.notna(atr) else None


def _momentum_12_1(s: pd.Series) -> float | None:
    """
    Academic 12-1 momentum (Jegadeesh & Titman): return from ~13 months
    ago to ~1 month ago, skipping the most recent month to avoid the
    short-term reversal effect. Needs ≥ 273 daily bars.
    Falls back to 6-1 momentum if only ~6 months are available.
    """
    n = len(s)
    skip = 21               # skip most recent ~1 month
    if n >= 273:            # ~13 months
        start = s.iloc[-273]
        end   = s.iloc[-skip]
        return float((end - start) / start * 100) if start else None
    if n >= 147:            # ~7 months → 6-1 fallback
        start = s.iloc[-147]
        end   = s.iloc[-skip]
        return float((end - start) / start * 100) if start else None
    return None


# ── Trade suggestion generator ────────────────────────────────────────────────

def _fmt_p(p: float) -> str:
    """Format a price cleanly regardless of magnitude."""
    if p < 0.01:   return f"${p:.6f}"
    if p < 1:      return f"${p:.4f}"
    if p < 100:    return f"${p:.2f}"
    return f"${p:,.2f}"


def trade_suggestion(
    setup_label: str,
    price: float,
    sma50: float,
    sma200: float,
    bb_upper: float | None,
    bb_mid: float | None,
    bb_lower: float | None,
    rsi: float,
    mom3m: float,
    atr: float | None = None,
) -> dict:
    """
    Returns a dict with keys: action, entry, target, stop, rr, note.

    Stops are VOLATILITY-ADAPTIVE: stop distance = `mult` × ATR(14) rather than
    a fixed %. This adapts to each asset (wide for volatile names, tight for calm
    ones), cutting premature stop-outs. Targets are chosen from structure (BB
    midline, SMA50) but the R:R is always computed from the real ATR stop so
    you can size positions correctly.
    """
    def _rr(entry: float, tgt: float, stop: float) -> str | None:
        risk   = abs(entry - stop)
        reward = abs(tgt - entry)
        if risk == 0:
            return None
        return f"{reward / risk:.1f}:1"

    # Volatility-based stop distance. Fall back to a sensible % if ATR missing.
    def _stop_below(mult: float, floor_pct: float = 0.03) -> float:
        if atr and atr > 0:
            return price - mult * atr
        return price * (1 - floor_pct)

    atr_note = f"≈{_fmt_p(atr)} ATR" if atr else "fixed %"

    # ── PREMIER: Connors RSI-2 pullback ───────────────────────────────────────
    if setup_label == "RSI-2 Pullback (Connors)":
        target = bb_mid if bb_mid else (sma50 if sma50 > price else price * 1.05)
        stop   = _stop_below(2.0)
        return {
            "action": "BUY",
            "entry":  f"Buy near {_fmt_p(price)} on the close — short-term washout in an uptrend",
            "target": f"{_fmt_p(target)} (5–10 day mean / BB midline). Exit when RSI(2) > 65",
            "stop":   f"{_fmt_p(stop)} (2× ATR, {atr_note})",
            "rr":     _rr(price, target, stop),
            "note":   "Connors' highest-probability setup (~75% bounce rate). Short hold — take the snap-back, don't marry it.",
        }

    # ── Oversold dip in uptrend ───────────────────────────────────────────────
    if setup_label == "Oversold in Uptrend":
        target = sma50 if sma50 > price else price * 1.06
        stop   = max(_stop_below(2.0), sma200 * 0.98)
        return {
            "action": "BUY",
            "entry":  f"Buy the dip near {_fmt_p(price)} — the 200-day uptrend is your tailwind",
            "target": f"{_fmt_p(target)} (SMA50 recovery)",
            "stop":   f"{_fmt_p(stop)} (2× ATR or just below 200-SMA, {atr_note})",
            "rr":     _rr(price, target, stop),
            "note":   "High-probability: oversold dip inside a confirmed uptrend. Trend break = exit.",
        }

    if setup_label == "BB Bounce Setup":
        target = bb_mid if bb_mid else price * 1.05
        stop   = _stop_below(2.0)
        return {
            "action": "BUY",
            "entry":  f"Buy near {_fmt_p(price)} — near the lower band, trend intact",
            "target": f"{_fmt_p(target)} (BB midline / 20-day mean)",
            "stop":   f"{_fmt_p(stop)} (2× ATR, {atr_note})",
            "rr":     _rr(price, target, stop),
            "note":   "Uptrend provides a tailwind for the bounce back to the mean.",
        }

    if setup_label == "Williams %R Oversold":
        target = sma50 if sma50 > price else price * 1.05
        stop   = _stop_below(2.0)
        return {
            "action": "BUY",
            "entry":  f"Buy near {_fmt_p(price)} — %R signals short-term exhaustion in an uptrend",
            "target": f"{_fmt_p(target)} (SMA50 swing recovery)",
            "stop":   f"{_fmt_p(stop)} (2× ATR, {atr_note})",
            "rr":     _rr(price, target, stop),
            "note":   "Swing trade: 3–10 day hold. Exit when %R crosses back above −20.",
        }

    if setup_label == "Overextended — Reversion Risk":
        target = bb_mid if bb_mid else price * 0.93
        stop   = (price + 2 * atr) if atr else (bb_upper * 1.03 if bb_upper else price * 1.05)
        return {
            "action": "SELL/EXIT",
            "entry":  "No new longs — reduce or exit existing positions here",
            "target": f"{_fmt_p(target)} (BB midline — likely pullback destination)",
            "stop":   f"{_fmt_p(stop)} (trail 2× ATR above price if still holding)",
            "rr":     None,
            "note":   "Take-profit zone, not a short entry. Tighten stops; wait for a reset before re-entering.",
        }

    if setup_label == "Far Above 200-SMA":
        target = sma50
        stop   = (price + 2 * atr) if atr else price * 1.05
        return {
            "action": "SELL/EXIT",
            "entry":  "Trim or exit longs — risk/reward has shifted unfavourably",
            "target": f"{_fmt_p(target)} (SMA50 — typical mean-reversion destination)",
            "stop":   f"{_fmt_p(stop)} (trail 2× ATR above price if still holding)",
            "rr":     None,
            "note":   "Not a short signal — a reminder that extended runs revert. Protect profits.",
        }

    # ── Breakout entries (volume / Donchian / squeeze) ─────────────────────────
    if setup_label in ("Donchian Breakout (55d)", "Volume Breakout", "Squeeze Breakout"):
        stop   = _stop_below(2.5)
        risk   = price - stop
        target = price + risk * 3.0        # breakouts trade with a wide target / trail
        entries = {
            "Donchian Breakout (55d)": "Buy the close of the 55-day breakout — don't wait for a pullback",
            "Volume Breakout":         "Buy the volume-confirmed breakout on the close",
            "Squeeze Breakout":        "Buy the expansion out of the squeeze on the close",
        }
        return {
            "action": "BUY",
            "entry":  f"{entries[setup_label]} near {_fmt_p(price)}",
            "target": f"{_fmt_p(target)} (3R) — or trail a 2.5× ATR stop and let it run",
            "stop":   f"{_fmt_p(stop)} (2.5× ATR, {atr_note})",
            "rr":     _rr(price, target, stop),
            "note":   "Breakout: low win rate by design, but winners run. Cut it fast if it fails back into the range.",
        }

    # ── Momentum entries ──────────────────────────────────────────────────────
    if setup_label == "Momentum Runner":
        stop      = max(_stop_below(2.5), sma50 * 0.985)
        risk      = price - stop
        extension = price + max(risk * 2.5, (price - sma200) * 0.25)   # ≥2.5R target
        return {
            "action": "BUY",
            "entry":  f"Buy now at {_fmt_p(price)} or add on any dip to SMA50 ({_fmt_p(sma50)})",
            "target": f"{_fmt_p(extension)} (≥2.5R extension)",
            "stop":   f"{_fmt_p(stop)} (2.5× ATR or below SMA50, {atr_note})",
            "rr":     _rr(price, extension, stop),
            "note":   "Trend-following. Add on pullbacks to SMA50; trim if RSI > 80.",
        }

    if setup_label == "Confirmed Uptrend":
        stop   = max(_stop_below(2.5), sma50 * 0.985)
        risk   = price - stop
        target = price + risk * 2.0
        return {
            "action": "BUY",
            "entry":  f"Buy at {_fmt_p(price)} — structure is clean, no need to wait",
            "target": f"{_fmt_p(target)} (2R swing target)",
            "stop":   f"{_fmt_p(stop)} (2.5× ATR or below SMA50, {atr_note})",
            "rr":     _rr(price, target, stop),
            "note":   "Textbook trend trade. Hold as long as price stays above SMA50.",
        }

    if setup_label == "Overbought Runner":
        stop   = sma50 * 0.985
        target = price * 1.10
        return {
            "action": "WAIT",
            "entry":  f"Wait for a pullback to SMA50 ({_fmt_p(sma50)}) — don't chase here",
            "target": f"{_fmt_p(target)} (momentum target on the pullback entry)",
            "stop":   f"{_fmt_p(stop)} (below SMA50 on the pullback entry)",
            "rr":     _rr(sma50, target, stop),
            "note":   "Momentum is real but RSI is stretched. Buy the first dip to SMA50, not now.",
        }

    if setup_label == "Pullback to SMA50":
        stop   = max(_stop_below(2.5), sma200 * 0.98)
        risk   = price - stop
        target = price + risk * 2.0
        return {
            "action": "BUY",
            "entry":  f"Buy the dip at {_fmt_p(price)} — SMA50 ({_fmt_p(sma50)}) is the support",
            "target": f"{_fmt_p(target)} (2R swing target)",
            "stop":   f"{_fmt_p(stop)} (2.5× ATR or below 200-SMA, {atr_note})",
            "rr":     _rr(price, target, stop),
            "note":   "Classic buy-the-dip. If the 200-SMA breaks, the uptrend is over — exit.",
        }

    if setup_label == "Counter-Trend Bounce":
        target = bb_mid if bb_mid else price * 1.05
        stop   = _stop_below(1.5)   # tight — this is a scalp against the trend
        return {
            "action": "BUY",
            "entry":  f"Scalp near {_fmt_p(price)} — extreme oversold, but trade small",
            "target": f"{_fmt_p(target)} (snap-back to 20-day mean; take profit fast)",
            "stop":   f"{_fmt_p(stop)} (tight 1.5× ATR — bail if the downtrend resumes, {atr_note})",
            "rr":     _rr(price, target, stop),
            "note":   "Counter-trend scalp below the 200-SMA. Quick in/out only — the higher-timeframe trend is against you.",
        }

    if setup_label == "Falling Knife — Avoid":
        return {
            "action": "WAIT",
            "entry":  "Do NOT buy — oversold inside a downtrend (below 200-SMA)",
            "target": "–",
            "stop":   "–",
            "rr":     None,
            "note":   "Oversold readings keep getting more oversold in downtrends. Wait for a 200-SMA reclaim.",
        }

    # ── Catch-all / neutral ───────────────────────────────────────────────────
    return {
        "action": "WAIT",
        "entry":  "No actionable entry — wait for a cleaner setup to develop",
        "target": "–",
        "stop":   "–",
        "rr":     None,
        "note":   "Below key levels. Watch for a reclaim of SMA200 before considering a position.",
    }


def breakout_signals(close, high, volume) -> dict:
    """
    Volume/breakout/squeeze features from series up to 'now' (last element = today).
    Used to classify the trend-following setups (Donchian, volume spike, squeeze).
      - donch_hi20/55: prior N-day high (EXCLUDING today) → today's close breaking
        it is a fresh N-day breakout.
      - vol_ratio: today's volume / 20-day average volume (participation).
      - squeeze: today's Bollinger bandwidth in the bottom 20% of the last 60 days
        (a volatility contraction that precedes expansion).
    All values are None when there isn't enough history (setup simply won't fire).
    """
    import numpy as _np
    out = {"vol_ratio": None, "donch_hi20": None, "donch_hi55": None, "squeeze": None}
    n = len(close)
    if len(high) >= 21:
        out["donch_hi20"] = float(high.iloc[-21:-1].max())
    if len(high) >= 56:
        out["donch_hi55"] = float(high.iloc[-56:-1].max())
    if volume is not None and len(volume) >= 20:
        avg = float(volume.iloc[-20:].mean())
        if avg > 0:
            out["vol_ratio"] = float(volume.iloc[-1] / avg)
    if n >= 80:
        ma = close.rolling(20).mean()
        sd = close.rolling(20).std()
        bw = (4.0 * sd) / ma            # (upper-lower)/mid bandwidth, 2σ bands
        recent = bw.iloc[-60:].dropna()
        cur = bw.iloc[-1]
        if len(recent) > 20 and cur == cur:   # cur not NaN
            out["squeeze"] = bool(cur <= recent.quantile(0.20))
    return out


# ── Setup classifier (momentum + mean reversion) ──────────────────────────────

def classify_setup(
    price: float, sma50: float, sma200: float,
    rsi: float, mom3m: float,
    bb_pct: float | None = None,
    zscore: float | None = None,
    williams_r: float | None = None,
    rsi2: float | None = None,
    vol_ratio: float | None = None,
    donch_hi20: float | None = None,
    donch_hi55: float | None = None,
    squeeze: bool | None = None,
) -> tuple[str, str, str]:
    """
    Returns (label, plain-English description, category).
    category = 'mean_reversion' | 'momentum' | 'neutral'

    CORE RULE (Larry Connors / Jegadeesh-Titman): mean-reversion LONGS are
    only taken when price is ABOVE the 200-day moving average. Buying
    oversold below the 200-SMA is "catching a falling knife" and is the
    single biggest source of losing trades — those setups are now flagged
    as 'Falling Knife — Avoid' rather than presented as buys.
    """
    above_200    = price > sma200
    above_50     = price > sma50
    golden_cross = sma50 > sma200
    dist_sma200  = (price / sma200 - 1) * 100 if sma200 else 0

    # ══ FALLING KNIFE GUARD ═══════════════════════════════════════════════
    # Oversold BELOW the 200-day trend → explicitly NOT a buy. This replaces
    # the old "Deep Oversold" / "Z-Score Extreme (no trend required)" buys
    # that were generating the most losers.
    deeply_oversold = (
        (rsi2 is not None and rsi2 < 15) or
        (rsi < 30) or
        (bb_pct is not None and bb_pct <= 0.05) or
        (zscore is not None and zscore <= -2.0)
    )
    if deeply_oversold and not above_200:
        # EXTREME short-term washout (RSI-2 < 5) below the 200-SMA → a tradeable
        # counter-trend bounce for a quick scalp, but honestly risk-weighted: it
        # gets a low base conviction so it ranks below proper above-trend setups.
        extreme_washout = (
            (rsi2 is not None and rsi2 < 5) or
            (zscore is not None and zscore <= -2.7)
        )
        if extreme_washout:
            return (
                "Counter-Trend Bounce",
                f"Extreme short-term washout (RSI {rsi:.0f}"
                + (f", RSI(2) {rsi2:.0f}" if rsi2 is not None else "")
                + ") but price is BELOW its 200-day average — this is a downtrend. "
                "Only a quick counter-trend scalp with a tight stop, not a position trade. "
                "Lower conviction by design: the higher-timeframe trend is against you.",
                "mean_reversion",
            )
        return (
            "Falling Knife — Avoid",
            f"Price is oversold (RSI {rsi:.0f}) but BELOW its 200-day average — a "
            "downtrend, not a dip. Oversold readings in downtrends keep getting more "
            "oversold. No long here until price reclaims the 200-SMA. "
            "(This guard exists because buying knives is the #1 cause of blown trades.)",
            "neutral",
        )

    # ── PREMIER mean-reversion: Connors RSI-2 pullback in an uptrend ──────
    # RSI(2) < 10 while above the 200-SMA → ~75% historical bounce rate.
    if rsi2 is not None and rsi2 < 10 and above_200:
        return (
            "RSI-2 Pullback (Connors)",
            f"RSI(2) at {rsi2:.0f} — an extreme short-term washout — while price holds "
            "above its 200-day uptrend. This is Larry Connors' highest-probability "
            "mean-reversion trigger (~75% historical bounce rate). Exit when RSI(2) "
            "crosses back above 65 or price tags the 5/10-day average.",
            "mean_reversion",
        )

    # ── Oversold dip within a confirmed uptrend (RSI-14 variant) ─────────
    if rsi < 35 and above_200:
        return (
            "Oversold in Uptrend",
            f"RSI {rsi:.0f} oversold while above the 200-day trend. Classic "
            "buy-the-dip: the long-term uptrend provides a tailwind for the bounce. "
            "One of the highest-probability swing setups.",
            "mean_reversion",
        )

    # ── BB Bounce: near lower band, uptrend intact ───────────────────────
    if (bb_pct is not None and bb_pct <= 0.15) and above_200 and rsi < 50:
        return (
            "BB Bounce Setup",
            f"Price is near the lower Bollinger Band (BB%={bb_pct:.2f}) while the "
            "200-day uptrend is intact. Mean reversion entry: price tends to drift "
            f"back toward the 20-day average. RSI {rsi:.0f} confirms not overbought.",
            "mean_reversion",
        )

    # ── Williams %R deep oversold, uptrend intact ────────────────────────
    if williams_r is not None and williams_r <= -85 and above_200:
        return (
            "Williams %R Oversold",
            f"Williams %%R at {williams_r:.0f} — deeply oversold on a 14-day lookback — "
            "with price above the 200-day trend line. A swing-trader mean-reversion "
            "setup confirmed by the longer-term uptrend.",
            "mean_reversion",
        )

    # ── Overextended: at upper BB + high RSI → take-profit / reversion ───
    if (bb_pct is not None and bb_pct >= 0.92) and rsi > 72:
        return (
            "Overextended — Reversion Risk",
            f"Price is at the upper Bollinger Band (BB%={bb_pct:.2f}) with RSI {rsi:.0f}. "
            "Statistically tends to pull back toward the mean. Not a buy — flags open "
            "positions as approaching a take-profit / trailing-stop zone.",
            "mean_reversion",
        )

    # ══ BREAKOUT / VOLUME setups (proven trend-following) ═════════════════
    # Checked before the generic momentum labels so a coin printing a fresh
    # breakout is tagged as such instead of collapsing into "Momentum Runner".
    breakout20 = donch_hi20 is not None and price >= donch_hi20
    breakout55 = donch_hi55 is not None and price >= donch_hi55
    high_vol   = vol_ratio is not None and vol_ratio >= 2.0
    good_vol   = vol_ratio is not None and vol_ratio >= 1.5

    # Turtle-style 55-day breakout in an uptrend — the classic crypto trend entry.
    if breakout55 and above_200 and rsi < 82:
        return (
            "Donchian Breakout (55d)",
            f"Price closed at a fresh 55-day high ({_fmt_p(price)}) while above the "
            f"200-day trend — the Turtle breakout. Crypto trends routinely extend "
            f"30–50% past a 55-day breakout. Enter on the close, trail the stop, let it run.",
            "momentum",
        )
    # Volatility squeeze → expansion: coiled range breaks out on real volume.
    if squeeze and breakout20 and good_vol and above_200:
        return (
            "Squeeze Breakout",
            f"Volatility had contracted to a multi-week low (a squeeze) and price just "
            f"broke to a 20-day high on {vol_ratio:.1f}× average volume. Compression → "
            f"expansion: these coiled breakouts tend to run once they release.",
            "momentum",
        )
    # Volume-confirmed 20-day breakout: participation behind the move.
    if breakout20 and high_vol and above_200:
        return (
            "Volume Breakout",
            f"Fresh 20-day high on {vol_ratio:.1f}× average volume — real participation "
            f"behind the move (not a low-liquidity drift). Breakouts confirmed by a "
            f"volume spike historically show materially better follow-through.",
            "momentum",
        )

    # ── Momentum setups ───────────────────────────────────────────────────
    if above_50 and above_200 and golden_cross and mom3m > 10 and rsi < 78:
        return (
            "Momentum Runner",
            f"Price above both 50 & 200-day averages, golden cross confirmed, "
            f"strong 3M momentum +{mom3m:.1f}%, RSI not yet stretched. High-conviction uptrend.",
            "momentum",
        )
    if rsi > 78 and mom3m > 20:
        return (
            "Overbought Runner",
            f"RSI very elevated at {rsi:.0f} with powerful momentum (+{mom3m:.1f}%). "
            "Trend is strong but stretched — wait for a pullback to SMA50 rather than "
            "chasing here.",
            "momentum",
        )
    if above_50 and above_200 and golden_cross:
        return (
            "Confirmed Uptrend",
            "Price above both SMAs with golden cross. Textbook bullish structure.",
            "momentum",
        )
    if above_200 and not above_50:
        return (
            "Pullback to SMA50",
            "Long-term uptrend intact but price pulled back below the 50-day average. "
            "Buy-the-dip zone as long as the 200-day holds.",
            "momentum",
        )
    if above_200:
        return (
            "Building Base",
            "Above 200-day average, consolidating. Watching for the next breakout.",
            "neutral",
        )
    return (
        "Watch — Below Key Levels",
        "Below both key moving averages. No edge — monitor for a 200-SMA reclaim.",
        "neutral",
    )


# ── Conviction scorer ─────────────────────────────────────────────────────────

# Base scores per setup — now anchored to EMPIRICAL win rates, not intuition.
# Highest scores go to setups with proven edge: oversold dips ABOVE the 200-SMA
# (Connors ~75% win rate) and confirmed momentum. Falling-knife setups removed.
# Calibrated from a walk-forward backtest (90 tickers, 3,463 simulated trades,
# 2y, backtesting/setup_validation.py) blended 60/40 with the literature prior to
# avoid over-fitting one sample. Trusted setups (n≥30) only; thin samples kept at prior.
# Empirical highlights: Momentum Runner was overrated (52% win), Confirmed Uptrend
# underrated (56% win, PF 1.72), Williams %R vindicated on the full universe (76% win).
_SETUP_BASE: dict[str, float] = {
    "RSI-2 Pullback (Connors)":    85,   # empirical 69% win, PF 2.07 (n=339) — premier setup, confirmed
    "Oversold in Uptrend":         80,   # thin (n=20, untrusted) — kept at literature prior
    "Donchian Breakout (55d)":     72,   # Turtle 55d breakout — trend-following, provisional until crypto-validated
    "Volume Breakout":             70,   # 20d high + 2x volume — provisional until crypto-validated
    "Squeeze Breakout":            70,   # volatility contraction → expansion — provisional until crypto-validated
    "Momentum Runner":             71,   # was 78; empirical 52% win, PF 1.56 (n=1224) — overrated
    "BB Bounce Setup":             71,   # was 74; empirical 64% win, PF 1.59 (n=132)
    "Williams %R Oversold":        73,   # was 70; empirical 76% win, PF 1.65 (n=180) — vindicated
    "Pullback to SMA50":           67,   # empirical 65% win, PF 1.52 (n=472) — confirmed
    "Confirmed Uptrend":           68,   # was 62; empirical 56% win, PF 1.72 (n=758) — underrated
    "Overbought Runner":           45,   # stretched — wait for pullback, low entry edge
    "Counter-Trend Bounce":        50,   # was 40; empirical 65% win/PF 1.71 BUT below-200-SMA → raised only modestly (regime risk)
    "Building Base":               34,   # consolidating only
    "Overextended — Reversion Risk": 18, # exit/take-profit flag, not an entry
    "Far Above 200-SMA":           18,   # take-profit flag
    "Falling Knife — Avoid":        8,   # oversold below 200-SMA — explicitly avoid
    "Watch — Below Key Levels":     8,   # below both SMAs, no edge
}


def conviction_score(
    setup_label: str,
    rsi: float,
    mom3m: float,
    bb_pct: float | None,
    zscore: float | None,
    williams_r: float | None,
    vol_usd_m: float,
    setup_cat: str,
    rsi2: float | None = None,
    regime_score: float | None = None,
) -> float:
    """
    Returns a 0–100 conviction score for a scanner result.

    Components:
      1. Setup base score   — anchored to empirical win rates
      2. Signal extremity   — how far into the edge the signal is
      3. Volume bonus       — liquidity / institutional interest (log-scaled)
      4. Regime adjustment  — aligns the score with the macro Deployment Score
                              so longs are penalised in risk-off regimes
    """
    base = _SETUP_BASE.get(setup_label, 25)

    # ── Signal extremity adjustment ──────────────────────────────────────────
    extremity = 0.0

    if setup_cat == "mean_reversion":
        # RSI(2) depth is the strongest mean-reversion edge: 10→0, 5→+4, 0→+8
        if rsi2 is not None and rsi2 < 10:
            extremity += min((10 - rsi2) * 0.8, 8)
        # RSI(14) depth: 35→0, 25→+4
        if rsi < 35:
            extremity += min((35 - rsi) / 2.5, 6)
        # BB%B depth: 0.15→0, 0.0→+5
        if bb_pct is not None and bb_pct < 0.15:
            extremity += (0.15 - bb_pct) / 0.15 * 5
        # Williams %R depth: -85→0, -95→+4
        if williams_r is not None and williams_r < -85:
            extremity += min((abs(williams_r) - 85) / 2.5, 4)

    elif setup_cat == "momentum":
        # Strong momentum adds up to +10
        if mom3m > 10:
            extremity += min((mom3m - 10) / 12, 10)
        # Healthy (not stretched) RSI for momentum: 45–68 zone bonus
        if 45 <= rsi <= 68:
            extremity += 4
        # Penalise overbought momentum chasing
        if rsi > 75:
            extremity -= 6

    # ── Volume bonus (0 … +8, log scale) ─────────────────────────────────────
    import math
    if vol_usd_m > 0.5:
        vol_bonus = min(math.log10(vol_usd_m / 0.5) / math.log10(1000) * 8, 8)
    else:
        vol_bonus = 0.0

    score = base + extremity + vol_bonus

    # ── Regime adjustment ────────────────────────────────────────────────────
    # When the macro Deployment Score is low (risk-off), discount long setups.
    # 50 = neutral (no change). 80 = +5% boost. 20 = −20% haircut.
    if regime_score is not None and setup_cat in ("momentum", "mean_reversion"):
        regime_mult = 0.8 + (regime_score / 100) * 0.4   # 0.8 … 1.2
        # Momentum suffers most in risk-off; mean reversion is more regime-neutral
        if setup_cat == "momentum":
            score *= regime_mult
        else:
            score *= (0.9 + (regime_mult - 0.9) * 0.6)   # softer effect

    return round(min(max(score, 0), 100), 1)


# ── Public entry points ───────────────────────────────────────────────────────

def run_scan(
    tickers: list[str] | None = None,
    criteria: ScanCriteria | None = None,
    regime_score: float | None = None,
) -> pd.DataFrame:
    """Stock scanner — defaults to broad large-cap universe."""
    return _run(
        tickers  or DEFAULT_STOCK_WATCHLIST,
        criteria or ScanCriteria(above_sma200=True),
        regime_score=regime_score,
    )


def run_crypto_scan(
    tickers: list[str] | None = None,
    criteria: ScanCriteria | None = None,
    regime_score: float | None = None,
    exchange: str | None = None,
) -> pd.DataFrame:
    """
    Crypto scanner — sources OHLCV from the ccxt data layer (utils/exchange.py),
    the canonical read-only price source for the crypto refocus. Multi-exchange
    fallback, no keys. (utils/bybit.py is retained only as a legacy fallback.)

    `exchange`: pin all candle fetches to one venue (e.g. "mexc") instead of the
    fallback chain — far faster for a large single-venue universe.
    """
    from utils.exchange import get_ohlcv_batch
    ticker_list = tickers or DEFAULT_CRYPTO_WATCHLIST
    crit = criteria or ScanCriteria(min_price=0.0, above_sma200=False, above_sma50=False)
    # ≥273 daily bars for the 12-1 momentum factor. get_ohlcv_batch returns
    # {ticker: DataFrame[open,high,low,close,volume]} — the shape _run_from_bybit
    # consumes (turnover optional → falls back to volume×close for USD volume).
    ohlc = get_ohlcv_batch(ticker_list, timeframe="1d", limit=400, exchange=exchange)
    return _run_from_bybit(ohlc, ticker_list, crit, regime_score=regime_score)


# ── Core scanner ──────────────────────────────────────────────────────────────

def _download_chunked(tickers: list[str], chunk: int = 60, retries: int = 2):
    """
    Download OHLCV in batches so large universes (e.g. the S&P 500) survive
    Yahoo throttling: one 500-ticker request often returns empty under rate
    limiting, whereas ~60-ticker batches with a brief pause + retry succeed.
    Returns (closes, volumes, highs, lows) DataFrames keyed by ticker.
    """
    import time as _t
    frames = {"Close": [], "Volume": [], "High": [], "Low": []}
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        for attempt in range(retries + 1):
            raw = yf.download(batch, period="2y", interval="1d",
                              progress=False, auto_adjust=True, group_by="column")
            if isinstance(raw.columns, pd.MultiIndex):
                got = raw["Close"].dropna(how="all", axis=1).shape[1]
            else:
                got = 0 if raw.empty else 1
            if got > 0 or attempt == retries:
                break
            log.warning("scanner: batch %d empty (attempt %d) — retrying", i // chunk + 1, attempt + 1)
            _t.sleep(2.0 * (attempt + 1))
        for field in frames:
            if isinstance(raw.columns, pd.MultiIndex):
                if field in raw.columns.get_level_values(0):
                    frames[field].append(raw[field])
            elif field in raw.columns:
                sub = raw[[field]].copy()
                sub.columns = batch[:1]
                frames[field].append(sub)
        if i + chunk < len(tickers):
            _t.sleep(0.5)
    out = {}
    for field, parts in frames.items():
        out[field] = pd.concat(parts, axis=1) if parts else pd.DataFrame()
    return out["Close"], out["Volume"], out["High"], out["Low"]


def _run(tickers: list[str], criteria: ScanCriteria,
         regime_score: float | None = None) -> pd.DataFrame:
    log.info("Scanning %d tickers …", len(tickers))

    # 2y of data so the 12-1 momentum factor (needs ~13 months) is available.
    # Small universes: single request. Large (>80): chunked + retry for resilience.
    if len(tickers) > 80:
        closes, volumes, highs, lows = _download_chunked(tickers)
    else:
        raw = yf.download(tickers, period="2y", interval="1d",
                          progress=False, auto_adjust=True)
        if isinstance(raw.columns, pd.MultiIndex):
            closes, volumes, highs, lows = raw["Close"], raw["Volume"], raw["High"], raw["Low"]
        else:
            closes  = raw[["Close"]]
            volumes = raw[["Volume"]]
            highs   = raw[["High"]]
            lows    = raw[["Low"]]

    results = []
    for ticker in tickers:
        try:
            if ticker not in closes.columns:
                continue
            s = closes[ticker].dropna()
            v = volumes[ticker].dropna() if ticker in volumes.columns else pd.Series()
            h = highs[ticker].dropna() if ticker in highs.columns else pd.Series()
            lo = lows[ticker].dropna() if ticker in lows.columns else pd.Series()

            if len(s) < 63:          # need ≥ 3 months of data
                continue

            price  = float(s.iloc[-1])
            sma50  = float(s.iloc[-50:].mean())
            sma200 = float(s.iloc[-200:].mean()) if len(s) >= 200 else sma50
            mom3m  = (price - float(s.iloc[-63])) / float(s.iloc[-63]) * 100
            mom121 = _momentum_12_1(s)
            rsi    = _rsi(s, 14)
            rsi_2  = _rsi2(s)

            # ── Mean reversion metrics ────────────────────────────────────
            bb_upper, bb_mid, bb_lower, bb_pct, bb_bw = _bollinger(s, 20, 2.0)
            zsc    = _zscore(s, 20)
            wil_r  = _williams_r(s, 14)
            atr    = _atr(h, lo, s, 14) if len(h) and len(lo) else None
            dist_sma50_pct  = (price / sma50  - 1) * 100 if sma50  else 0
            dist_sma200_pct = (price / sma200 - 1) * 100 if sma200 else 0

            # Volume in USD millions (works for both stocks and crypto)
            vol_usd_m = float(v.iloc[-20:].mean() * price / 1e6) if len(v) >= 20 else 0

            passes = True
            if criteria.min_price and price < criteria.min_price:
                passes = False
            if vol_usd_m < criteria.min_volume_usd_m:
                passes = False
            if criteria.above_sma200 and price < sma200:
                passes = False
            if criteria.above_sma50 and price < sma50:
                passes = False
            if rsi < criteria.min_rsi or rsi > criteria.max_rsi:
                passes = False
            if criteria.min_momentum_3m is not None and mom3m < criteria.min_momentum_3m:
                passes = False

            bo = breakout_signals(s, h, v)
            setup_label, setup_desc, setup_cat = classify_setup(
                price, sma50, sma200, rsi, mom3m, bb_pct, zsc, wil_r, rsi_2,
                vol_ratio=bo["vol_ratio"], donch_hi20=bo["donch_hi20"],
                donch_hi55=bo["donch_hi55"], squeeze=bo["squeeze"],
            )

            # Format price sensibly across stocks and micro-cap crypto
            if price < 0.01:
                price_fmt = f"{price:.6f}"
            elif price < 1:
                price_fmt = f"{price:.4f}"
            elif price < 100:
                price_fmt = f"{price:.2f}"
            else:
                price_fmt = f"{price:,.2f}"

            conv  = conviction_score(
                setup_label, rsi, mom3m, bb_pct, zsc, wil_r, vol_usd_m, setup_cat,
                rsi2=rsi_2, regime_score=regime_score,
            )
            trade = trade_suggestion(
                setup_label, price, sma50, sma200, bb_upper, bb_mid, bb_lower, rsi, mom3m, atr,
            )
            results.append({
                "ticker":           ticker,
                "price":            round(price, 6 if price < 0.01 else (4 if price < 1 else 2)),
                "price_fmt":        price_fmt,
                "sma50":            round(sma50, 2),
                "sma200":           round(sma200, 2),
                "above_sma50":      bool(price > sma50),
                "above_sma200":     bool(price > sma200),
                "mom_3m_pct":       round(mom3m, 1),
                "mom_12_1_pct":     round(mom121, 1) if mom121 is not None else None,
                "rsi_14":           round(rsi, 1),
                "rsi_2":            round(rsi_2, 1) if rsi_2 is not None else None,
                "atr_14":           round(atr, 4) if atr is not None else None,
                "vol_usd_m":        round(vol_usd_m, 1),
                # Mean reversion metrics
                "bb_pct":           round(bb_pct, 3) if bb_pct is not None else None,
                "bb_upper":         round(bb_upper, 4) if bb_upper is not None else None,
                "bb_lower":         round(bb_lower, 4) if bb_lower is not None else None,
                "bb_bandwidth":     round(bb_bw, 2)   if bb_bw   is not None else None,
                "zscore_20":        round(zsc, 2)      if zsc     is not None else None,
                "williams_r":       round(wil_r, 1)    if wil_r   is not None else None,
                "dist_sma50_pct":   round(dist_sma50_pct, 1),
                "dist_sma200_pct":  round(dist_sma200_pct, 1),
                # Setup classification
                "setup_label":      setup_label,
                "setup_desc":       setup_desc,
                "setup_category":   setup_cat,
                "conviction":       conv,
                "trade":            trade,
                # Backward compat
                "avg_vol_m":        round(vol_usd_m, 1),
                "passes":           passes,
            })
        except Exception as exc:
            log.warning("Scan failed for %s: %s", ticker, exc)

    df = pd.DataFrame(results)
    if df.empty:
        return df
    return (
        df[df["passes"]]
        .sort_values("conviction", ascending=False)
        .reset_index(drop=True)
    )


def _run_from_bybit(bybit_data: dict, tickers: list[str], criteria: ScanCriteria,
                    regime_score: float | None = None) -> pd.DataFrame:
    """Scanner core that consumes pre-fetched Bybit DataFrames instead of yfinance."""
    log.info("Scanning %d Bybit tickers …", len(bybit_data))
    results = []
    for ticker in tickers:
        if ticker not in bybit_data:
            continue
        try:
            df = bybit_data[ticker]
            s  = df["close"].dropna()
            h  = df["high"].dropna() if "high" in df.columns else pd.Series()
            lo = df["low"].dropna()  if "low"  in df.columns else pd.Series()

            # Bybit turnover is already in USD; use that for volume USD
            if "turnover" in df.columns:
                v_usd = df["turnover"].dropna()
            else:
                v_usd = (df["volume"] * df["close"]).dropna()

            if len(s) < 63:
                continue

            price  = float(s.iloc[-1])
            sma50  = float(s.iloc[-50:].mean())
            sma200 = float(s.iloc[-200:].mean()) if len(s) >= 200 else sma50
            mom3m  = (price - float(s.iloc[-63])) / float(s.iloc[-63]) * 100
            mom121 = _momentum_12_1(s)
            rsi    = _rsi(s, 14)
            rsi_2  = _rsi2(s)

            bb_upper, bb_mid, bb_lower, bb_pct, bb_bw = _bollinger(s, 20, 2.0)
            zsc   = _zscore(s, 20)
            wil_r = _williams_r(s, 14)
            atr   = _atr(h, lo, s, 14) if len(h) and len(lo) else None
            dist_sma50_pct  = (price / sma50  - 1) * 100 if sma50  else 0
            dist_sma200_pct = (price / sma200 - 1) * 100 if sma200 else 0

            vol_usd_m = float(v_usd.iloc[-20:].mean() / 1e6) if len(v_usd) >= 20 else 0

            passes = True
            if criteria.min_price and price < criteria.min_price:
                passes = False
            if vol_usd_m < criteria.min_volume_usd_m:
                passes = False
            if criteria.above_sma200 and price < sma200:
                passes = False
            if criteria.above_sma50 and price < sma50:
                passes = False
            if rsi < criteria.min_rsi or rsi > criteria.max_rsi:
                passes = False
            if criteria.min_momentum_3m is not None and mom3m < criteria.min_momentum_3m:
                passes = False

            vol_series = df["volume"].dropna() if "volume" in df.columns else v_usd
            bo = breakout_signals(s, h, vol_series)
            setup_label, setup_desc, setup_cat = classify_setup(
                price, sma50, sma200, rsi, mom3m, bb_pct, zsc, wil_r, rsi_2,
                vol_ratio=bo["vol_ratio"], donch_hi20=bo["donch_hi20"],
                donch_hi55=bo["donch_hi55"], squeeze=bo["squeeze"],
            )

            if price < 0.01:
                price_fmt = f"{price:.6f}"
            elif price < 1:
                price_fmt = f"{price:.4f}"
            elif price < 100:
                price_fmt = f"{price:.2f}"
            else:
                price_fmt = f"{price:,.2f}"

            conv  = conviction_score(
                setup_label, rsi, mom3m, bb_pct, zsc, wil_r, vol_usd_m, setup_cat,
                rsi2=rsi_2, regime_score=regime_score,
            )
            trade = trade_suggestion(
                setup_label, price, sma50, sma200, bb_upper, bb_mid, bb_lower, rsi, mom3m, atr,
            )
            results.append({
                "ticker":           ticker,
                "price":            round(price, 6 if price < 0.01 else (4 if price < 1 else 2)),
                "price_fmt":        price_fmt,
                "sma50":            round(sma50, 2),
                "sma200":           round(sma200, 2),
                "above_sma50":      bool(price > sma50),
                "above_sma200":     bool(price > sma200),
                "mom_3m_pct":       round(mom3m, 1),
                "mom_12_1_pct":     round(mom121, 1) if mom121 is not None else None,
                "rsi_14":           round(rsi, 1),
                "rsi_2":            round(rsi_2, 1) if rsi_2 is not None else None,
                "atr_14":           round(atr, 4) if atr is not None else None,
                "vol_usd_m":        round(vol_usd_m, 1),
                "bb_pct":           round(bb_pct, 3) if bb_pct is not None else None,
                "bb_upper":         round(bb_upper, 4) if bb_upper is not None else None,
                "bb_lower":         round(bb_lower, 4) if bb_lower is not None else None,
                "bb_bandwidth":     round(bb_bw, 2)   if bb_bw   is not None else None,
                "zscore_20":        round(zsc, 2)      if zsc     is not None else None,
                "williams_r":       round(wil_r, 1)    if wil_r   is not None else None,
                "dist_sma50_pct":   round(dist_sma50_pct, 1),
                "dist_sma200_pct":  round(dist_sma200_pct, 1),
                "setup_label":      setup_label,
                "setup_desc":       setup_desc,
                "setup_category":   setup_cat,
                "conviction":       conv,
                "trade":            trade,
                "avg_vol_m":        round(vol_usd_m, 1),
                "passes":           passes,
            })
        except Exception as exc:
            log.warning("Bybit scan failed for %s: %s", ticker, exc)

    df = pd.DataFrame(results)
    if df.empty:
        return df
    return (
        df[df["passes"]]
        .sort_values("conviction", ascending=False)
        .reset_index(drop=True)
    )


def _rsi(series: pd.Series, period: int = 14) -> float:
    delta    = series.diff().dropna()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean().iloc[-1]
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    return float(100 - (100 / (1 + avg_gain / avg_loss)))
