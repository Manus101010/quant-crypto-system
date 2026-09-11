"""
Fundamental data fetcher via yfinance.
Gathers 8+ quarters of financial data plus TTM aggregation.
"""
from __future__ import annotations
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from analyst.cache import get_fundamentals, set_fundamentals
from utils.logger import get_logger

log = get_logger(__name__)
warnings.filterwarnings("ignore", category=FutureWarning)


def _safe_float(val) -> float | None:
    try:
        v = float(val)
        return None if np.isnan(v) else v
    except Exception:
        return None


def fetch(ticker: str, force: bool = False) -> dict:
    """Return comprehensive fundamental dict for ticker."""
    ticker = ticker.upper()

    if not force:
        cached = get_fundamentals(ticker, max_age_hours=6)
        if cached:
            log.info("Fundamentals cache hit: %s", ticker)
            return cached

    log.info("Fetching fundamentals for %s …", ticker)
    t = yf.Ticker(ticker)
    info = t.info or {}

    quarterly_income = _safe_df(t.quarterly_income_stmt)
    quarterly_cashflow = _safe_df(t.quarterly_cashflow)
    quarterly_balance = _safe_df(t.quarterly_balance_sheet)
    annual_income = _safe_df(t.income_stmt)

    quarters = _build_quarters(
        quarterly_income, quarterly_cashflow, quarterly_balance
    )
    ttm = _build_ttm(quarterly_income, quarterly_cashflow, quarterly_balance)
    ratios = _build_ratios(info, quarters, ttm)
    price_metrics = _price_metrics(info)

    data = {
        "ticker": ticker,
        "name": info.get("longName", ticker),
        "sector": info.get("sector", "Unknown"),
        "industry": info.get("industry", "Unknown"),
        "market_cap": _safe_float(info.get("marketCap")),
        "quarters": quarters,
        "ttm": ttm,
        "ratios": ratios,
        "price_metrics": price_metrics,
    }
    set_fundamentals(ticker, data)
    return data


def _safe_df(df) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    return df.copy()


def _row(df: pd.DataFrame, *keys: str) -> pd.Series:
    for k in keys:
        for idx in df.index:
            if str(idx).lower().replace(" ", "").replace("_", "") == k.lower().replace(" ", "").replace("_", ""):
                return df.loc[idx]
    return pd.Series(dtype=float)


def _build_quarters(income: pd.DataFrame, cashflow: pd.DataFrame,
                    balance: pd.DataFrame) -> list[dict]:
    if income.empty:
        return []
    cols = income.columns[:8]  # last 8 quarters
    out = []
    for col in cols:
        def g(df, *keys):
            s = _row(df, *keys)
            if col in s.index:
                return _safe_float(s[col])
            return None

        revenue  = g(income, "Total Revenue", "TotalRevenue")
        net_inc  = g(income, "Net Income", "NetIncome")
        gross_p  = g(income, "Gross Profit", "GrossProfit")
        op_inc   = g(income, "Operating Income", "OperatingIncome", "Ebit")
        cfo      = g(cashflow, "Operating Cash Flow", "OperatingCashflow",
                     "Total Cash From Operating Activities")
        capex    = g(cashflow, "Capital Expenditure", "CapitalExpenditures",
                     "Purchases Of Property Plant And Equipment")
        ar       = g(balance, "Accounts Receivable", "Net Receivables")
        total_d  = g(balance, "Total Debt", "Long Term Debt")
        equity   = g(balance, "Stockholders Equity", "Total Stockholder Equity",
                     "Common Stock Equity")

        fcf = None
        if cfo is not None and capex is not None:
            fcf = cfo + capex  # capex is usually negative

        gross_m = (gross_p / revenue) if (gross_p and revenue) else None
        op_m    = (op_inc / revenue)  if (op_inc  and revenue) else None
        net_m   = (net_inc / revenue) if (net_inc  and revenue) else None
        cfo_ni  = (cfo / net_inc)     if (cfo and net_inc and net_inc != 0) else None
        de      = (total_d / equity)  if (total_d and equity and equity != 0) else None

        period = str(col.date()) if hasattr(col, "date") else str(col)
        out.append({
            "period": period,
            "revenue": revenue,
            "net_income": net_inc,
            "gross_profit": gross_p,
            "operating_income": op_inc,
            "cfo": cfo,
            "capex": capex,
            "fcf": fcf,
            "accounts_receivable": ar,
            "total_debt": total_d,
            "equity": equity,
            "gross_margin": gross_m,
            "operating_margin": op_m,
            "net_margin": net_m,
            "cfo_ni_ratio": cfo_ni,
            "debt_equity": de,
        })
    return out


