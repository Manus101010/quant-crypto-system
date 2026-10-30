"""
Daily movers board: what he does by hand every morning, done for him.

He sorts the day's biggest gainers and losers, clicks into about five of each and asks one
question per coin: which of four states is it in? This module answers it for the top
movers on MEXC perps, with a 0 to 100 score for how cleanly the coin fits that state, and
the backtest verdict for the state next to it (research/movers/run.py, 30 Oct 2026,
Binance 1h 2021..2026, maker fees):

  Gainers
    ROLLING OVER   stretched >= 3 ATR above the 1h midline, bars shrinking (last 3 bars'
                   range <= 0.7x the 3 before), Parabolic SAR just flipped above price.
                   Tested as a short to the midline: LOST (PF 0.84). Random shorts on
                   the same list broke even. Grid only, small, or skip.
    STILL RUNNING  SAR under price, above the midline, no midline touch for 12+ hours.
                   Tested long with a 5% trail: break even 2023..2026, worked only in
                   the 2021 bull. Only when the long gate is open.
    STRETCHED      >= 3 ATR above the midline but not turned yet: wait for the roll over.
  Losers
    STILL DUMPING  SAR above price, below the midline, no touch for 12+ hours.
                   Tested short with a 5% trail: PF 1.35 in 2023..2025 AND 2025..2026,
                   failed in the 2021..22 bull. Best of the eight. Weak statistically
                   (t about 1.2), so paper, and only while BTC is below its 50 day.
    TURNING UP     stretched down, shrinking, SAR flipped under price (bounce long).
                   Tested: the worst of all (PF 0.18). Do not buy these.
    STRETCHED      >= 3 ATR below the midline, not turned: no trade.
  Anything else is CHOP.

Signal only. Nothing here places an order. Every board is stored in app_state as
movers:<stamp> so the states can be graded against what price did next.
"""
from __future__ import annotations

import datetime as _dt
import json

import numpy as np
import pandas as pd

from utils.logger import get_logger

log = get_logger(__name__)

TOP_N = 5
MIN_QV_USD = 2_000_000            # 24h quote volume on MEXC perps (thinner is untradeable)

VERDICT = {
    "ROLLING OVER": ("🔻", "4h has turned too (the rare aligned case, PF 1.06 to 1.88 but under 70 trades). Without the 4h:  back to the midline 7 times in 10, but the 3 misses cost as much (about break even). A grid here does worse than a plain short"),
    "FADE AGAINST 4H": ("⛔", "skip: fading a rollover while the 4h is still rising lost (PF 0.86, 664 trades, 15m)"),
    "STILL RUNNING": ("🚀", "tested 15m, 1h, 4h: break even, random entries on the list did as well. Longs only if the long gate is open"),
    "STRETCHED UP": ("⏳", "not turned yet, wait for the SAR to flip"),
    "STILL DUMPING": ("📉", "tested: best of the eight (PF 1.35, 2023 to 2026), weak stats, paper only, BTC below 50 day"),
    "TURNING UP": ("⚠️", "tested: worst of the eight (PF 0.18). Do not buy these bounces"),
    "STRETCHED DOWN": ("⏳", "stretched down, not turned: no trade"),
    "CHOP": ("·", "no clean state"),
}


def _psar(h: np.ndarray, l: np.ndarray, af0=0.02, step=0.02, amax=0.2):
    n = len(h)
    sar = np.full(n, np.nan)
    up = np.zeros(n, dtype=int)
    if n < 3:
        return sar, up
    bull, s, ep, af = True, l[0], h[0], af0
    for i in range(1, n):
        s = s + af * (ep - s)
        if bull:
            s = min(s, l[i - 1], l[max(i - 2, 0)])
            if l[i] < s:
                bull, s, ep, af = False, ep, l[i], af0
            elif h[i] > ep:
                ep, af = h[i], min(af + step, amax)
        else:
            s = max(s, h[i - 1], h[max(i - 2, 0)])
            if h[i] > s:
                bull, s, ep, af = True, ep, h[i], af0
            elif l[i] < ep:
                ep, af = l[i], min(af + step, amax)
        sar[i], up[i] = s, (1 if bull else -1)
    return sar, up


