"""
Trade Desk — technical analysis engine.

Reuses the scanner's indicator stack and the BTC regime read; the ONLY new
indicator is MACD (missing from the scanner). Everything is computed from raw
ccxt OHLC in code — no TradingView control, no order integration. Read-only.

Public surface:
  TIMEFRAMES                       ordered list the desk computes
  compute_tf(df)                   scalar indicator bundle for one timeframe
  chart_series(df, bars)           arrays for the SVG chart (candles + overlays)
  structure(df_daily)              range hi/lo + breakout/breakdown levels
  build_call(tf_reads, structure_, funding, btc)  long/neutral/short + reasons
  grid_params(direction, ...)      volatility-derived grid suggestion
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd

from skills.scanner import (_bollinger, _rsi, _rsi2, _zscore, _williams_r, _atr,
                            breakout_signals)
from utils import btc_regime

TIMEFRAMES = ["1w", "1d", "4h", "1h"]
_TF_WEIGHT = {"1w": 3, "1d": 3, "4h": 2, "1h": 1}   # higher TFs dominate the Call


# ── Indicators (MACD is the only new one) ─────────────────────────────────────
def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def macd_series(close: pd.Series, fast=12, slow=26, sig=9):
    macd = _ema(close, fast) - _ema(close, slow)
    signal = _ema(macd, sig)
    return macd, signal, macd - signal


def _macd_state(close: pd.Series) -> tuple[str, float]:
    if len(close) < 35:
        return "n/a", 0.0
    macd, signal, hist = macd_series(close)
    m, h = float(macd.iloc[-1]), float(hist.iloc[-1])
    state = ("bull↑" if h > 0 and m > 0 else "bull" if h > 0 else
             "bear↓" if h < 0 and m < 0 else "bear")
    return state, h


def _realized_vol_daily(close: pd.Series, days=30) -> float | None:
    """Daily realized volatility (% st.dev of daily log returns)."""
    rets = np.log(close / close.shift(1)).dropna()
    if len(rets) < 5:
        return None
    return float(rets.iloc[-days:].std() * 100)


def _sma(close: pd.Series, n: int) -> float | None:
    return float(close.iloc[-n:].mean()) if len(close) >= n else None


def _trend(price, sma50, sma200) -> str:
    if sma50 and sma200:
        if price > sma50 > sma200:
            return "up"
        if price < sma50 < sma200:
            return "down"
    if sma50:
        return "up" if price > sma50 else "down"
    return "mixed"


def compute_tf(df: pd.DataFrame) -> dict | None:
    """Scalar indicator bundle for one timeframe's OHLC frame."""
    if df is None or df.empty or len(df) < 30:
        return None
    close, high, low = df["close"], df["high"], df["low"]
    price = float(close.iloc[-1])
    sma20, sma50, sma200 = _sma(close, 20), _sma(close, 50), _sma(close, 200)
    rsi = _rsi(close, 14)
    macd_state, macd_hist = _macd_state(close)
    _, bb_mid, _, bb_pct, bb_bw = _bollinger(close, 20, 2.0)
    return {
        "price": price, "sma20": sma20, "sma50": sma50, "sma200": sma200,
        "trend": _trend(price, sma50, sma200),
        "rsi": rsi, "rsi2": _rsi2(close),
        "macd_state": macd_state, "macd_hist": macd_hist,
        "bb_pct": bb_pct, "bb_bw": bb_bw,
        "williams_r": _williams_r(close, 14), "zscore": _zscore(close, 20),
        "atr": _atr(high, low, close, 14),
    }


def structure(df_daily: pd.DataFrame) -> dict:
    """Recent range + breakout/breakdown levels from the daily frame."""
    close, high = df_daily["close"], df_daily["high"]
    bo = breakout_signals(close, high, df_daily.get("volume"), df_daily["low"])
    price = float(close.iloc[-1])
    return {
        "price": price,
        "range_hi20": bo["donch_hi20"], "range_lo20": bo["donch_lo20"],
        "range_hi55": bo["donch_hi55"], "range_lo55": bo["donch_lo55"],
        "vol_ratio": bo["vol_ratio"], "squeeze": bo["squeeze"],
        "at_high": bo["donch_hi20"] is not None and price >= bo["donch_hi20"] * 0.999,
        "at_low": bo["donch_lo20"] is not None and price <= bo["donch_lo20"] * 1.001,
        "realized_vol_d": _realized_vol_daily(close),
    }


# ── Chart series (arrays for the SVG) ─────────────────────────────────────────
def _roll_mean(vals: list[float], n: int) -> list[float | None]:
    out, s = [], pd.Series(vals)
    m = s.rolling(n).mean()
    return [None if pd.isna(x) else float(x) for x in m]


