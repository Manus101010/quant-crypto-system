"""
Trade flow: why the live system sends so few tradeable alerts.

Replays every scheduled scan of the last 30 days with the CURRENT branch code
(research/fix-live-edge: DS 2R take profit, restop at arm and fire, 3% up drift
bound, Breakdown Short retired, basket cap 3 per direction per Sydney day) on the
same reconstructed candles as research/live_forensics.py, and counts, per scan,
how many setups each gate removes:

  universe -> coins with data -> liquid (volume floor) -> setups detected (by type)
  -> long gate / decay deactivated / retired / not validated
  -> held coin / bad plan / drift at arm / stop cap / funding crowding
  -> open position cap / top_n + diversify -> armed
  -> invalidated before firing (drift, stop, re-anchored stop cap) / too extended /
     long gate at fire / cancelled unfired by the next scan -> fired
  -> basket cap (paper only) -> tradeable alert

Then: the base rate of Distribution Short and Downtrend Bounce Fade signals per week
in this regime from the survivor free shorts study panel (docs/edge_fix/shorts.md),
the frequency of the trader's discretionary "ran up hard and rolling over" pattern
on 1h/4h bars (for a paper only "your setup" tier), and the extra alerts each option
would add.

Usage (cache defaults to $TRADE_FLOW_CACHE):
  python research/trade_flow.py refresh   # copy the forensics cache, top up 1h candles + funding
  python research/trade_flow.py replay    # 30 day replay, current rules -> flow.pkl
  python research/trade_flow.py report    # funnel tables, base rates, options -> report.json / stdout
No production file is modified; production modules are monkeypatched in process only.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

CACHE = Path(os.environ.get("TRADE_FLOW_CACHE", "/tmp/trade_flow_cache"))
os.environ["FORENSICS_CACHE"] = str(CACHE)
import live_forensics as lf  # noqa: E402

FORENSICS_CACHE = Path(os.environ.get(
    "FORENSICS_SRC", "/tmp/claude-0/-home-claude/f9afb357-b96a-5c99-93e3-0ac2bb39e920/scratchpad/forensics/cache"))
SHORTS_PANEL = Path(os.environ.get(
    "SHORTS_PANEL", "/tmp/claude-0/-home-claude/f9afb357-b96a-5c99-93e3-0ac2bb39e920/scratchpad/sh/short_trades.parquet"))
SYD = ZoneInfo("Australia/Sydney")
# config.AUTO_SCAN_SCHEDULE: morning 06:50 Sydney, close 00:05 UTC, arvo 15:00 Sydney
SCHEDULE = [("morning", "Australia/Sydney", 6, 50), ("close", "UTC", 0, 5),
            ("arvo", "Australia/Sydney", 15, 0)]
# Decay watch state today (brief): these validated longs are switched off.
DEACTIVATED_NOW = {"Momentum Runner", "Donchian Breakout (55d)", "Relative Strength Leader",
                   "Volume Breakout", "Squeeze Breakout"}
LONG_SETUP_LABELS = None   # filled from the scanner rows (direction)


# ── data ─────────────────────────────────────────────────────────────────────
def refresh() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for f in ("ohlcv_1d.pkl", "ohlcv_1h.pkl", "funding.pkl"):
        if not (CACHE / f).exists():
            shutil.copy(FORENSICS_CACHE / f, CACHE / f)
    ex = lf._patch_exchange()
    d, h = lf.load_cache()
    syms = list(h)
    for tf, store, lim in (("1h", h, 60), ("1d", d, 5)):
        for i in range(0, len(syms), 60):
            got = ex.get_ohlcv_batch(syms[i:i + 60], timeframe=tf, limit=lim, exchange="bybit")
            for s, new in got.items():
                old = store.get(s)
                store[s] = new if old is None else pd.concat([old[~old.index.isin(new.index)], new]).sort_index()
            print(f"{tf} {min(i + 60, len(syms))}/{len(syms)}", flush=True)
        (CACHE / f"ohlcv_{tf}.pkl").write_bytes(pickle.dumps(store))
    print("BTC 1h last bar:", h["BTC-USD"].index[-1], " 1d last:", d["BTC-USD"].index[-1])


def refresh_funding() -> None:
    lf.fetch_funding(since="2026-09-20")


# ── scan slots ───────────────────────────────────────────────────────────────
def scan_slots(start: pd.Timestamp, end: pd.Timestamp, extra_hours: list[int] | None = None):
    """UTC times of every scheduled scan between start and end (Sydney DST aware).
    extra_hours: additional UTC hh:05 scans (option b)."""
    out = []
    day = (start - pd.Timedelta(days=1)).normalize()
    while day <= end + pd.Timedelta(days=1):
        for name, tz, hh, mm in SCHEDULE:
            z = ZoneInfo(tz)
            loc = pd.Timestamp(year=day.year, month=day.month, day=day.day, hour=hh, minute=mm, tz=z)
            t = loc.tz_convert("UTC").tz_localize(None)
            out.append((t, name))
        for hh in extra_hours or []:
            out.append((day + pd.Timedelta(hours=hh, minutes=5), f"x{hh:02d}"))
        day += pd.Timedelta(days=1)
    out = sorted({(t, n) for t, n in out if start <= t <= end})
    return out


# ── the replay with the current branch code ─────────────────────────────────
class FlowReplay(lf.Replay):
    def __init__(self, d, h, funding, deactivated=DEACTIVATED_NOW):
        super().__init__(d, h, funding=funding, era="current")
        self.db.deactivated = set(deactivated)
        self.flow: list[dict] = []          # one row per (scan, coin, setup)
        self.scan_meta: list[dict] = []
        self.fires: list[dict] = []
        self._patch_current()

    def _patch_current(self):
        R = self
        # 1) new_setups.latest with the current return shape (tp_r, close), cached
        ns = self.ns
        orig_detect = ns.detect

        def latest(df, btc_close):
            if df is None or len(df) < 206:
                return None
            if pd.Timestamp(df.index[-1]).normalize() >= R.today:
                df = df.iloc[:-1]
            if len(df) < 206:
                return None
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
                    "max_hold": int(row["max_hold"]), "atr": float(row["atr"]),
                    "tp_r": None if pd.isna(row["tp_r"]) else float(row["tp_r"]),
                    "close": float(df["close"].iloc[-1]), "signal_bar": str(df.index[-1].date())}
        ns.latest = latest
        # 2) the scanner drops the forming candle against the REPLAY clock
        orig_drop = self.scanner._drop_forming
        self.scanner._drop_forming = lambda df, now=None: orig_drop(df, now if now is not None else R.db.now)
        # 3) show every ranked row (only the display list and the funding fetch use it)
        self.scan._MAX_CANDIDATES = 100_000

    def era_params(self, t):
        return {"top_n": 5, "cap": True, "ds_wide": True}

    def run_slots(self, sl: list[tuple[pd.Timestamp, str]], end: pd.Timestamp):
        for i, (t, name) in enumerate(sl):
            nxt = sl[i + 1][0] if i + 1 < len(sl) else end
            self.slot_name = name
            self.scan_once(t, self.era_params(t))
            self._record(t, name)
            self.monitor(t, nxt)
            if i % 10 == 0:
                print(f"  scan {i + 1}/{len(sl)} {t} rows {len(self.flow)} fires {len(self.fires)}",
                      flush=True)

    def _record(self, t, name):
        from backtesting import crypto_validation as cv
        import config
        df = getattr(self, "last_df", None)
        validated = cv.validated_labels() or set()
        retired = set(config.RETIRED_SETUPS)
        gate_open, gate_why = self.long_gate()
        res_rows = {(r["ticker"], r.get("setup_label")): r for r in (self._last_res.get("candidates") or [])}
        meta = {"t": t, "slot": name, "universe": len(lf.universe()), "with_data": len(self.frames),
                "liquid": 0 if df is None else len(df), "long_gate_open": gate_open,
                "gate_why": gate_why, "open_positions": self._last_res.get("open_positions"),
                "arm_slots": self._last_res.get("arm_slots"),
                "n_eligible": sum(1 for r in res_rows.values() if r.get("_status") in ("not_selected", "armed")),
                "armed": len(self._last_res.get("armed") or [])}
        self.scan_meta.append(meta)
        if df is None or df.empty:
            return
        for r in df.to_dict("records"):
            act = (r.get("trade") or {}).get("action")
            if act not in ("BUY", "SELL"):
                continue
            lab = r.get("setup_label")
            dr = "long" if act == "BUY" else "short"
            flags = []
            if dr == "long" and not gate_open:
                flags.append("long_gate")
            if lab in self.db.deactivated:
                flags.append("decay")
            if lab in retired:
                flags.append("retired")
            if lab not in validated:
                flags.append("not_validated")
            rr = res_rows.get((r["ticker"], lab))
            st = rr.get("_status") if rr else None
            plan = (rr or {}).get("_plan") or {}
            ns_bar = ((r.get("trade") or {}).get("plan") or {}).get("signal_close")
            self.flow.append({"t": t, "slot": name, "ticker": r["ticker"], "setup": lab, "dir": dr,
                              "flags": flags, "status": st, "stop_pct": plan.get("stop_pct"),
                              "drift_pct": plan.get("drift_pct"), "conv": r.get("conviction"),
                              "close_day": str((t.normalize() - pd.Timedelta(days=1)).date()),
                              "is_new_setup": bool(ns_bar)})

    def scan_once(self, t, p):
        orig = self.scan.run_scan_and_arm
        R = self

        def wrapped(**kw):
            res = orig(**kw)
            R._last_res = res
            return res
        self.scan.run_scan_and_arm = wrapped
        try:
            super().scan_once(t, p)
        finally:
            self.scan.run_scan_and_arm = orig

    # monitor with restop at fire and the basket cap (monitor.poll_once rules)
    def monitor(self, t, nxt):
        import monitor as mon
        import config
        from utils import overext
        active = [r for r in self.db.rows if r["status"] == "active"]
        gate_ok = self.long_gate()[0]
        polls = [t + pd.Timedelta(minutes=1) + pd.Timedelta(minutes=15 * k)
                 for k in range(int((nxt - t) / pd.Timedelta(minutes=15)) + 1)]
        polls = [p for p in polls if p < nxt]
        for r in active:
            h1 = self.h.get(r["symbol"])
            done = False
            for p in polls:
                px = lf.price_at(h1, p)
                if px is None:
                    break
                ind = {"price": px, "prev": px, "rsi2_now": 50.0, "rsi2_prev": 50.0,
                       "rsi14_now": 50.0, "mean20": px}
                cond = json.loads(r["condition_json"])
                if cond.get("kind") in ("breakout", "breakdown", "mr_reversal", "mr_reversal_short"):
                    f = lf.forming_df(self.d[r["symbol"]], h1, p)
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
                    done = True
                    break
                if verdict != "fire":
                    continue
                if (r.get("direction") or "long") == "long":
                    if not gate_ok:
                        r["_gate_veto"] = r.get("_gate_veto", 0) + 1
                        continue
                    mx = overext.measure(r["symbol"], h1[h1.index <= p])
                    if mx and mx["overextended"]:
                        r["status"] = "too_extended"
                        done = True
                        break
                fp = mon._fire_plan(r, px)
                if fp:
                    cond.update({"stop_armed": r.get("stop"), "stop": fp["stop"], "tp": fp.get("tp"),
                                 "restop_at_fire": True})
                    r["stop"], r["tp"] = fp["stop"], fp.get("tp")
                d0 = r.get("direction") or "long"
                day = p.tz_localize("UTC").tz_convert(SYD).date()
                n_today = sum(1 for x in self.fires if x["dir"] == d0 and x["syd_day"] == day
                              and not x["capped"])
                capped = n_today >= config.FIRE_CAP_PER_DIR_PER_DAY
                if capped:
                    cond["basket_cap"] = True
                r["condition_json"] = json.dumps(cond, default=str)
                r.update(status="fired", fired_at=p.isoformat(), fired_price=px, _why=why)
                self.fires.append({"t": p, "syd_day": day, "dir": d0, "symbol": r["symbol"],
                                   "setup": r.get("setup_label"), "capped": capped,
                                   "armed_at": r["created_at"]})
                try:
                    self._track(r)
                except Exception as exc:          # noqa: BLE001
                    r["_track_err"] = str(exc)
                done = True
                break
            if not done and r["status"] == "active":
                r["_unfired_window_end"] = nxt.isoformat()


BUM_1H = Path(os.environ.get(
    "BUM_1H", "/tmp/claude-0/-home-claude/f9afb357-b96a-5c99-93e3-0ac2bb39e920/scratchpad/bum/k1h"))


def volume_ratios(d: dict, end: str = "2026-10-27") -> pd.Series:
    """Per coin: Binance USDT-M quote volume / MEXC perp quote volume over the 20
    days to `end`. The research (shorts study) measured liquidity on Binance; the
    live US hosted scan measures it on the MEXC fallback candles."""
    out = {}
    for s, x in d.items():
        x = x[x.index < end]
        mq = float((x["close"] * x["volume"]).iloc[-20:].mean())
        f = BUM_1H / f"{s[:-4]}USDT.parquet"
        if not f.exists() or mq <= 0:
            continue
        k = pd.read_parquet(f)
        k = k[(k.index >= pd.Timestamp(end) - pd.Timedelta(days=20)) & (k.index < end)]
        if len(k) > 400:
            out[s] = float(k["quote_volume"].sum() / 20) / mq
    return pd.Series(out)


def run_replay(days: int = 30, extra_hours: list[int] | None = None, tag: str = "flow",
               vol_scale: str | None = None):
    import logging
    logging.disable(logging.INFO)
    d, h = lf.load_cache()
    if vol_scale == "binance":
        # option: measure liquidity like the research did (Binance volume)
        ratio = volume_ratios(d)
        print(f"volume scaled for {len(ratio)} coins, median x{ratio.median():.1f}")
        for s, k in ratio.items():
            d[s] = d[s].assign(volume=d[s]["volume"] * k)
            if s in h:
                h[s] = h[s].assign(volume=h[s]["volume"] * k)
    funding = pickle.loads((CACHE / "funding.pkl").read_bytes())
    end = min(pd.Timestamp(h["BTC-USD"].index[-1]) + pd.Timedelta(hours=1),
              pd.Timestamp.now("UTC").tz_localize(None))
    start = end - pd.Timedelta(days=days)
    # 5 day warm up so the book (held coins, open cap) is realistic at the window start
    sl = scan_slots(start - pd.Timedelta(days=5), end, extra_hours)
    print(f"replay {tag}: {len(sl)} scans {sl[0][0]} .. {sl[-1][0]} (data end {end})", flush=True)
    rp = FlowReplay(d, h, funding)
    rp.run_slots(sl, end)
    rows = [{k: v for k, v in r.items()} for r in rp.db.rows]
    out = {"start": start, "end": end, "slots": sl, "flow": rp.flow, "meta": rp.scan_meta,
           "fires": rp.fires, "rows": rows}
    (CACHE / f"{tag}.pkl").write_bytes(pickle.dumps(out))
    print("saved", CACHE / f"{tag}.pkl")


# ── analysis ─────────────────────────────────────────────────────────────────
GATE_ORDER = ["long_gate", "decay", "retired", "not_validated", "held", "bad_plan", "drifted",
              "wide_stop", "crowded", "open_cap", "top_n"]
GATE_NAMES = {"long_gate": "long gate (BTC below 50d or 200d, or breadth < 60%)",
              "decay": "decay watch deactivated", "retired": "retired (Breakdown Short 55d)",
              "not_validated": "not validated (edge gate)", "held": "coin already held",
              "bad_plan": "bad plan (stop < 0.3%)", "drifted": "drift at arm (>3% from signal close)",
              "wide_stop": "stop cap (25%, DS 50%)", "crowded": "funding crowding",
              "open_cap": "open position cap (10)", "top_n": "top_n 5 / diversify"}


def primary_gate(row: dict, meta: dict) -> str:
    for g in ("long_gate", "decay", "retired", "not_validated"):
        if g in row["flags"]:
            return g
    st = row["status"]
    if st == "btc_downtrend":
        return "long_gate"
    if st in ("held", "bad_plan", "drifted", "wide_stop", "crowded"):
        return st
    if st == "not_selected":
        return "open_cap" if (meta.get("arm_slots") or 0) == 0 else "top_n"
    if st == "armed":
        return "armed"
    return st or "unknown"


def funnel(out: dict, since: pd.Timestamp) -> dict:
    meta = [m for m in out["meta"] if m["t"] >= since]
    mby = {m["t"]: m for m in out["meta"]}
    flow = [r for r in out["flow"] if r["t"] >= since]
    n_scans = len(meta)
    weeks = (out["end"] - since) / pd.Timedelta(days=7)
    res = {"scans": n_scans, "weeks": round(weeks, 2),
           "per_scan": {k: float(np.mean([m[k] for m in meta])) for k in ("universe", "with_data", "liquid")},
           "long_gate_open_scans": sum(m["long_gate_open"] for m in meta)}
    res["detected_by_type"] = Counter((r["setup"], r["dir"]) for r in flow)
    prim = Counter(primary_gate(r, mby[r["t"]]) for r in flow)
    res["primary"] = prim
    # independent counts: every gate a row hits (edge-part flags), for context
    res["any_flag"] = Counter(f for r in flow for f in r["flags"])
    # unique signals: (coin, setup, last closed day)
    uniq = defaultdict(list)
    for r in flow:
        uniq[(r["ticker"], r["setup"], r["close_day"])].append(primary_gate(r, mby[r["t"]]))
    res["unique_signals"] = len(uniq)
    res["unique_by_best"] = Counter(("armed" if "armed" in v else
                                     min(v, key=lambda g: GATE_ORDER.index(g) if g in GATE_ORDER else 99))
                                    for v in uniq.values())
    res["unique_validated_types"] = Counter(k[1] for k, v in uniq.items()
                                            if not any(g in ("not_validated", "retired") for g in v))
    rows = [r for r in out["rows"] if pd.Timestamp(r["created_at"]) >= since]
    st = Counter()
    for r in rows:
        s = r["status"]
        if s == "cancelled":
            s = "cancelled unfired (next scan)"
        elif s == "invalidated":
            why = r.get("_why", "")
            s = ("invalidated: bounced > 3%" if "bounced" in why else
                 "invalidated: fell > 3%" if "below the signal" in why else
                 "invalidated: re-anchored stop > cap" if "re-anchored" in why else
                 "invalidated: stop hit" if "stop" in why else "invalidated: other")
        elif s == "active":
            s = "still armed at end"
        st[s] += 1
    res["armed_rows"] = len(rows)
    res["armed_outcome"] = st
    fires = [f for f in out["fires"] if f["t"] >= since]
    res["fired"] = len(fires)
    res["fired_capped"] = sum(f["capped"] for f in fires)
    res["tradeable"] = res["fired"] - res["fired_capped"]
    res["tradeable_per_week"] = round(res["tradeable"] / weeks, 2) if weeks else None
    res["fired_by_setup"] = Counter((f["setup"], "capped" if f["capped"] else "tradeable") for f in fires)
    res["fires_list"] = [(str(f["t"])[:16], f["symbol"], f["setup"], f["capped"]) for f in fires]
    res["armed_list"] = [(str(r["created_at"])[:16], r["symbol"], r["setup_label"], r["status"],
                          r.get("_why", "")[:60]) for r in rows]
    return res


def ledger_funnel(path: Path, since: pd.Timestamp) -> dict:
    d = json.loads(path.read_text())
    t = pd.DataFrame(d["triggers"])
    t["created"] = pd.to_datetime(t["created_at"])
    t = t[t["created"] >= since]
    return {"exported_at": d["exported_at"], "rows": len(t), "status": Counter(t["status"]),
            "fired_or_overcap_by_setup": Counter(t[t["fired_at"].notna()]["setup_label"]),
            "first": str(t["created"].min()), "last": str(t["created"].max())}


def base_rates(panel: Path = SHORTS_PANEL) -> dict:
    """DS / DBF signals per week on the survivor free Binance UM universe (827 coins),
    with the live filters (stop cap DS 50% / DBF 25%, funding veto), by regime."""
    t = pd.read_parquet(panel)
    t = t[t["setup"].isin(["Distribution Short", "Downtrend Bounce Fade"])].copy()
    t["date"] = pd.to_datetime(t["date"])
    t = t[t["date"] >= "2022-01-01"]
    cap = np.where(t["setup"] == "Distribution Short", 50.0, 25.0)
    live = t[(t["stop_pct"] <= cap) & ~(t["fund_last"] <= -0.0005)]
    weeks = (t["date"].max() - pd.Timestamp("2022-01-01")).days / 7
    out = {"weeks": round(weeks, 1), "raw_n": len(t), "live_n": len(live)}
    # days per regime (BTC daily) to turn counts into per week rates
    btc = _btc_daily_panel()
    reg = pd.DataFrame({"above50": btc > btc.rolling(50).mean(), "trend": _btc_trend(btc)})
    reg = reg.loc["2022-01-01":str(t["date"].max().date())]
    for name, mask_days, mask_sig in (
            ("all", reg.index == reg.index, np.ones(len(live), bool)),
            ("BTC below 50d", ~reg["above50"], ~live["btc_above50"].astype(bool)),
            ("BTC below 50d and MIXED", (~reg["above50"]) & (reg["trend"] == "MIXED"),
             (~live["btc_above50"].astype(bool)) & (live["btc_trend"] == "MIXED")),
            ("BTC DOWN", reg["trend"] == "DOWN", live["btc_trend"] == "DOWN")):
        w = mask_days.sum() / 7
        sub = live[np.asarray(mask_sig)]
        per_setup = {s: round(len(g) / w, 2) if w else None for s, g in sub.groupby("setup")}
        days = sub.groupby(sub["date"].dt.normalize()).size()
        # basket cap 3 per direction per day (all shorts)
        capped = int(np.minimum(days, 3).sum())
        out[name] = {"weeks": round(w, 1), "signals": len(sub), "per_week": round(len(sub) / w, 2) if w else None,
                     "per_setup_per_week": per_setup,
                     "after_basket_cap_per_week": round(capped / w, 2) if w else None,
                     "weeks_with_zero_signals_share": None if not w else round(
                         1 - sub["date"].dt.to_period("W").nunique() / max(w, 1), 2)}
    return out


def _btc_daily_panel() -> pd.Series:
    p = Path(SHORTS_PANEL).parent / "short_ctx.parquet"
    d, _ = lf.load_cache()
    # the forensics cache has 500 days; for 2022+ use the shorts study context if it carries BTC
    try:
        ctx = pd.read_parquet(p)
        if "btc_close" in ctx:
            return ctx["btc_close"]
    except Exception:                                   # noqa: BLE001
        pass
    return d["BTC-USD"]["close"]


def _btc_trend(c: pd.Series) -> pd.Series:
    from skills.new_setups import btc_trend
    return btc_trend(c)


def your_setup_frequency(days: int = 30) -> dict:
    """How often the trader's discretionary pattern shows up on the scanned universe:
    a coin that ran up hard (24h gain >= 20% or 7d gain >= 40% at the peak), is
    stretched (peak >= 3 ATR above BOTH the 1h and the 4h EMA20, utils.overext) and is
    now rolling over (1h close back below the 1h EMA20 and a lower high). One alert
    per coin per 48 hours, liquid coins only (20d turnover >= $2M). Paper only."""
    d, h = lf.load_cache()
    end = pd.Timestamp(h["BTC-USD"].index[-1])
    start = end - pd.Timedelta(days=days)
    hits = []
    for s, x in h.items():
        if s.startswith("BTC") or len(x) < 300:
            continue
        dd = d.get(s)
        if dd is None or len(dd) < 25:
            continue
        qv = (dd["close"] * dd["volume"]).rolling(20).mean().shift(1)
        c, hi = x["close"], x["high"]
        e1 = c.ewm(span=20, adjust=False).mean()
        tr = pd.concat([x["high"] - x["low"], (x["high"] - c.shift()).abs(),
                        (x["low"] - c.shift()).abs()], axis=1).max(axis=1)
        a1 = tr.rolling(14).mean()
        x4 = x.resample("4h", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        e4 = x4["close"].ewm(span=20, adjust=False).mean()
        tr4 = pd.concat([x4["high"] - x4["low"], (x4["high"] - x4["close"].shift()).abs(),
                         (x4["low"] - x4["close"].shift()).abs()], axis=1).max(axis=1)
        a4 = tr4.rolling(14).mean()
        # 4h values known at each 1h bar: last CLOSED 4h bar
        e4h = e4.shift(1).reindex(x.index, method="ffill")
        a4h = a4.shift(1).reindex(x.index, method="ffill")
        peak12 = hi.rolling(12).max()
        ext1 = (peak12 - e1) / a1
        ext4 = (peak12 - e4h) / a4h
        g24 = peak12 / c.shift(24).rolling(12).min() - 1
        g7d = peak12 / c.shift(168) - 1
        roll = (c < e1) & (c.shift(1) >= e1.shift(1)) & (hi < peak12)
        cond = (ext1 >= 3) & (ext4 >= 3) & ((g24 >= 0.20) | (g7d >= 0.40)) & roll
        idx = cond[cond & (cond.index >= start)].index
        last = None
        for ts in idx:
            day = ts.normalize()
            q = qv.reindex([day], method="ffill").iloc[0] if len(qv) else np.nan
            if not (q >= 2e6):
                continue
            if last is not None and ts - last < pd.Timedelta(hours=48):
                continue
            last = ts
            hits.append({"t": ts, "sym": s, "ext4": float(ext4[ts]), "g24": float(g24[ts]),
                         "pct_above_4h_ema": float(c[ts] / e4h[ts] - 1)})
    hits = pd.DataFrame(hits)
    weeks = days / 7
    out = {"days": days, "hits": len(hits), "per_week": round(len(hits) / weeks, 1) if len(hits) else 0}
    if len(hits):
        per_day = hits.groupby(hits["t"].dt.tz_localize("UTC").dt.tz_convert(SYD).dt.date).size()
        out["per_week_capped_3_per_day"] = round(np.minimum(per_day, 3).sum() / weeks, 1)
        out["days_with_hit_share"] = round(len(per_day) / days, 2)
        out["examples"] = [(str(r.t)[:16], r.sym, round(r.pct_above_4h_ema * 100, 1), round(r.g24 * 100))
                           for r in hits.sort_values("t").tail(8).itertuples()]
    return out


def report():
    out = pickle.loads((CACHE / "flow.pkl").read_bytes())
    end = out["end"]
    rep = {"window": [str(out["start"]), str(end)]}
    for name, days in (("30d", 30), ("7d", 7)):
        rep[name] = funnel(out, end - pd.Timedelta(days=days))
    x = CACHE / "flow_hourly.pkl"
    if x.exists():
        oh = pickle.loads(x.read_bytes())
        for name, days in (("30d_hourly", 30), ("7d_hourly", 7)):
            rep[name] = funnel(oh, oh["end"] - pd.Timedelta(days=days))
    lp = CACHE / "track_export.json"
    if lp.exists():
        rep["ledger"] = ledger_funnel(lp, pd.Timestamp("2026-10-08"))
        rep["ledger_7d"] = ledger_funnel(lp, end - pd.Timedelta(days=7))
    try:
        rep["base_rates"] = base_rates()
    except Exception as exc:                              # noqa: BLE001
        rep["base_rates"] = {"error": str(exc)}
    rep["your_setup"] = your_setup_frequency(30)
    rep["your_setup_7d"] = your_setup_frequency(7)
    rep["universe_note"] = {"bybit_perps_json": json.loads((ROOT / "data" / "bybit_perps.json").read_text())["updated"],
                            "symbols": len(lf.universe()),
                            "with_candles": len(lf.load_cache()[0])}
    txt = json.dumps(rep, indent=1, default=lambda o: {str(k): v for k, v in o.items()}
                     if isinstance(o, dict) else str(o))
    (CACHE / "report.json").write_text(txt)
    print(txt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["refresh", "funding", "replay", "replay_hourly",
                                    "replay_binvol", "report"])
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    if a.cmd == "refresh":
        return refresh()
    if a.cmd == "funding":
        return refresh_funding()
    if a.cmd == "replay":
        return run_replay(a.days)
    if a.cmd == "replay_hourly":
        # option (b): four more scans a day (02, 08, 12, 16 UTC) on top of the schedule
        return run_replay(a.days, extra_hours=[2, 8, 12, 16], tag="flow_hourly")
    if a.cmd == "replay_binvol":
        return run_replay(a.days, tag="flow_binvol", vol_scale="binance")
    if a.cmd == "report":
        return report()


if __name__ == "__main__":
    main()