def features_1h(df: pd.DataFrame) -> dict | None:
    """Same definitions as research/movers/run.py, on the last CLOSED 1h bar."""
    if df is None or len(df) < 40:
        return None
    d = df.iloc[:-1] if len(df) > 40 else df        # last row is the forming bar
    h, l, c = d["high"].to_numpy(float), d["low"].to_numpy(float), d["close"].to_numpy(float)
    mid = pd.Series(c).rolling(20).mean().to_numpy()
    tr = np.maximum.reduce([h - l, np.abs(h - np.r_[np.nan, c[:-1]]), np.abs(l - np.r_[np.nan, c[:-1]])])
    atr = pd.Series(tr).rolling(14).mean().to_numpy()
    sar, up = _psar(h, l)
    rng = h - l
    comp = rng[-3:].mean() / max(rng[-6:-3].mean(), 1e-12)
    hh12, ll12 = h[-12:].max(), l[-12:].min()
    a, m = atr[-1], mid[-1]
    if not (np.isfinite(a) and np.isfinite(m) and a > 0):
        return None
    touch = (l <= mid) & (h >= mid)
    since = 0
    for t in touch[::-1]:
        if t:
            break
        since += 1
    flip_dn = [i for i in range(1, 4) if up[-i] == -1 and up[-i - 1] == 1]
    flip_up = [i for i in range(1, 4) if up[-i] == 1 and up[-i - 1] == -1]
    return {"close": c[-1], "mid": m, "atr": a, "sar": sar[-1], "up": int(up[-1]),
            "comp": float(comp), "stretch_up": (hh12 - m) / a, "stretch_dn": (m - ll12) / a,
            "since_mid": since, "flip_dn": bool(flip_dn), "flip_up": bool(flip_up),
            "hh12": hh12, "ll12": ll12}


def sar4_up(df: pd.DataFrame | None) -> bool | None:
    """True when the 4h SAR is under price on the last closed 4h bar (4h still rising)."""
    if df is None or len(df) < 10:
        return None
    d = df.iloc[:-1]
    _, up = _psar(d["high"].to_numpy(float), d["low"].to_numpy(float))
    return bool(up[-1] == 1)


def _clip(x, lo=0.0, hi=1.0):
    return float(min(hi, max(lo, x)))


def classify(f: dict, side: str) -> tuple[str, int, str]:
    """(state, score 0..100, one line why). side 'gainer' or 'loser'. The score is how
    cleanly the coin fits the state, not an expected profit."""
    c, m, a = f["close"], f["mid"], f["atr"]
    dist = (c - m) / a
    if side == "gainer":
        if f["stretch_up"] >= 3 and f["comp"] <= 0.7 and f["flip_dn"] and dist > 0.5:
            s = 40 + 25 * _clip((f["stretch_up"] - 3) / 4) + 20 * _clip((0.7 - f["comp"]) / 0.4) + 15 * _clip(dist / 3)
            return "ROLLING OVER", int(s), (f"{f['stretch_up']:.1f} ATR above the midline at the peak, bars "
                                           f"{f['comp']:.0%} of the run's size, SAR flipped down")
        if f["up"] == 1 and dist > 0 and f["since_mid"] >= 12 and f["stretch_up"] < 6:
            s = 40 + 30 * _clip(f["since_mid"] / 36) + 30 * _clip(1 - abs(dist - 2) / 3)
            return "STILL RUNNING", int(s), (f"SAR under price, {f['since_mid']}h without touching the midline, "
                                            f"{dist:.1f} ATR above it")
        if f["stretch_up"] >= 3:
            return "STRETCHED UP", int(30 + 10 * _clip((f["stretch_up"] - 3) / 4)), \
                f"{f['stretch_up']:.1f} ATR above the midline, SAR still under price"
    else:
        if f["up"] == -1 and dist < 0 and f["since_mid"] >= 12 and f["stretch_dn"] < 6:
            s = 40 + 30 * _clip(f["since_mid"] / 36) + 30 * _clip(1 - abs(-dist - 2) / 3)
            return "STILL DUMPING", int(s), (f"SAR above price, {f['since_mid']}h without touching the midline, "
                                            f"{-dist:.1f} ATR below it")
        if f["stretch_dn"] >= 3 and f["comp"] <= 0.7 and f["flip_up"] and dist < -0.5:
            s = 40 + 25 * _clip((f["stretch_dn"] - 3) / 4) + 20 * _clip((0.7 - f["comp"]) / 0.4) + 15 * _clip(-dist / 3)
            return "TURNING UP", int(s), (f"{f['stretch_dn']:.1f} ATR below the midline, bars shrinking, "
                                         f"SAR flipped up")
        if f["stretch_dn"] >= 3:
            return "STRETCHED DOWN", int(30 + 10 * _clip((f["stretch_dn"] - 3) / 4)), \
                f"{f['stretch_dn']:.1f} ATR below the midline, SAR still above price"
    return "CHOP", 0, f"{dist:+.1f} ATR from the midline, no clean state"


