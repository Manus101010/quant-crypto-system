"""
How overextended is a coin right now? (shared by the "do not chase" guard and,
if it passes research, the intraday Overextension Short.)

Measured on CLOSED 1h and 4h bars from the trading venue:
  ext_4h  = (highest high of the last 12h - 4h EMA20) / 4h ATR(14)
  ext_1h  = (highest high of the last 12h - 1h EMA20) / 1h ATR(14)
  pct_4h  = how far the price is above the 4h EMA20, in %
  rsi_4h  = 4h RSI(14)
"Overextended" = ext_4h >= 3 AND ext_1h >= 3 — the same definition as the core
variant in research/overext/backtest.py.
"""
from __future__ import annotations
import pandas as pd

EXT_ATR = 3.0


def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def _atr(df, n=14):
    c = df["close"]
    tr = pd.concat([df["high"] - df["low"], (df["high"] - c.shift()).abs(),
                    (df["low"] - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.where(dn != 0))


def measure(symbol: str, h1: pd.DataFrame | None = None) -> dict | None:
    """Overextension read for `symbol` ('ORCA-USD'), or None if no data."""
    if h1 is None:
        from config import CANDLE_VENUE
        from utils.exchange import get_ohlcv
        h1 = get_ohlcv(symbol, "1h", limit=300, exchange=CANDLE_VENUE)
        if h1 is None or h1.empty:
            h1 = get_ohlcv(symbol, "1h", limit=300)
    if h1 is None or len(h1) < 120:
        return None
    h1 = h1.iloc[:-1]                                  # drop the still-forming hour
    h4 = h1.resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    if len(h4) < 30:
        return None
    peak = float(h1["high"].iloc[-12:].max())
    price = float(h1["close"].iloc[-1])
    e1, a1 = float(_ema(h1["close"], 20).iloc[-1]), float(_atr(h1).iloc[-1])
    e4, a4 = float(_ema(h4["close"], 20).iloc[-1]), float(_atr(h4).iloc[-1])
    ext4 = (peak - e4) / a4 if a4 else 0.0
    ext1 = (peak - e1) / a1 if a1 else 0.0
    return {"ext_4h": ext4, "ext_1h": ext1, "pct_4h": (price / e4 - 1) * 100,
            "ema20_4h": e4, "rsi_4h": float(_rsi(h4["close"]).iloc[-1]), "price": price,
            "overextended": ext4 >= EXT_ATR and ext1 >= EXT_ATR}


def chase_message(symbol: str, m: dict, setup: str = "") -> str:
    coin = symbol.replace("-USD", "")
    return (f"🚫 <b>Too extended to chase — {coin}</b>\n"
            f"A {setup or 'long'} signal triggered, but {coin} is "
            f"<b>{m['pct_4h']:+.0f}% above its 4h 20 EMA</b> ({_fmt(m['ema20_4h'])}), "
            f"{m['ext_4h']:.1f}× its normal 4h move above the average"
            f" (4h RSI {m['rsi_4h']:.0f}).\n"
            "Buying here is how pumps end in liquidation, so this long was blocked. "
            "If it pulls back to the average and the setup comes again, you'll get a fresh alert.")


def _fmt(p: float) -> str:
    return f"${p:,.2f}" if p >= 100 else (f"${p:.4f}" if p >= 0.01 else f"${p:.8f}".rstrip("0"))