def chart_series(df: pd.DataFrame, bars: int = 90) -> dict:
    """Everything the SVG chart needs for one timeframe, last `bars` candles."""
    d = df.tail(bars + 200)                 # keep history so MAs/BB are valid at the left edge
    close = d["close"]
    macd, signal, hist = macd_series(close)
    rsi_full = pd.Series([_rsi(close.iloc[:i + 1], 14) if i >= 14 else np.nan
                          for i in range(len(close))])
    mid = close.rolling(20).mean()
    sd = close.rolling(20).std(ddof=0)
    tail = slice(-bars, None)
    candles = [(float(o), float(h), float(l), float(c), float(v))
               for o, h, l, c, v in zip(d["open"].iloc[tail], d["high"].iloc[tail],
                                        d["low"].iloc[tail], d["close"].iloc[tail],
                                        d["volume"].iloc[tail])]

    def _f(series):
        return [None if pd.isna(x) else float(x) for x in series.iloc[tail]]

    return {
        "candles": candles,
        "sma20": _f(close.rolling(20).mean()),
        "sma50": _f(close.rolling(50).mean()),
        "sma200": _f(close.rolling(200).mean()),
        "bb_up": _f(mid + 2 * sd), "bb_lo": _f(mid - 2 * sd),
        "rsi": _f(rsi_full), "macd": _f(macd), "macd_signal": _f(signal),
        "macd_hist": _f(hist),
    }


# ── The Call (transparent — carries its reasons) ──────────────────────────────
def _net_trend(tf_reads: dict) -> int:
    net = 0
    for tf, r in tf_reads.items():
        if not r:
            continue
        s = {"up": 1, "down": -1, "mixed": 0}[r["trend"]]
        net += _TF_WEIGHT.get(tf, 1) * s
    return net                               # range roughly [-9, +9]


def build_call(tf_reads: dict, structure_: dict, funding: dict | None,
               btc: dict, chg_24h: float | None) -> dict:
    """
    Rules-based long/neutral/short with 2–3 specific reads, direction-aware vs
    BTC. Funding is referenced for SHORTS as a crowding read.
    """
    net = _net_trend(tf_reads)
    daily = tf_reads.get("1d") or {}
    rsi_d = daily.get("rsi")
    z_d = daily.get("zscore")
    reasons: list[str] = []

    # Alignment read
    aligned = [tf for tf, r in tf_reads.items() if r and r["trend"] == ("up" if net > 0 else "down")]
    if abs(net) >= 4:
        reasons.append(f"{'/'.join(aligned)} aligned {'up' if net > 0 else 'down'} "
                       f"(price vs 50/200-SMA), net trend {net:+d}")
    else:
        reasons.append(f"timeframes mixed (net trend {net:+d}) — no clean alignment")

    # Overextension / fade read (the 150% gainer case)
    hot_gainer = (chg_24h is not None and chg_24h >= 80)
    overbought = (rsi_d is not None and rsi_d >= 78) or (z_d is not None and z_d >= 2.0)
    at_high, at_low = structure_.get("at_high"), structure_.get("at_low")

    # Direction decision
    if hot_gainer and overbought:
        direction = "short"
        reasons.append(f"+{chg_24h:.0f}% 24h and overbought (RSI {rsi_d:.0f}, "
                       f"z {z_d:+.1f}) — blow-off, fade candidate")
    elif net >= 4 and not (rsi_d and rsi_d >= 82):
        direction = "long"
        if at_high:
            reasons.append(f"at the 20-day high ({_p(structure_.get('range_hi20'))}) — breakout")
        else:
            reasons.append("uptrend structure intact, not yet stretched")
    elif net <= -4:
        direction = "short"
        if at_low:
            reasons.append(f"at the 20-day low ({_p(structure_.get('range_lo20'))}) — breakdown")
        else:
            reasons.append("downtrend structure intact")
    else:
        direction = "neutral"
        reasons.append("ranging inside recent structure — no directional edge")

    # Funding as a crowding read (shorts especially)
    if direction == "short" and funding and funding.get("rate") is not None:
        fr = funding["rate"] * 100
        if fr >= 0.05:
            reasons.append(f"funding {fr:+.3f}%/8h — crowded longs paying, squeeze-prone "
                           f"(supports the fade)")
        elif fr <= -0.02:
            reasons.append(f"funding {fr:+.3f}%/8h — shorts already crowded, wary of a short squeeze")
        else:
            reasons.append(f"funding {fr:+.3f}%/8h — positioning roughly balanced")

    # BTC regime stamp (direction-aware)
    stamp = btc_regime.stamp_for(btc["label"], direction if direction != "neutral" else "long")
    caution = "CAUTION" in stamp
    reasons.append(f"BTC {btc['label']} — {stamp}")

    # Confidence: clean if strong alignment and BTC not fighting it
    clean = abs(net) >= 6 and not caution and direction != "neutral"
    confidence = "clean, aligned" if clean else ("mixed — size down" if direction != "neutral"
                                                 else "no edge — stand aside")
    return {"direction": direction, "reasons": reasons[:4], "confidence": confidence,
            "net_trend": net, "caution": caution}