def top_movers(n: int = TOP_N, min_qv: float = MIN_QV_USD, tickers: dict | None = None) -> tuple[list, list]:
    """([(base, pct, qv)] gainers, losers) from MEXC USDT perps, by 24h % change."""
    if tickers is None:
        from utils.exchange import _client
        ex = _client("mexc", swap=True)
        tickers = ex.fetch_tickers(params={"type": "swap"}) if ex else {}
    rows = []
    for sym, t in tickers.items():
        if not sym.endswith(":USDT"):
            continue
        base = sym.split("/")[0]
        pct, qv = t.get("percentage"), t.get("quoteVolume")
        if pct is None:
            continue
        if qv is None and t.get("baseVolume") and t.get("last"):
            qv = t["baseVolume"] * t["last"]
        if (qv or 0) < min_qv or base.endswith("STOCK"):
            continue
        rows.append((base, float(pct), float(qv or 0)))
    rows.sort(key=lambda r: r[1])
    gainers = [r for r in rows[::-1] if r[1] > 0][:n]
    losers = [r for r in rows if r[1] < 0][:n]
    return gainers, losers


def board(n: int = TOP_N, *, tickers: dict | None = None, candles: dict | None = None,
          store: bool = True) -> dict:
    """Classify the top n gainers and losers. candles: {base: 1h DataFrame} for tests."""
    g, lo = top_movers(n, tickers=tickers)
    out = {"t": _dt.datetime.utcnow().isoformat(timespec="minutes"), "rows": []}
    for side, rows in (("gainer", g), ("loser", lo)):
        for base, pct, qv in rows:
            if candles is not None:
                df = candles.get(base)
            else:
                from utils.exchange import get_ohlcv
                df = get_ohlcv(f"{base}-USD", "1h", 120, exchange="mexc")
            f = features_1h(df)
            if f is None:
                out["rows"].append({"base": base, "side": side, "pct": pct, "qv": qv,
                                    "state": "NO DATA", "score": 0, "why": ""})
                continue
            st, sc, why = classify(f, side)
            up4 = None
            try:
                d4 = candles.get(base + "@4h") if candles is not None else None
                if d4 is None and candles is None:
                    from utils.exchange import get_ohlcv
                    d4 = get_ohlcv(f"{base}-USD", "4h", 60, exchange="mexc")
                up4 = sar4_up(d4)
            except Exception as exc:      # noqa: BLE001
                log.debug("movers 4h %s: %s", base, exc)
            if st == "ROLLING OVER" and up4:
                st, sc = "FADE AGAINST 4H", 0
                why += "; but the 4h SAR is still under price"
            out["rows"].append({"up4": up4, "base": base, "side": side, "pct": pct, "qv": qv, "state": st,
                                "score": sc, "why": why, "price": f["close"], "mid": f["mid"],
                                "sar": f["sar"], "hh12": f["hh12"], "ll12": f["ll12"]})
    if store:
        try:
            from triggers import db
            db.set_state(f"movers:{out['t']}", json.dumps(out, default=float))
        except Exception as exc:          # noqa: BLE001
            log.debug("movers store failed: %s", exc)
    return out


def _p(x) -> str:
    from desk.botplan import _p as fmt
    return fmt(float(x))


def text(b: dict) -> str:
    try:
        from utils.breadth import long_gate
        longs_ok, _ = long_gate()
    except Exception:                     # noqa: BLE001
        longs_ok = None
    lines = ["📊 <b>Today's movers</b> (MEXC perps, 24h, 1h chart read)"]
    for side, head in (("gainer", "🟢 <b>Top gainers</b>"), ("loser", "🔴 <b>Top losers</b>")):
        rows = [r for r in b["rows"] if r["side"] == side]
        if not rows:
            continue
        lines.append("")
        lines.append(head)
        for r in rows:
            icon, _ = VERDICT.get(r["state"], ("·", ""))
            sc = f" {r['score']}/100" if r["score"] else ""
            lines.append(f"{icon} <b>{r['base']}</b> {r['pct']:+.0f}% · {r['state'].title()}{sc}")
            if r.get("why"):
                lines.append(f"   {r['why']}")
            if r["state"] == "STILL DUMPING":
                lines.append(f"   Paper short idea: stop above {_p(max(r['sar'], r['mid']))} (SAR or midline), 5% trail")
            elif r["state"] == "ROLLING OVER":
                lines.append(f"   Midline {_p(r['mid'])} · high {_p(r['hh12'])}. /bot {r['base']} for a grid plan")
            elif r["state"] == "STILL RUNNING" and longs_ok is False:
                lines.append("   Long gate is closed (BTC below its 50 day): watch only")
    seen = {r["state"] for r in b["rows"]}
    notes = [f"{VERDICT[s][0]} {s.title()}: {VERDICT[s][1]}" for s in VERDICT
             if s in seen and s not in ("CHOP",)]
    if notes:
        lines.append("")
        lines.append("<b>What the backtest says</b>")
        lines.extend(notes)
    lines.append("")
    lines.append("<i>Score = how cleanly it fits the state, not a profit forecast. Signal only.</i>")
    return "\n".join(lines)
