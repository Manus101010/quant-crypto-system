"""
Two SHORT setups that passed the Oct 2026 research (research/families/REPORT*.md):

  Distribution Short     A coin that ran up hard (+50% in 120 days, or 50 SMA above
                         200 SMA) goes quiet (Bollinger width in the bottom 10% of
                         180 days) and slips into the lower half of its 20-day range.
                         Short the FIRST quiet day. Not when BTC is trending down.
                         Stop 3.5 ATR above, trail 3.5 ATR, up to 60 days.
                         Full MEXC perp universe: n 669, PF 2.24, +0.366R.

  Downtrend Bounce Fade  A coin BELOW its 200 SMA bounces sharply (5-day return
                         z-score >= 2 within the last 7 days, peak >= 2.5 ATR above
                         the 20 EMA), the last 3 days are calmer (avg true range
                         <= ATR) and price is still >= 0.25 ATR above the 20 EMA.
                         Only when BTC is MIXED and the coin trades >= $2M a day.
                         Stop 0.25 ATR above the 7-day high, target the 20 EMA,
                         up to 10 days. Liquid coins: n 415, PF 1.63, +0.099R.

Vectorised over a whole daily DataFrame so the backtest and the live scan use the
exact same code. Only data up to and including each bar is used.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DIST = "Distribution Short"
FADE = "Downtrend Bounce Fade"
LABELS = {DIST, FADE}

DESCRIPTIONS = {
    DIST: ("Ran up hard, has gone quiet (volatility in the bottom 10% of 6 months) and is "
           "slipping to the bottom of its range. Supply is absorbing demand; the next "
           "expansion tends to be down. Short, trail the stop."),
    FADE: ("A sharp bounce in a coin that is below its 200-day trend, now losing steam. "
           "Relief rallies like this are mostly short covering. Short, take profit at the "
           "20 EMA (usually within ~4 days)."),
}

DIST_MIN_QV = 0.5e6
FADE_MIN_QV = 2e6


def btc_trend(btc_close: pd.Series) -> pd.Series:
    """UP / MIXED / DOWN per day from BTC's close vs its 50 and 200 SMA."""
    c = btc_close
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    lab = pd.Series("MIXED", index=c.index)
    lab[(c > s200) & (s50 > s200) & (c > s50)] = "UP"
    lab[(c < s200) & (s50 < s200) & (c < s50)] = "DOWN"
    lab[s200.isna()] = "NA"
    return lab


def _ind(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l = df["close"], df["high"], df["low"]
    v = df["volume"] if "volume" in df.columns else pd.Series(np.nan, index=df.index)
    x = pd.DataFrame(index=df.index)
    x["c"], x["h"], x["l"] = c, h, l
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    x["atr"] = tr.rolling(14).mean()
    x["tr3"] = tr.rolling(3).mean()
    x["ema9"] = c.ewm(span=9, adjust=False).mean()
    x["ema20"] = c.ewm(span=20, adjust=False).mean()
    x["sma50"] = c.rolling(50).mean()
    x["sma200"] = c.rolling(200).mean()
    r5 = c / c.shift(5) - 1
    x["z5"] = (r5 - r5.rolling(90).mean()) / r5.rolling(90).std()
    x["ret120"] = c / c.shift(120) - 1
    std20 = c.rolling(20).std()
    x["bbw_pct"] = (4 * std20 / c.rolling(20).mean()).rolling(180).rank(pct=True)
    x["hh20p"] = h.rolling(20).max().shift(1)
    x["ll20p"] = l.rolling(20).min().shift(1)
    x["qvol20"] = (c * v).rolling(20).mean()
    return x


def detect(df: pd.DataFrame, btc_close: pd.Series | None) -> pd.DataFrame:
    """Per bar: label (or None) and the trade plan. Columns: label, stop, target,
    trail_atr, max_hold, atr."""
    x = _ind(df)
    out = pd.DataFrame(index=df.index, data={"label": None, "stop": np.nan, "target": np.nan,
                                              "trail_atr": np.nan, "max_hold": np.nan})
    out["atr"] = x["atr"]
    if btc_close is None or len(x) < 205:
        return out
    btc = btc_trend(btc_close.reindex(x.index.normalize(), method="ffill"))
    btc.index = x.index

    # ── Distribution Short ──
    post_up = (x["ret120"] >= 0.50) | (x["sma50"] > x["sma200"])
    coiled = (x["bbw_pct"] <= 0.10) & post_up
    first = coiled & ~coiled.shift(fill_value=False)
    lower_half = x["c"] < (x["hh20p"] + x["ll20p"]) / 2
    dist = first & lower_half & (btc != "DOWN") & (btc != "NA") & (x["qvol20"] >= DIST_MIN_QV)

    # ── Downtrend Bounce Fade ──
    rip = x["z5"].rolling(7).max() >= 2.0
    peak = ((x["h"] - x["ema20"]) / x["atr"]).rolling(7).max() >= 2.5
    calm = x["tr3"] <= x["atr"]
    room = (x["c"] - x["ema20"]) >= 0.25 * x["atr"]
    fade = (rip & peak & calm & room & (x["c"] < x["sma200"]) & (btc == "MIXED")
            & (x["qvol20"] >= FADE_MIN_QV))

    hi7 = x["h"].rolling(7).max()
    d = dist.fillna(False).values
    f = fade.fillna(False).values
    out.loc[d, "label"] = DIST
    out.loc[d, "stop"] = (x["c"] + 3.5 * x["atr"])[d]
    out.loc[d, "trail_atr"] = 3.5
    out.loc[d, "max_hold"] = 60
    ff = f & ~d                                       # one label per bar
    out.loc[ff, "label"] = FADE
    out.loc[ff, "stop"] = (hi7 + 0.25 * x["atr"])[ff]
    out.loc[ff, "target"] = x["ema20"][ff]
    out.loc[ff, "max_hold"] = 10
    return out


def latest(df: pd.DataFrame, btc_close: pd.Series | None) -> dict | None:
    """The setup on the last CLOSED daily bar of df (the live scan), or None.
    Exchanges return today's still-forming candle as the last row; the research
    only ever used closed bars, so it is dropped here."""
    if df is None or len(df) < 206:
        return None
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    if pd.Timestamp(df.index[-1]).normalize() >= today:
        df = df.iloc[:-1]
    row = detect(df, btc_close).iloc[-1]
    if not row["label"]:
        return None
    return {"label": row["label"], "stop": float(row["stop"]),
            "target": None if pd.isna(row["target"]) else float(row["target"]),
            "trail_atr": None if pd.isna(row["trail_atr"]) else float(row["trail_atr"]),
            "max_hold": int(row["max_hold"]), "atr": float(row["atr"])}
