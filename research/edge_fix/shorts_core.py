"""
Core for research/edge_fix_shorts.py: data panel, live short detectors, 1h exit
simulator. Data: research/edge_fix/shorts_fetch_binance_um.py (Binance USDT-M
perps incl. delisted, 1h klines + funding).

Detectors are the LIVE code where it exists:
  Distribution Short, Downtrend Bounce Fade   skills/new_setups.detect (unchanged)
  Breakdown Short (55d low)                   skills/scanner.classify_setup rule:
      close <= min(low of the prior 55 days), SMA50 < SMA200, close < SMA200,
      and NOT oversold (the Falling Knife guard returns first for oversold
      coins, see research/breakdown_broad.py), 20d turnover >= $0.5M.
Live scan filters applied on top: stop distance <= 25% (Distribution Short:
25% before 25 Oct 2026, 50% after), funding veto (no short when the last
funding print <= -0.05%), one open trade per coin per setup.

Exits are simulated on 1h bars (Bybit native stops/trails act intrabar):
stop checked first each hour (gap through the stop fills at the open), then
target, then the trail ratchets off the best low. Costs: 0.36% round trip
(taker + slippage, as backtesting/crypto_validation) plus funding actually
paid/received on Binance between entry and exit. A trade still open when a
DELISTED coin's data ends is closed at its last price (not dropped: dropping
it is survivorship bias). A trade still open on a live coin at the data end is
excluded and counted.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numba
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skills import new_setups as NS  # noqa: E402

COST = 0.0036
DATA_END_ALIVE = pd.Timestamp("2026-10-20")      # last bar after this = still listed
EXCLUDE_BASES = {"USDC", "BUSD", "TUSD", "USDP", "FDUSD", "USDE", "DAI", "BTCDOM", "DEFI",
                 "FOOTBALL", "BLUEBIRD", "XAU", "XAG", "XAUT", "PAXG", "EUR", "GBP", "AUD",
                 "USD1", "RLUSD", "TSLA", "NVDA", "AAPL", "MSTR", "COIN", "HOOD", "AMZN", "GOOGL",
                 "META", "MSFT", "SPY", "QQQ", "CRCL", "OPENAI", "INTC", "AMD", "PLTR", "XPT", "XPD"}
DS, DBF, BDS = "Distribution Short", "Downtrend Bounce Fade", "Breakdown Short (55d low)"

# FOMC statement days: federalreserve.gov/monetarypolicy/fomccalendars.htm (fetched 28 Oct 2026)
FOMC = ["2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21",
        "2022-11-02", "2022-12-14", "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
        "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13", "2024-01-31", "2024-03-20",
        "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17",
        "2025-10-29", "2025-12-10", "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-10-28"]
# US CPI release days (BLS schedule; bls.gov blocks this host so 2025-10 onward are from
# memory of the post shutdown schedule and may be off by a day).
CPI = ["2022-01-12", "2022-02-10", "2022-03-10", "2022-04-12", "2022-05-11", "2022-06-10",
       "2022-07-13", "2022-08-10", "2022-09-13", "2022-10-13", "2022-11-10", "2022-12-13",
       "2023-01-12", "2023-02-14", "2023-03-14", "2023-04-12", "2023-05-10", "2023-06-13",
       "2023-07-12", "2023-08-10", "2023-09-13", "2023-10-12", "2023-11-14", "2023-12-12",
       "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10", "2024-05-15", "2024-06-12",
       "2024-07-11", "2024-08-14", "2024-09-11", "2024-10-10", "2024-11-13", "2024-12-11",
       "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13", "2025-06-11",
       "2025-07-15", "2025-08-12", "2025-09-11", "2025-10-24", "2025-12-18", "2026-01-13",
       "2026-02-11", "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10", "2026-07-14",
       "2026-08-12", "2026-09-11", "2026-10-14"]
MACRO = pd.DatetimeIndex(sorted(set(FOMC) | set(CPI)))


def base_of(sym: str) -> str:
    return sym[:-4]


def load_1h(root: Path, sym: str) -> pd.DataFrame | None:
    p = root / "k1h" / f"{sym}.parquet"
    if not p.exists():
        return None
    k = pd.read_parquet(p)
    if len(k) < 24 * 60:
        return None
    k = k[~k.index.duplicated()].sort_index()
    # trim the dead tail of delisted contracts (flat price, zero volume)
    live = np.flatnonzero(k["volume"].values > 0)
    if len(live) == 0:
        return None
    k = k.iloc[:live[-1] + 1]
    return k


def load_funding(root: Path, sym: str, idx: pd.DatetimeIndex) -> tuple[np.ndarray, pd.Series]:
    """Cumulative funding aligned to the END of each 1h bar, plus the raw prints."""
    p = root / "fund" / f"{sym}.parquet"
    f = pd.read_parquet(p)["rate"] if p.exists() else pd.Series(dtype=float)
    if len(f):
        f.index = pd.DatetimeIndex(f.index).floor("h")
        f = f.groupby(level=0).sum()
    # a print at hh:00 is paid by positions held over that instant: credit it to the
    # bar that ENDS at hh:00, i.e. the bar opening at hh-1.
    else:
        f = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    per_bar = f.reindex(idx + pd.Timedelta(hours=1)).fillna(0.0).values
    return np.cumsum(per_bar), f


def daily_from_1h(k: pd.DataFrame) -> pd.DataFrame:
    d = k.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                              "volume": "sum", "quote_volume": "sum"}).dropna()
    return d


@numba.njit(cache=True)
def sim_short_1h(o, h, l, c, cumf, s, entry, stop, target, trail, be_r, max_bars, dead):
    """Short entered at `entry` before bar s. Returns (exit_idx, exit_px, code).
    code 0 stop, 1 trail, 2 target, 3 time, 4 delisted at data end, 5 open (exclude)."""
    n = len(c)
    risk = stop - entry
    st = stop
    best = entry
    moved = False
    for j in range(s, min(s + max_bars, n)):
        if o[j] >= st:
            return j, o[j], 1 if moved else 0
        if h[j] >= st:
            return j, st, 1 if moved else 0
        if not np.isnan(target) and l[j] <= target:
            return j, target, 2
        if l[j] < best:
            best = l[j]
        if not np.isnan(trail):
            ns = best + trail
            if ns < st:
                st = ns
                moved = True
        if not np.isnan(be_r) and entry - best >= be_r * risk and st > entry:
            st = entry
            moved = True
    if s + max_bars <= n:
        j = s + max_bars - 1
        return j, c[j], 3
    if dead:
        return n - 1, c[n - 1], 4
    return n - 1, c[n - 1], 5


def r_of(entry, stop, exit_px, cumf, i_entry_end, j_exit):
    """Net R for a short: price move - 0.36% round trip + funding received."""
    risk = stop - entry
    fund = cumf[j_exit] - (cumf[i_entry_end] if i_entry_end >= 0 else 0.0)
    return (entry - exit_px) / risk - COST * entry / risk + fund * entry / risk


def rsi(c: pd.Series, n: int) -> pd.Series:
    d = c.diff()
    g = d.clip(lower=0).ewm(com=n - 1, min_periods=n).mean()
    ls = (-d).clip(lower=0).ewm(com=n - 1, min_periods=n).mean()
    return 100 - 100 / (1 + g / ls)


def breakdown_signals(d: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = d["close"], d["high"], d["low"], d["volume"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    lo55 = l.rolling(55).min().shift(1)
    qv = (c * v).rolling(20).mean()
    r14, r2 = rsi(c, 14), rsi(c, 2)
    m20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    bbp = (c - (m20 - 2 * sd20)) / (4 * sd20)
    z = (c - m20) / sd20
    oversold = (r2 < 15) | (r14 < 30) | (bbp <= 0.05) | (z <= -2.0)
    sig = (c <= lo55) & (c < s200) & (s50 < s200) & (qv >= 0.5e6)
    return pd.DataFrame({"sig": sig.fillna(False), "oversold": oversold.fillna(False),
                         "atr": atr, "stop": c + 3.5 * atr, "qvol20": qv})
