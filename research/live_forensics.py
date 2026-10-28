"""
Live forensics: replay the live scanner day by day since the tracking reset
(2026-10-08) and compare with the real paper ledger, then diagnose every fired
trade (regime, entry timing, stop width, MFE/MAE, funding, correlation).

Ground truth: the nightly `track-export` artifact of .github/workflows/track-admin.yml
(track_export.json: every trigger row incl. fired/outcome). Download the newest
one (repo is public; artifacts need a GitHub login) and pass it with --ledger.

Data: the live path on a US host. Bybit is geo blocked, so utils/exchange.py takes
the saved data/bybit_perps.json list and pulls MEXC PERP candles (same coin,
1000x prefixes mapped). This script uses that exact code path (utils.exchange,
with the proxy injected into ccxt) so prices match what the monitor saw.

Replay rules (as live, per scan slot 19:50 / 00:05 / 04:00 UTC):
  * daily candles up to the slot, the last one still FORMING (built from 1h bars),
    exactly like a live 400 bar fetch; skills.new_setups.detect on CLOSED bars
    (latest() drops the forming candle), skills.scanner.classify_setup on the
    forming candle (live does not drop it: see BUGS in docs/edge_fix/forensics.md);
  * edge gate = data/crypto_validation.json "validated", minus decayed setups;
  * long gate = BTC above 200d and 50d (forming close) and alt breadth >= 60%;
  * funding crowding, held coins, MAX_OPEN_POSITIONS, top_n, _diversify, the
    25% stop cap (50% for Distribution Short from 2026-10-25 08:15 UTC);
  * enter_now_short fires on the next 15 min poll, breakout_long when the live
    price reaches the level (1h bars), triggers cancelled by the next scan;
  * paper exits with triggers.outcomes._simulate (unchanged, imported).

Usage:
  python research/live_forensics.py fetch                 # candles -> cache
  python research/live_forensics.py replay --ledger track_export.json
  python research/live_forensics.py diagnose --ledger track_export.json
Cache: $FORENSICS_CACHE (default /tmp/live_forensics_cache).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pickle
import sys
import types
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if "yfinance" not in sys.modules:            # scanner imports it at module top (stocks only)
    sys.modules["yfinance"] = types.ModuleType("yfinance")

CACHE = Path(os.environ.get("FORENSICS_CACHE", "/tmp/live_forensics_cache"))
START = pd.Timestamp("2026-10-08")
DS_WIDE_FROM = pd.Timestamp("2026-10-25 08:15")      # commit 57f1676, 19:15 AEDT
# The exported table starts at trigger id 450 (10 Oct 19:51): ids 1 to 449 are gone
# (table wiped/restored), so the comparable window starts at that scan.
REPLAY_FROM = pd.Timestamp("2026-10-10 19:00")
# data/crypto_validation.json: Distribution Short "Approved 18 Oct 2026" (manual
# note); before that its last computed run (PF 0.225, n 62) kept it off the
# validated list. The ledger agrees: no DS armed before 24 Oct although the
# detector fired on GIGGLE (13 Oct), TRX (15 Oct) and XMR (12 Oct).
DS_APPROVED = pd.Timestamp("2026-10-18 00:00")
SLOTS_UTC = [(19, 50), (0, 5), (4, 0)]                # morning 06:50 AEDT, close, arvo 15:00 AEDT


# ── data ─────────────────────────────────────────────────────────────────────
def _patch_exchange():
    """utils.exchange with the sandbox proxy injected into every ccxt client."""
    from utils import exchange as ex
    import ccxt
    proxy = os.environ.get("HTTPS_PROXY")

    def _client(name, *, swap=False):
        key = f"{name}:{'swap' if swap else 'spot'}"
        if key in ex._clients:
            return ex._clients[key]
        opts = {"enableRateLimit": True, "timeout": 20000}
        if proxy:
            opts["httpsProxy"] = proxy
        if swap:
            opts["options"] = {"defaultType": "swap"}
        c = getattr(ccxt, name)(opts)
        ex._clients[key] = c
        return c
    ex._client = _client
    return ex


def universe() -> list[str]:
    return json.loads((ROOT / "data" / "bybit_perps.json").read_text())["symbols"]


def fetch(symbols: list[str] | None = None, d_limit: int = 500, h_limit: int = 1000) -> None:
    ex = _patch_exchange()
    CACHE.mkdir(parents=True, exist_ok=True)
    syms = symbols or universe()
    for tf, lim in (("1d", d_limit), ("1h", h_limit)):
        path = CACHE / f"ohlcv_{tf}.pkl"
        have = pickle.loads(path.read_bytes()) if path.exists() else {}
        todo = [s for s in syms if s not in have]
        print(f"{tf}: {len(have)} cached, fetching {len(todo)}", flush=True)
        for i in range(0, len(todo), 40):
            got = ex.get_ohlcv_batch(todo[i:i + 40], timeframe=tf, limit=lim, exchange="bybit")
            have.update(got)
            path.write_bytes(pickle.dumps(have))
            print(f"  {tf} {i + 40}/{len(todo)} -> {len(have)}", flush=True)


def load_cache() -> tuple[dict, dict]:
    d = pickle.loads((CACHE / "ohlcv_1d.pkl").read_bytes())
    h = pickle.loads((CACHE / "ohlcv_1h.pkl").read_bytes())
    return d, h


def slots(start: pd.Timestamp = START, end: pd.Timestamp | None = None) -> list[pd.Timestamp]:
    end = end or pd.Timestamp.utcnow().tz_localize(None)
    out = []
    day = start.normalize()
    while day <= end:
        for hh, mm in SLOTS_UTC:
            t = day + pd.Timedelta(hours=hh, minutes=mm)
            if max(start, REPLAY_FROM) <= t <= end:
                out.append(t)
        day += pd.Timedelta(days=1)
    return sorted(out)


def forming_df(d1: pd.DataFrame, h1: pd.DataFrame | None, t: pd.Timestamp,
               limit: int = 400) -> pd.DataFrame | None:
    """Daily candles as a live fetch at time t returns them: closed bars plus the
    still forming bar of t's UTC day (built from the complete 1h bars before t;
    the open of the current hour stands in for the last price)."""
    day = t.normalize()
    closed = d1[d1.index < day]
    if closed.empty:
        return None
    row = None
    if h1 is not None and not h1.empty:
        w = h1[(h1.index >= day) & (h1.index < t)]
        if not w.empty:
            done = w[w.index + pd.Timedelta(hours=1) <= t]
            cur = w[w.index + pd.Timedelta(hours=1) > t]
            last = float(cur["open"].iloc[0]) if not cur.empty else float(w["close"].iloc[-1])
            hi = max([last] + list(done["high"])) if not done.empty else last
            lo = min([last] + list(done["low"])) if not done.empty else last
            vol = float(done["volume"].sum()) if not done.empty else 0.0
            row = {"open": float(w["open"].iloc[0]), "high": hi, "low": lo, "close": last,
                   "volume": vol}
    if row is None:
        if day in d1.index and (h1 is None or h1.empty or h1.index[-1] < day):
            return None                      # no intraday data to build the bar
        pc = float(closed["close"].iloc[-1])
        row = {"open": pc, "high": pc, "low": pc, "close": pc, "volume": 0.0}
    out = pd.concat([closed, pd.DataFrame([row], index=[day])])
    return out.iloc[-limit:]


def price_at(h1: pd.DataFrame | None, t: pd.Timestamp) -> float | None:
    """Last price at t from 1h bars: open of the hour that contains t."""
    if h1 is None or h1.empty:
        return None
    w = h1[h1.index <= t]
    if w.empty:
        return None
    bar = w.iloc[-1]
    if w.index[-1] + pd.Timedelta(hours=1) <= t:
        return float(bar["close"])
    return float(bar["open"])


# ── fake trigger store (in memory; replaces triggers.db during the replay) ───
class FakeDB:
    def __init__(self, track_from: str):
        self.rows: list[dict] = []
        self.deactivated: set[str] = set()
        self.state = {"track_from": track_from}
        self.now: pd.Timestamp = START

    # functions scan.py / outcomes.py call
    def get_deactivated(self):
        return set(self.deactivated)

    def get_fired_trades(self, open_only: bool = False):
        out = [r for r in self.rows if r["status"] == "fired"]
        if open_only:
            out = [r for r in out if not r.get("_closed_by") or r["_closed_by"] > self.now]
        return sorted(out, key=lambda r: r["fired_at"])

    def get_state(self, k):
        return self.state.get(k)

    def clear_active(self):
        n = 0
        for r in self.rows:
            if r["status"] == "active":
                r["status"] = "cancelled"
                n += 1
        return n

    def add_trigger(self, symbol, condition_type, condition_value, **kw):
        r = {"id": len(self.rows) + 1, "symbol": symbol, "condition_type": condition_type,
             "condition_value": condition_value, "status": "active",
             "created_at": self.now.isoformat(), "fired_at": None, "fired_price": None,
             "taken": False, **kw}
        self.rows.append(r)
        return r["id"]


# ── the replay ───────────────────────────────────────────────────────────────
class Replay:
    """Drives the production scan code (skills.scanner._run_from_bybit and
    triggers.scan.run_scan_and_arm, unchanged) on reconstructed candles."""

    def __init__(self, d: dict, h: dict, funding: dict | None = None,
                 era: str = "ledger", ledger_kept: set | None = None):
        import config
        from skills import new_setups, scanner
        from triggers import db as tdb, scan, outcomes
        from utils import btc_regime, breadth, exchange as ex
        self.config, self.ns, self.scanner = config, new_setups, scanner
        self.tdb, self.scan, self.outcomes = tdb, scan, outcomes
        self.btc_regime, self.breadth, self.ex = btc_regime, breadth, ex
        self.d, self.h = d, h
        self.funding = funding or {}
        self.era = era
        self.ledger_kept = ledger_kept or set()
        self.db = FakeDB("2026-10-08T11:17:37.855588")
        self.syms = [s for s in universe() if s in d]
        self.btc_now: pd.Series | None = None
        self.today: pd.Timestamp = START
        self._ns_cache: dict = {}
        self.log: list[dict] = []
        self.scan_rows: dict = {}
        self.short_rows: dict = {}
        self._patch()

    # patches: every external read the production code makes is answered from
    # the replay clock instead of the network or Supabase
    def _patch(self):
        R = self
        for name in ("get_deactivated", "get_fired_trades", "get_state", "clear_active",
                     "add_trigger"):
            setattr(self.tdb, name, getattr(self.db, name))
        def _scan(tickers=None, criteria=None, regime_score=None, exchange=None):
            R.last_df = R.scanner._run_from_bybit(R.frames, tickers, criteria, regime_score)
            return R.last_df
        self.scan.run_crypto_scan = _scan
        from backtesting import crypto_validation as cv
        orig_valid = cv.validated_labels

        def validated():
            v = orig_valid()
            if v is not None and self.era == "ledger" and R.db.now < DS_APPROVED:
                v = v - {"Distribution Short"}
            return v
        cv.validated_labels = validated
        self.ex.list_perp_symbols = lambda exchange="mexc", quote="USDT": list(R.syms)
        self.scan._xch.get_funding_rates = lambda syms: {s: R.funding_at(s) for s in syms
                                                         if R.funding_at(s) is not None}
        self.btc_regime.btc_return = lambda days=30, force=False: (
            float((R.btc_now.iloc[-1] / R.btc_now.iloc[-1 - days] - 1) * 100))
        self.btc_regime.btc_daily_close = lambda force=False: R.btc_now
        self.breadth.long_gate = lambda: R.long_gate()
        orig_detect = self.ns.detect

        def latest(df, btc_close):
            if df is None or len(df) < 206:
                return None
            if pd.Timestamp(df.index[-1]).normalize() >= R.today:
                df = df.iloc[:-1]
            key = (str(df.index[0]), str(df.index[-1]), len(df), float(df["close"].iloc[-1]),
                   float(df["close"].sum()))
            if key not in R._ns_cache:
                R._ns_cache[key] = orig_detect(df, btc_close).iloc[-1]
            row = R._ns_cache[key]
            if not row["label"]:
                return None
            return {"label": row["label"], "stop": float(row["stop"]),
                    "target": None if pd.isna(row["target"]) else float(row["target"]),
                    "trail_atr": None if pd.isna(row["trail_atr"]) else float(row["trail_atr"]),
                    "max_hold": int(row["max_hold"]), "atr": float(row["atr"])}
        self.ns.latest = latest

    def funding_at(self, sym: str) -> float | None:
        s = self.funding.get(sym)
        if s is None or s.empty:
            return None
        w = s[s.index <= self.db.now]
        return float(w.iloc[-1]) if not w.empty else None

    def long_gate(self) -> tuple[bool, str]:
        c = self.btc_now
        if c is None or len(c) < 205:
            return True, ""
        if c.iloc[-1] <= c.iloc[-200:].mean():
            return False, "Bitcoin below its 200-day average"
        if c.iloc[-1] <= c.iloc[-50:].mean():
            return False, "Bitcoin below its 50-day average"
        b = self.breadth_at()
        if b is not None and b < self.config.ALT_BREADTH_MIN:
            return False, f"only {b:.0f}% of altcoins above their 50-day"
        return True, ""

    def breadth_at(self) -> float | None:
        uni = set(json.loads((ROOT / "data" / "breadth_universe.json").read_text())["symbols"])
        above = n = 0
        for s, df in self.frames.items():
            if s in uni and len(df) >= 50:
                n += 1
                above += df["close"].iloc[-1] > df["close"].iloc[-50:].mean()
        return above / n * 100 if n >= 60 else None

    def era_params(self, t: pd.Timestamp) -> dict:
        """Live config at time t. The repo history starts at 57f1676 (25 Oct), so
        the earlier config is inferred from the ledger: until the 12 Oct 19:51
        scan, scans armed up to 14 with no concurrent cap (~15 per scan); from
        then on top_n 5 and MAX_OPEN_POSITIONS 10 (and the one off 'over_cap'
        clean up of everything else that was open)."""
        p = {"top_n": 5, "cap": True, "ds_wide": t >= DS_WIDE_FROM}
        if self.era == "ledger" and t < pd.Timestamp("2026-10-12 12:00"):
            p.update(top_n=14, cap=False)
        return p

    def run(self, end: pd.Timestamp | None = None) -> list[dict]:
        sl = slots(end=end)
        swapped = False
        for i, t in enumerate(sl):
            nxt = sl[i + 1] if i + 1 < len(sl) else (end or pd.Timestamp.utcnow().tz_localize(None))
            p = self.era_params(t)
            if self.era == "ledger" and not swapped and p["cap"]:
                swapped = True
                self._over_cap(t)
            self.scan_once(t, p)
            self.monitor(t, nxt)
        return self.db.rows

    def _over_cap(self, t: pd.Timestamp):
        """Copy the ledger's one off clean up: open paper trades it did not keep
        are set aside (status over_cap) and stop counting."""
        self.db.now = t
        for r in self.db.get_fired_trades(open_only=True):
            if (r["symbol"], r["setup_label"]) not in self.ledger_kept:
                r["status"] = "over_cap"

    def scan_once(self, t: pd.Timestamp, p: dict):
        self.db.now = t
        self.today = t.normalize()
        frames = {}
        for s in self.syms:
            f = forming_df(self.d[s], self.h.get(s), t)
            if f is not None and len(f) >= 63:
                frames[s] = f
        self.frames = frames
        self.btc_now = frames["BTC-USD"]["close"] if "BTC-USD" in frames else None
        self.config.MAX_STOP_PCT_BY_SETUP.clear()
        if p["ds_wide"]:
            self.config.MAX_STOP_PCT_BY_SETUP["Distribution Short"] = 50.0
        self.config.MAX_OPEN_POSITIONS = 10 if p["cap"] else 10_000
        top_n = p["top_n"]
        res = self.scan.run_scan_and_arm(
            universe_size=100, top_n=top_n, regime_score=None, expiry_hours=72,
            min_vol_usd_m=0.5, source="bybit_perps", max_per_setup=max(2, top_n // 3),
            max_stop_pct=25.0)
        cands = res.get("candidates") or []
        armed_syms = {a["symbol"] for a in res.get("armed") or []}
        wide = {w.split(" ")[0] for w in res.get("wide_stop_excluded") or []}
        held = set(res.get("held_excluded") or [])
        shorts = []
        if getattr(self, "last_df", None) is not None and not self.last_df.empty:
            from backtesting import crypto_validation as cv
            ok = (cv.validated_labels() or set()) - self.db.deactivated
            for r in self.last_df.to_dict("records"):
                if (r.get("trade") or {}).get("action") != "SELL":
                    continue
                st = ("armed" if r["ticker"] in armed_syms else "held" if r["ticker"] in held
                      else "not_validated" if r["setup_label"] not in ok
                      else "wide_stop" if r["ticker"] in wide else "eligible_not_armed")
                plan = self.scan._armed_plan(dict(r, direction="short"))
                shorts.append({"ticker": r["ticker"], "setup": r["setup_label"], "status": st,
                               "price": r["price"], "stop_pct": plan.get("stop_pct"),
                               "conv": r.get("conviction")})
        self.short_rows[t] = shorts
        self.scan_rows[t] = [{"ticker": r["ticker"], "setup": r.get("setup_label"),
                              "dir": r.get("direction"), "status": r.get("_status"),
                              "conv": r.get("conviction"), "price": r.get("price"),
                              "stop_pct": (r.get("_plan") or {}).get("stop_pct")}
                             for r in cands]
        self.log.append({"t": t, "valid": len(cands), "armed": len(res.get("armed") or []),
                         "long_gate": not res.get("btc_below_200d"),
                         "gate_reason": res.get("long_gate_reason"),
                         "open": res.get("open_positions"),
                         "wide": res.get("wide_stop_excluded"),
                         "crowded": res.get("crowded_excluded"),
                         "watch": [(w["ticker"], w["setup_label"]) for w in res.get("watch_only", [])
                                   if w.get("setup_label") in {"Distribution Short",
                                                               "Downtrend Bounce Fade",
                                                               "Breakdown Short (55d low)"}]})

    # monitor: 15 min polls between this scan and the next (the next scan
    # cancels whatever is still armed)
    def monitor(self, t: pd.Timestamp, nxt: pd.Timestamp):
        import monitor as mon
        from utils import overext
        active = [r for r in self.db.rows if r["status"] == "active"]
        if not active:
            return
        gate_ok = self.long_gate()[0]
        polls = [t + pd.Timedelta(minutes=1) + pd.Timedelta(minutes=15 * k)
                 for k in range(int((nxt - t) / pd.Timedelta(minutes=15)) + 1)]
        polls = [p for p in polls if p < nxt]
        for r in active:
            h1 = self.h.get(r["symbol"])
            for p in polls:
                px = price_at(h1, p)
                if px is None:
                    break
                ind = {"price": px, "prev": px, "rsi2_now": 50.0, "rsi2_prev": 50.0,
                       "rsi14_now": 50.0, "mean20": px}
                cond = json.loads(r["condition_json"])
                if cond.get("kind") in ("breakout", "breakdown", "mr_reversal",
                                        "mr_reversal_short"):
                    f = forming_df(self.d[r["symbol"]], h1, p)
                    if f is None:
                        continue
                    f.iloc[-1, f.columns.get_loc("close")] = px
                    got = mon._indicators(f)
                    if got is None:
                        continue
                    ind = got
                verdict, why = mon._evaluate(r, ind)
                if verdict == "invalidate":
                    r["status"], r["_why"] = "invalidated", why
                    break
                if verdict != "fire":
                    continue
                if (r.get("direction") or "long") == "long":
                    if not gate_ok:
                        continue                       # long gate veto at fire time
                    mx = overext.measure(r["symbol"], h1[h1.index <= p])
                    if mx and mx["overextended"]:
                        r["status"] = "too_extended"
                        break
                r.update(status="fired", fired_at=p.isoformat(), fired_price=px, _why=why)
                self._track(r)
                break

    def _track(self, r: dict):
        """Paper outcome with the production exit logic (outcomes._simulate)."""
        sym = r["symbol"]
        fired = pd.Timestamp(r["fired_at"])
        h1 = self.h.get(sym)
        h1s = h1[h1.index >= fired.normalize()] if h1 is not None else None
        d1 = self.d[sym]
        patch = self.outcomes._simulate(r, d1, h1s)
        r.update(patch or {})
        r["_closed_by"] = None
        if patch and patch.get("outcome"):
            r["_closed_by"] = close_time(r, patch, h1)


def close_time(r: dict, patch: dict, h1: pd.DataFrame | None) -> pd.Timestamp:
    """When the live monitor would have seen the exit (first 1h bar through it)."""
    ts = pd.Timestamp(patch["exit_at"])
    if patch["outcome"] == "time":
        return ts.normalize() + pd.Timedelta(days=1, minutes=15)
    fired = pd.Timestamp(r["fired_at"])
    if h1 is not None:
        w = h1[(h1.index >= max(fired.floor("h"), ts.normalize()))]
        px, short = patch["exit_price"], r.get("direction") == "short"
        hit = w[(w["high"] >= px * 0.9999)] if (short != (patch["outcome"] == "target")) \
            else w[(w["low"] <= px * 1.0001)]
        if not hit.empty:
            return hit.index[0] + pd.Timedelta(minutes=30)
    return ts.normalize() + pd.Timedelta(hours=12)


# ── ledger comparison ────────────────────────────────────────────────────────
def load_ledger(path: str) -> pd.DataFrame:
    d = json.loads(Path(path).read_text())
    df = pd.DataFrame(d["triggers"])
    df = df[df["created_at"] >= d["track_from"]]
    return df


def _scan_key(ts) -> pd.Timestamp:
    """Map a created_at to its scan slot (nearest slot within 40 minutes)."""
    t = pd.Timestamp(ts)
    for hh, mm in SLOTS_UTC:
        for day in (t.normalize(), t.normalize() - pd.Timedelta(days=1)):
            s = day + pd.Timedelta(hours=hh, minutes=mm)
            if abs((t - s).total_seconds()) <= 40 * 60:
                return s
    return t.floor("h")


def compare(rows: list[dict], led: pd.DataFrame) -> dict:
    rep = pd.DataFrame(rows)
    rep["slot"] = rep["created_at"].map(_scan_key)
    led = led.copy()
    led["slot"] = led["created_at"].map(_scan_key)
    A = {(s, x, y) for s, x, y in zip(led.slot, led.symbol, led.setup_label)}
    B = {(s, x, y) for s, x, y in zip(rep.slot, rep.symbol, rep.setup_label)}
    Afire = {(x, y) for x, y, st in zip(led.symbol, led.setup_label, led.status)
             if st in ("fired", "over_cap")}
    Bfire = {(x, y) for x, y, f in zip(rep.symbol, rep.setup_label, rep.fired_at) if f}
    Acount = {(x, y) for x, y, st in zip(led.symbol, led.setup_label, led.status) if st == "fired"}
    Bcount = {(x, y) for x, y, st in zip(rep.symbol, rep.setup_label, rep.status) if st == "fired"}
    return {"armed_ledger": len(A), "armed_replay": len(B), "armed_both": len(A & B),
            "armed_only_ledger": sorted(A - B, key=str), "armed_only_replay": sorted(B - A, key=str),
            "fired_ledger": len(Afire), "fired_replay": len(Bfire), "fired_both": len(Afire & Bfire),
            "fired_only_ledger": sorted(Afire - Bfire), "fired_only_replay": sorted(Bfire - Afire),
            "counted_ledger": sorted(Acount), "counted_replay": sorted(Bcount),
            "counted_both": sorted(Acount & Bcount)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "funding", "replay", "diagnose"])
    ap.add_argument("--ledger", default=str(CACHE / "track_export.json"))
    ap.add_argument("--era", default="ledger", choices=["ledger", "current"])
    ap.add_argument("--end", default=None)
    a = ap.parse_args()
    if a.cmd in ("replay", "diagnose"):
        import logging
        logging.disable(logging.INFO)
    if a.cmd == "fetch":
        return fetch()
    if a.cmd == "funding":
        return fetch_funding()
    led = load_ledger(a.ledger)
    d, h = load_cache()
    fpath = CACHE / "funding.pkl"
    funding = pickle.loads(fpath.read_bytes()) if fpath.exists() else {}
    if a.cmd == "replay":
        kept = {(x, y) for x, y, st in zip(led.symbol, led.setup_label, led.status) if st == "fired"}
        rp = Replay(d, h, funding=funding, era=a.era, ledger_kept=kept)
        rows = rp.run(end=pd.Timestamp(a.end) if a.end else None)
        out = CACHE / f"replay_{a.era}.pkl"
        out.write_bytes(pickle.dumps({"rows": rows, "log": rp.log, "scan_rows": rp.scan_rows,
                                      "short_rows": rp.short_rows}))
        cmp_ = compare(rows, led)
        (CACHE / f"compare_{a.era}.json").write_text(json.dumps(cmp_, indent=1, default=str))
        summarize(rows, rp.log, led)
        return None
    if a.cmd == "diagnose":
        return diagnose(led, d, h, funding)


def _stats(rs: list[float]) -> dict:
    g, l = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return {"n": len(rs), "win": (sum(r > 0 for r in rs) / len(rs)) if rs else None,
            "total_r": round(sum(rs), 3), "pf": (g / l) if l else None}


def summarize(rows: list[dict], log: list[dict], led: pd.DataFrame) -> None:
    rep = pd.DataFrame(rows)
    f = rep[rep["status"] == "fired"].sort_values("fired_at")
    cols = ["symbol", "setup_label", "direction", "created_at", "fired_at", "fired_price",
            "stop", "outcome", "r_multiple", "bars_held"]
    print("REPLAY counted trades (status fired):")
    print(f[[c for c in cols if c in f]].to_string())
    closed = [r for r in f["r_multiple"] if pd.notna(r)]
    print("replay closed:", _stats(closed), " open:", int(f["r_multiple"].isna().sum()))
    lf = led[led["status"] == "fired"]
    print("ledger closed:", _stats([r for r in lf["r_multiple"] if pd.notna(r)]),
          " open:", int(lf["r_multiple"].isna().sum()))
    print("\nscan log (slot, valid, armed, long gate, open, wide stop skips, crowded):")
    for x in log:
        print(f"{x['t']:%m-%d %H:%M} valid {x['valid']:3d} armed {x['armed']:2d} "
              f"gate {'open' if x['long_gate'] else 'CLOSED'} open {x['open']} "
              f"wide {x['wide'] or ''} crowded {x['crowded'] or ''}")


def fetch_funding(since: str = "2026-10-01") -> None:
    """Funding history from the venue the live chain actually reaches from a US
    host (binance and bybit refuse it, so get_funding_rate ends up on OKX).
    Coins OKX does not list have no funding live either (never vetoed)."""
    import ccxt
    ok = ccxt.okx({"enableRateLimit": True, "httpsProxy": os.environ.get("HTTPS_PROXY"),
                   "options": {"defaultType": "swap"}})
    mk = ok.load_markets()
    t0 = int(pd.Timestamp(since).timestamp() * 1000)
    out = {}
    for s in universe():
        sym = s[:-4] + "/USDT:USDT"
        if sym not in mk:
            continue
        rows, cur = [], t0
        for _ in range(6):
            try:
                got = ok.fetch_funding_rate_history(sym, since=cur, limit=100)
            except Exception as exc:                      # noqa: BLE001
                print("funding", s, exc)
                break
            if not got:
                break
            rows += got
            cur = got[-1]["timestamp"] + 1
            if len(got) < 100:
                break
        if rows:
            ser = pd.Series({pd.Timestamp(r["timestamp"], unit="ms"): float(r["fundingRate"])
                             for r in rows}).sort_index()
            out[s] = ser
    (CACHE / "funding.pkl").write_bytes(pickle.dumps(out))
    print("funding series:", len(out))


def _ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def _resample(h1: pd.DataFrame, rule: str) -> pd.DataFrame:
    return h1.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


def btc_regime_at(d: dict, h: dict, t: pd.Timestamp) -> dict:
    """BTC trend on 1h / 4h (closed bars: close vs EMA20 and EMA50), 1d (closed
    close vs SMA50/200 = new_setups.btc_trend), returns, and alt breadth."""
    from skills.new_setups import btc_trend
    b1 = h["BTC-USD"][h["BTC-USD"].index + pd.Timedelta(hours=1) <= t]
    b4 = _resample(b1, "4h")
    b4 = b4[b4.index + pd.Timedelta(hours=4) <= t]
    dd = d["BTC-USD"][d["BTC-USD"].index < t.normalize()]

    def lab(x):
        c, e20, e50 = x["close"].iloc[-1], _ema(x["close"], 20).iloc[-1], _ema(x["close"], 50).iloc[-1]
        return "UP" if c > e20 > e50 else ("DOWN" if c < e20 < e50 else "MIXED")
    uni = set(json.loads((ROOT / "data" / "breadth_universe.json").read_text())["symbols"])
    above = n = 0
    for s_, df in d.items():
        if s_ in uni:
            c = df["close"][df.index < t.normalize()]
            if len(c) >= 50:
                n += 1
                above += c.iloc[-1] > c.iloc[-50:].mean()
    px = float(b1["close"].iloc[-1])
    return {"btc_1h": lab(b1), "btc_4h": lab(b4), "btc_1d": btc_trend(dd["close"]).iloc[-1],
            "btc_vs50d": px / dd["close"].iloc[-50:].mean() - 1,
            "btc_ret24h": px / float(b1["close"].iloc[-25]) - 1,
            "btc_ret7d": px / float(b1["close"].iloc[-169]) - 1,
            "breadth50": above / n * 100 if n else None, "btc_px": px}


def trade_path(t: dict, h1: pd.DataFrame, end: pd.Timestamp) -> dict:
    """MFE / MAE in R from 1h bars between the fire and the exit (or now)."""
    fired = pd.Timestamp(t["fired_at"])
    e, s0 = float(t["fired_price"]), float(t["stop"])
    risk = abs(e - s0)
    short = t["direction"] == "short"
    w = h1[(h1.index + pd.Timedelta(hours=1) > fired) & (h1.index <= end)]
    if w.empty:
        return {}
    fav = (e - w["low"]) if short else (w["high"] - e)
    adv = (w["high"] - e) if short else (e - w["low"])
    mfe_t = fav.idxmax()
    out = {"mfe_r": float(fav.max() / risk), "mae_r": float(adv.max() / risk),
           "hrs_to_mfe": (mfe_t - fired).total_seconds() / 3600,
           "mae_before_mfe_r": float(adv[:mfe_t].max() / risk),
           "hours": (end - fired).total_seconds() / 3600}
    for hrs in (24, 72):
        ww = w[w.index < fired + pd.Timedelta(hours=hrs)]
        f2 = (e - ww["low"]) if short else (ww["high"] - e)
        out[f"mfe_{hrs}h_r"] = float(f2.max() / risk) if len(ww) else None
    last = float(w["close"].iloc[-1])
    out["mark_r"] = ((e - last) if short else (last - e)) / risk
    return out


def backtest_exit_r(t: dict, d1: pd.DataFrame, atr: float) -> dict:
    """The exit the research simulated (crypto_optimize._simulate_plan for the
    new setups: stop fixed, trail = min(stop, close + k*ATR_entry) off the CLOSE,
    entry at the signal close) applied to the live entry, for comparison."""
    fired = pd.Timestamp(t["fired_at"]).normalize()
    e, stop = float(t["fired_price"]), float(t["stop"])
    risk = stop - e
    bars = d1[d1.index >= fired]
    for ts, b in bars.iterrows():
        if b["high"] >= stop:
            return {"bt_outcome": "stop" if stop == float(t["stop"]) else "trail",
                    "bt_r": (e - stop) / risk, "bt_exit": str(ts.date())}
        stop = min(stop, float(b["close"]) + 3.5 * atr)
    return {"bt_outcome": None, "bt_r": (e - float(bars["close"].iloc[-1])) / risk,
            "bt_trail": stop}


def diagnose(led, d, h, funding):
    from skills import new_setups
    from triggers import outcomes
    now = pd.Timestamp.now("UTC").tz_localize(None)
    fired = led[led["status"] == "fired"].sort_values("fired_at")
    rows = []
    for _, t in fired.iterrows():
        t = t.to_dict()
        sym = t["symbol"]
        d1, h1 = d[sym], h[sym]
        ft = pd.Timestamp(t["fired_at"])
        has_exit = isinstance(t.get("exit_at"), str)
        end = pd.Timestamp(t["exit_at"]) + pd.Timedelta(days=1) if has_exit else now
        if t.get("outcome") == "manual":
            end = pd.Timestamp(t["exit_at"])
        closed = d1[d1.index < ft.normalize()]
        x = new_setups._ind(closed)
        atr = float(x["atr"].iloc[-1])
        sig_close = float(closed["close"].iloc[-1])
        resim = outcomes._simulate(dict(t, target=None if pd.isna(t.get("target")) else t["target"]),
                                   d1, h1[h1.index >= ft.normalize()])
        fr = funding.get(sym)
        f_at = float(fr[fr.index <= ft].iloc[-1]) if fr is not None and (fr.index <= ft).any() else None
        f_avg7 = float(fr[(fr.index <= ft) & (fr.index > ft - pd.Timedelta(days=7))].mean()) \
            if fr is not None else None
        r = {"id": t["id"], "symbol": sym, "setup": t["setup_label"], "dir": t["direction"],
             "fired_at": t["fired_at"][:16], "entry": t["fired_price"], "scan_px": t["entry"],
             "sig_close": sig_close, "entry_vs_sigclose": t["fired_price"] / sig_close - 1,
             "stop_pct": abs(t["stop"] / t["fired_price"] - 1),
             "stop_atr": abs(t["stop"] - t["fired_price"]) / atr, "atr_pct": atr / sig_close,
             "outcome": t.get("outcome"), "r": t.get("r_multiple"), "bars": t.get("bars_held"),
             "taken": t.get("taken"),
             "resim_outcome": (resim or {}).get("outcome"), "resim_r": (resim or {}).get("r_multiple"),
             "funding_at_fire": f_at, "funding_7d_avg": f_avg7,
             "ret5d_before": sig_close / float(closed["close"].iloc[-6]) - 1,
             "ret30d_before": sig_close / float(closed["close"].iloc[-31]) - 1}
        r.update(btc_regime_at(d, h, ft))
        r.update(trade_path(t, h1, end))
        if t["direction"] == "short":
            r.update(backtest_exit_r(t, d1, atr))
        rows.append(r)
    df = pd.DataFrame(rows)
    out = CACHE / "diagnose.pkl"
    out.write_bytes(pickle.dumps(df))
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 60)
    print(df.T.to_string())
    return df


if __name__ == "__main__":
    main()