def _build_ttm(income: pd.DataFrame, cashflow: pd.DataFrame,
               balance: pd.DataFrame) -> dict:
    """Sum last 4 quarters for flow statements; last quarter for balance sheet."""
    def ttm_sum(df, *keys):
        s = _row(df, *keys)
        if s.empty:
            return None
        vals = [_safe_float(v) for v in s.iloc[:4]]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None

    def latest(df, *keys):
        s = _row(df, *keys)
        if s.empty or len(s) == 0:
            return None
        return _safe_float(s.iloc[0])

    revenue = ttm_sum(income, "Total Revenue", "TotalRevenue")
    net_inc = ttm_sum(income, "Net Income", "NetIncome")
    gross_p = ttm_sum(income, "Gross Profit", "GrossProfit")
    op_inc  = ttm_sum(income, "Operating Income", "OperatingIncome", "Ebit")
    cfo     = ttm_sum(cashflow, "Operating Cash Flow", "OperatingCashflow",
                      "Total Cash From Operating Activities")
    capex   = ttm_sum(cashflow, "Capital Expenditure", "CapitalExpenditures")
    equity  = latest(balance, "Stockholders Equity", "Total Stockholder Equity")
    total_d = latest(balance, "Total Debt", "Long Term Debt")

    fcf = (cfo + capex) if (cfo and capex) else None
    gross_m = (gross_p / revenue) if (gross_p and revenue) else None
    op_m    = (op_inc / revenue)  if (op_inc  and revenue) else None
    net_m   = (net_inc / revenue) if (net_inc  and revenue) else None
    cfo_ni  = (cfo / net_inc)     if (cfo and net_inc and net_inc != 0) else None
    de      = (total_d / equity)  if (total_d and equity and equity != 0) else None

    return {
        "period": "TTM",
        "revenue": revenue,
        "net_income": net_inc,
        "gross_profit": gross_p,
        "operating_income": op_inc,
        "cfo": cfo,
        "capex": capex,
        "fcf": fcf,
        "gross_margin": gross_m,
        "operating_margin": op_m,
        "net_margin": net_m,
        "cfo_ni_ratio": cfo_ni,
        "debt_equity": de,
    }


def _build_ratios(info: dict, quarters: list[dict], ttm: dict) -> dict:
    roe = _safe_float(info.get("returnOnEquity"))
    roa = _safe_float(info.get("returnOnAssets"))
    cr  = _safe_float(info.get("currentRatio"))

    # AR growth vs revenue growth (quality signal for earnings manipulation)
    ar_growth = None
    rev_growth = None
    if len(quarters) >= 5:
        q0, q4 = quarters[0], quarters[4]
        if q0["accounts_receivable"] and q4["accounts_receivable"] and q4["accounts_receivable"] != 0:
            ar_growth = (q0["accounts_receivable"] - q4["accounts_receivable"]) / abs(q4["accounts_receivable"])
        if q0["revenue"] and q4["revenue"] and q4["revenue"] != 0:
            rev_growth = (q0["revenue"] - q4["revenue"]) / abs(q4["revenue"])

    return {
        "roe": roe,
        "roa": roa,
        "current_ratio": cr,
        "pe_ratio": _safe_float(info.get("trailingPE")),
        "pb_ratio": _safe_float(info.get("priceToBook")),
        "ev_ebitda": _safe_float(info.get("enterpriseToEbitda")),
        "ar_growth_yoy": ar_growth,
        "revenue_growth_yoy": rev_growth,
        "ar_rev_divergence": (ar_growth - rev_growth)
            if (ar_growth is not None and rev_growth is not None) else None,
    }


def _price_metrics(info: dict) -> dict:
    return {
        "price": _safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
        "52w_high": _safe_float(info.get("fiftyTwoWeekHigh")),
        "52w_low":  _safe_float(info.get("fiftyTwoWeekLow")),
        "beta": _safe_float(info.get("beta")),
        "analyst_target": _safe_float(info.get("targetMeanPrice")),
        "analyst_rating": info.get("recommendationKey", "N/A"),
    }