# ── Grid parameters (derived from measured volatility) ────────────────────────
def grid_params(direction: str, price: float, atr_d: float | None,
                rv_d: float | None, structure_: dict, chg_24h: float | None) -> dict:
    """
    Volatility-derived grid suggestion. Range anchored to measured structure,
    rung spacing tied to ATR, leverage sized so a break OUT of the range doesn't
    liquidate. Conservative caps; floored at 1× with an explicit 'too volatile'
    surface when the math wants below 1×.
    """
    out = {"direction": direction, "ok": False, "note": ""}
    if not atr_d or atr_d <= 0 or not price:
        out["note"] = "ATR unavailable — cannot derive grid parameters."
        return out

    hi20, lo20 = structure_.get("range_hi20"), structure_.get("range_lo20")
    sma20 = None  # filled by caller-independent structure; kept simple here

    # Range per direction (measured, then vol-adjusted).
    if direction == "neutral" and hi20 and lo20:
        lo, hi = lo20, hi20
        basis = "current 20-day range"
    elif direction == "long":
        if structure_.get("at_high") and hi20:
            proj = price * (1 + (rv_d or 0) / 100 * math.sqrt(5))
            lo, hi = hi20, max(proj, price + 2 * atr_d)
            basis = "breakout: broken 20-day high as support → 5-day vol projection up"
        else:
            lo = max(lo20 or price - 2 * atr_d, price - 2 * atr_d)
            hi = price + 2 * atr_d
            basis = "uptrend leg: price ±2×ATR, floored at the 20-day low"
    elif direction == "short":
        hi = price + 1 * atr_d
        lo = min(lo20 or price - 2 * atr_d, price - 2 * atr_d)
        basis = "fade: invalidation +1×ATR above, target toward the 20-day low"
    else:
        lo, hi = price - 2 * atr_d, price + 2 * atr_d
        basis = "no structure — price ±2×ATR"

    if hi <= lo:
        lo, hi = price - 2 * atr_d, price + 2 * atr_d
        basis += " (adjusted: degenerate range)"
    width = hi - lo

    # Rung spacing ≈ half a daily ATR → each grid captures a real swing, not noise.
    step = 0.5 * atr_d
    count = int(min(60, max(8, round(width / step))))
    step_pct = step / price * 100

    # Leverage: a break OUT against the position by (half-range + 1×ATR) is the
    # modeled adverse move. Travel only a third of the way to liquidation on it.
    adverse_pct = (width / 2 + atr_d) / price
    lev_liq = 1.0 / adverse_pct if adverse_pct > 0 else 0.0
    raw = lev_liq * 0.33
    too_volatile = raw < 1.0

    lev = math.floor(raw)
    fresh_pump = chg_24h is not None and chg_24h >= 50
    high_vol = rv_d is not None and rv_d >= 10.0            # daily RV ≥10% ≈ extreme
    cap_reason = []
    if fresh_pump:
        cap_reason.append("24h > 50%")
    if high_vol:
        cap_reason.append("realized vol top-decile")
    if (fresh_pump or high_vol):
        lev = min(lev, 2)
    lev = min(lev, 5)

    out.update({
        "ok": True, "range_low": lo, "range_high": hi, "width_pct": width / price * 100,
        "basis": basis, "grid_count": count, "step_pct": step_pct,
        "step_atr_mult": 0.5, "atr_d": atr_d, "rv_d": rv_d,
        "adverse_pct": adverse_pct * 100, "lev_liq": lev_liq,
        "too_volatile": too_volatile,
        "leverage": None if too_volatile else max(1, lev),
        "leverage_caps": cap_reason,
    })
    if too_volatile:
        out["note"] = ("Measured volatility too high to suggest leverage here — the "
                       "modeled adverse move would exceed a safe fraction even at 1×. "
                       "Consider spot, or a tighter range.")
    return out


def _p(v) -> str:
    if v is None:
        return "—"
    v = float(v)
    if v < 0.01:  return f"${v:.6f}"
    if v < 1:     return f"${v:.4f}"
    if v < 100:   return f"${v:.2f}"
    return f"${v:,.2f}"
