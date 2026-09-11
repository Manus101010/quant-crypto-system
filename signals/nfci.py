"""
Signal 8: Financial Conditions (Chicago Fed NFCI)
The National Financial Conditions Index synthesises 105 indicators covering
risk, credit, and leverage across money markets, debt, and equity markets.
NEGATIVE value = loose (easy) conditions → HIGH score (deploy capital).
POSITIVE value = tight (stressed) conditions → LOW score (be cautious).
Historical range: roughly −1.7 (very loose) to +2.8 (GFC stress).
"""
from __future__ import annotations
import numpy as np
from utils.fred import fetch_fred
from utils.logger import get_logger

log = get_logger(__name__)


def compute() -> dict:
    try:
        nfci = fetch_fred("NFCI")          # weekly, 1-week lag
        current = float(nfci.iloc[-1])
        prev_4w = float(nfci.iloc[-4]) if len(nfci) >= 4 else current

        # Score: 50 at neutral (NFCI=0), +33 points per standard deviation
        # below zero (looser), -33 per SD above zero.
        # NFCI = -1.5 → ≈100; NFCI = 0 → 50; NFCI = +1.5 → ≈0
        score = float(np.clip(50 + (-current) * 33, 0, 100))

        trend = current - prev_4w  # negative = loosening (bullish)
        trend_str = f"loosening" if trend < -0.05 else "tightening" if trend > 0.05 else "stable"

        return {
            "name":   "Financial Conditions",
            "score":  round(score, 1),
            "value":  round(current, 3),
            "unit":   "NFCI",
            "detail": (
                f"Chicago Fed NFCI = {current:+.3f} "
                f"({'loose' if current < 0 else 'tight'} conditions) | "
                f"4-week trend: {trend_str} ({trend:+.3f})"
            ),
            "raw": nfci.tail(52).tolist(),
        }

    except Exception as exc:
        log.warning("nfci FRED failed (%s) — trying yfinance proxy", exc)
        return _yfinance_fallback(str(exc))


def _yfinance_fallback(orig_err: str) -> dict:
    """
    Proxy financial conditions from HYG/LQD credit spread + VIX level.
    Tight conditions = wide HYG/LQD spread + elevated VIX.
    """
    try:
        import yfinance as yf
        import numpy as np
        raw = yf.download(["HYG", "LQD", "^VIX"], period="1y", interval="1d",
                          progress=False, auto_adjust=True)["Close"]
        spread = (raw["LQD"] / raw["HYG"]).dropna()   # higher = tighter credit
        vix    = raw["^VIX"].dropna()

        if len(spread) < 20:
            raise ValueError("insufficient data")

        # Normalise spread to z-score vs 1Y
        sp_z   = float((spread.iloc[-1] - spread.mean()) / spread.std())
        vix_z  = float((vix.iloc[-1]   - vix.mean())    / vix.std())

        # Composite proxy: negative z = loose, positive = tight (like NFCI)
        proxy_nfci = (sp_z * 0.6 + vix_z * 0.4)
        score = float(np.clip(50 + (-proxy_nfci) * 20, 0, 100))

        trend_str = "loosening" if proxy_nfci < -0.2 else "tightening" if proxy_nfci > 0.2 else "stable"
        return {
            "name":   "Financial Conditions",
            "score":  round(score, 1),
            "value":  round(proxy_nfci, 3),
            "unit":   "proxy z-score",
            "detail": (
                f"HYG/LQD+VIX proxy = {proxy_nfci:+.2f} "
                f"({'loose' if proxy_nfci < 0 else 'tight'}) | "
                f"Trend: {trend_str} | FRED unavailable"
            ),
            "raw": spread.tail(52).tolist(),
        }
    except Exception as exc2:
        log.warning("nfci yfinance fallback also failed: %s", exc2)
        return {
            "name": "Financial Conditions", "score": 50.0, "value": None,
            "unit": "NFCI", "detail": f"FRED unavailable: {orig_err}", "raw": [],
        }
