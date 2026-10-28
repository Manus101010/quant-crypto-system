"""
Shorts decay study (28 Oct 2026): are Distribution Short, Downtrend Bounce Fade
and Breakdown Short (55d low) still edges, and what version works in 2026?

Pipeline (survivorship-free Binance USDT-M perp archive, incl. delisted coins):
  1. python research/edge_fix/shorts_fetch_binance_um.py DATA      (1h klines + funding)
  2. python research/edge_fix/shorts_signals.py DATA OUT           (signals + 1h sims)
  3. python research/edge_fix/shorts_oi.py OUT                     (OI 3d/7d at signal)
  4. python research/edge_fix_shorts.py OUT                        (this file: tables)

Writes OUT/shorts_tables.md (the numbers in docs/edge_fix/shorts.md).

Design (fixed before looking at the out of sample period):
  in sample (IS)      2022-01-01 .. 2025-06-30   variants are chosen here
  out of sample (OOS) 2025-07-01 .. 2026-10-27   untouched until the final table
  Selection rule: a variant is selected if on IS it raises expectancy vs the
  live base with a one sided week-block bootstrap p < 0.10. Selected filters
  are AND-combined with at most one exit/entry replacement (best IS delta).
  Every variant's OOS result is still reported; OOS p values are Holm adjusted
  over all variants tried. Edge gate on OOS: PF > 1, n >= 25, positive total R
  in both halves of the OOS period.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

IS_END = pd.Timestamp("2025-06-30")
OOS_START = pd.Timestamp("2025-07-01")
RNG = np.random.default_rng(7)
NBOOT = 4000
DS, DBF, BDS = "Distribution Short", "Downtrend Bounce Fade", "Breakdown Short (55d low)"
SHORT = {DS: "DS", DBF: "DBF", BDS: "BDS"}
FUND_VETO = -0.0005


# ── stats ───────────────────────────────────────────────────────────────────
def pf(a):
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    loss = -a[a < 0].sum()
    return a[a > 0].sum() / loss if loss > 0 else np.inf


def week_boot(df: pd.DataFrame, fn, nboot=NBOOT) -> np.ndarray:
    """Bootstrap a statistic by resampling whole calendar weeks (signals in the
    same week are correlated: alt shorts fire in clusters)."""
    wk = df["date"].dt.to_period("W").astype(str).values
    groups = pd.Series(np.arange(len(df))).groupby(wk).apply(list).tolist()
    out = np.empty(nboot)
    for b in range(nboot):
        pick = RNG.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[p] for p in pick]) if len(groups) else np.array([], int)
        out[b] = fn(df.iloc[idx])
    return out


def summ(df: pd.DataFrame, col="r", ci=False) -> dict:
    a = df[col].values.astype(float)
    a = a[np.isfinite(a)]
    s = {"n": len(a), "pf": pf(a) if len(a) else np.nan, "exp": a.mean() if len(a) else np.nan,
         "win": (a > 0).mean() if len(a) else np.nan, "tot": a.sum()}
    if ci and len(a) >= 8:
        b = week_boot(df[np.isfinite(df[col].values.astype(float))], lambda x: x[col].mean())
        s["lo"], s["hi"] = np.nanpercentile(b, [2.5, 97.5])
    return s


def fmt(s: dict, ci=False) -> str:
    if s["n"] == 0:
        return "0 | | |"
    p = "inf" if not np.isfinite(s["pf"]) else f"{s['pf']:.2f}"
    base = f"{s['n']} | {p} | {s['exp']:+.3f} | {s['win']*100:.0f}%"
    if ci:
        base += f" | {s.get('lo', np.nan):+.2f} to {s.get('hi', np.nan):+.2f}" if "lo" in s else " | n/a"
    return base


# ── live versions of each setup ─────────────────────────────────────────────
def veto(T):
    return T.fund_last.isna() | (T.fund_last > FUND_VETO)


def live(T: pd.DataFrame, setup: str, ds_cap=50.0) -> pd.DataFrame:
    x = T[(T.setup == setup) & veto(T)]
    if setup == DS:
        x = x[x.stop_pct <= ds_cap]
    else:
        x = x[x.stop_pct <= 25.0]
    if setup == BDS:
        x = x[~x.oversold]
    return x[np.isfinite(x.r)].copy()


# ── variants ────────────────────────────────────────────────────────────────
def variants(setup: str) -> dict:
    """name -> (kind, spec). kind 'filter': boolean mask fn; 'swap': R column."""
    v = {}
    if setup == DS:
        v["V1 OI 3d rising (pre-registered)"] = ("filter", lambda x: x.oi_chg3d.isna() | (x.oi_chg3d > 0))
    if setup == DBF:
        v["V1 skip OI 7d >= +10% (pre-registered)"] = ("filter", lambda x: x.oi_chg7d.isna() | (x.oi_chg7d < 0.10))
    v["V2 entry: 4h close below signal-day low (48h)"] = ("swap", "conf4h")
    v["V3 entry: 1h close below signal-day low (24h)"] = ("swap", "conf1h")
    v["V4 time stop " + {DS: "20d", DBF: "5d", BDS: "20d"}[setup]] = ("swap", "r_time")
    v["V5 " + ("breakeven at +0.5R" if setup == DBF else "add 2R take profit")] = ("swap", "r_exit")
    v["V6 only when BTC below 4h EMA50"] = ("filter", lambda x: x.btc_4h_below_ema50.fillna(False).astype(bool))
    v["V7 turnover >= $5M and listed >= 180d"] = ("filter", lambda x: (x.qvol20 >= 5e6) & ((x.age_days >= 180) | x.listed_before_archive))
    v["V8 skip FOMC/CPI in next 48h"] = ("filter", lambda x: ~x.macro_next2.astype(bool))
    if setup == DS:
        v["V9 stop cap 25% (undo 25 Oct rule)"] = ("filter", lambda x: x.stop_pct <= 25)
    # Added after the forensics note (lead, 28 Oct): exit model, arming time, the
    # sma50 > sma200 branch. Also selected on IS only.
    if setup in (DS, BDS):
        v["V12 exit: research close trail (close + 3.5 ATR, daily)"] = ("swap", "r_closetrail")
    v["V13 arm 12h after close at live price, stop recomputed"] = ("swap", "live12_restop")
    if setup == DS:
        v["V14 drop the sma50 > sma200 branch (need +50% in 120d)"] = ("filter", lambda x: x.ret120 >= 0.5)
        v["V15 sma50 > sma200 branch only above the 200d"] = ("filter", lambda x: (x.ret120 >= 0.5) | x.above200.astype(bool))
    # Added AFTER the first full run showed the Jul..Sep 2026 losses came in a broad
    # alt rally. Selected on IS like the rest, but their OOS is not clean: read as
    # hypotheses for the forward ledger, not as validated.
    v["V10 (post hoc) setup decay gate: last 20 closed trades mean R > 0"] = ("filter", lambda x: x.decay_ok.astype(bool))
    v["V11 (post hoc) breadth not rising: breadth50 <= its value 20d ago"] = ("filter", lambda x: (x.breadth_chg20 <= 0).fillna(False))
    return v


def add_gates(x: pd.DataFrame, ctx: pd.DataFrame, k: int = 20) -> pd.DataFrame:
    """decay_ok: mean R of the last k trades of this setup that had CLOSED before
    the signal close is > 0 (True while fewer than k have closed). Uses only
    information available at the signal. breadth_chg20: breadth50 change over 20d."""
    x = x.sort_values("date").copy()
    exit_t = x.date + pd.Timedelta(days=1) + pd.to_timedelta(x.bars_h, unit="h")
    order = np.argsort(exit_t.values)
    et, rr = exit_t.values[order], x.r.values[order]
    ok = []
    for d in (x.date + pd.Timedelta(days=1)).values:
        m = np.searchsorted(et, d, side="right")
        ok.append(True if m < k else rr[m - k:m].mean() > 0)
    x["decay_ok"] = ok
    b = ctx["breadth50"]
    x["breadth_chg20"] = (b - b.shift(20)).reindex(x.date).values
    return x


def apply(x: pd.DataFrame, kind, spec) -> pd.Series:
    """Per-signal R under the variant, NaN = no trade."""
    if kind == "filter":
        m = spec(x).values.astype(bool)
        return pd.Series(np.where(m, x.r.values, np.nan), index=x.index)
    return x[spec].astype(float)


def delta_test(x: pd.DataFrame, rv: pd.Series) -> tuple[float, float]:
    """expectancy(variant, own trades) - expectancy(base); one sided p (delta <= 0)."""
    y = x.assign(_v=rv.values)
    d0 = np.nanmean(y._v) - y.r.mean()
    b = week_boot(y, lambda z: (np.nanmean(z._v) if np.isfinite(z._v).any() else np.nan) - z.r.mean())
    b = b[np.isfinite(b)]
    return d0, float((b <= 0).mean()) if len(b) else np.nan


def holm(ps: list[float]) -> list[float]:
    p = np.asarray(ps, float)
    order = np.argsort(p)
    adj = np.empty_like(p)
    m, run = len(p), 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (m - k) * p[i]))
        adj[i] = run
    return adj.tolist()


def halves_ok(df: pd.DataFrame, col: str) -> tuple[float, float]:
    y = df[np.isfinite(df[col].values.astype(float))].sort_values("date")
    if len(y) < 4:
        return np.nan, np.nan
    mid = y.date.iloc[len(y) // 2]
    return y[y.date < mid][col].sum(), y[y.date >= mid][col].sum()


# ── report ──────────────────────────────────────────────────────────────────
def main(out: Path):
    T = pd.read_parquet(out / "short_trades.parquet")
    meta = pd.read_parquet(out / "short_meta.parquet")
    T["date"] = pd.to_datetime(T.date)
    for c in ("oi_chg3d", "oi_chg7d"):
        if c not in T:
            T[c] = np.nan
    T["q"] = T.date.dt.to_period("Q").astype(str)
    T["period"] = np.where(T.date <= IS_END, "IS", "OOS")
    L = []
    w = L.append
    n_open = int(T.r.isna().sum())
    w(f"Universe: {len(meta)} Binance USDT-M perps with >= 60 days of data, "
      f"{int(meta.dead.sum())} of them delisted before 20 Oct 2026. Signals 2022-01-01 to 2026-10-26: "
      f"{len(T)} raw (all filters off), {n_open} still open at data end on live coins (excluded).\n")

    ctx = pd.read_parquet(out / "short_ctx.parquet")
    lives = {k_: add_gates(live(T, k_), ctx) for k_ in (DS, DBF, BDS)}
    lives_alt = {"DS old cap 25%": live(T, DS, 25.0),
                 "BDS incl. oversold": T[(T.setup == BDS) & veto(T) & (T.stop_pct <= 25) & np.isfinite(T.r)]}

    # 1. headline + survivors
    w("## T1 Headline, live versions, full period 2022-01 to 2026-10\n")
    w("| Setup | n | PF | exp R | win | 95% CI exp R (week bootstrap) | survivors only: n / PF / exp R | delisted coins only: n / exp R |")
    w("|---|---|---|---|---|---|---|---|")
    for name, x in list(lives.items()) + list(lives_alt.items()):
        s = summ(x, ci=True)
        sv = summ(x[~x.dead]); dd = summ(x[x.dead])
        w(f"| {SHORT.get(name, name)} | {fmt(s, ci=True)} | {sv['n']} / {sv['pf']:.2f} / {sv['exp']:+.3f} | "
          f"{dd['n']} / {dd['exp']:+.3f} |" if dd['n'] else
          f"| {SHORT.get(name, name)} | {fmt(s, ci=True)} | {sv['n']} / {sv['pf']:.2f} / {sv['exp']:+.3f} | 0 |")
    w("")

    # 2. quarterly
    w("## T2 By quarter (live versions): n, PF, exp R\n")
    qs = sorted(T.q.unique())
    w("| Quarter | " + " | ".join(f"{SHORT[s]} n | {SHORT[s]} PF | {SHORT[s]} expR" for s in lives) + " |")
    w("|---|" + "---|" * (3 * len(lives)))
    for q in qs:
        cells = []
        for s, x in lives.items():
            y = x[x.q == q]
            if len(y) == 0:
                cells += ["0", "", ""]
                continue
            st = summ(y)
            cells += [str(st["n"]), "inf" if not np.isfinite(st["pf"]) else f"{st['pf']:.2f}", f"{st['exp']:+.2f}"]
        w(f"| {q} | " + " | ".join(cells) + " |")
    w("")

    # yearly with CI
    w("## T3 By year with 95% week-block bootstrap CI of exp R\n")
    w("| Setup | Year | n | PF | exp R | win | 95% CI |")
    w("|---|---|---|---|---|---|---|")
    for s, x in lives.items():
        for y in sorted(x.date.dt.year.unique()):
            st = summ(x[x.date.dt.year == y], ci=True)
            w(f"| {SHORT[s]} | {y} | {fmt(st, ci=True)} |")
    w("")

    # 2026 significance
    w("## T4 Is 2026 different from 2022 to 2025? (difference in exp R, week-block bootstrap)\n")
    w("| Setup | pre-2026 n / exp R | 2026 n / exp R | diff | 95% CI of diff | p(2026 not worse) |")
    w("|---|---|---|---|---|---|")
    for s, x in lives.items():
        a, b = x[x.date.dt.year < 2026], x[x.date.dt.year == 2026]
        if len(b) < 5:
            continue
        ba = week_boot(a, lambda z: z.r.mean()); bb = week_boot(b, lambda z: z.r.mean())
        diff = bb - ba
        lo, hi = np.nanpercentile(diff, [2.5, 97.5])
        w(f"| {SHORT[s]} | {len(a)} / {a.r.mean():+.3f} | {len(b)} / {b.r.mean():+.3f} | "
          f"{b.r.mean()-a.r.mean():+.3f} | {lo:+.2f} to {hi:+.2f} | {np.mean(diff >= 0):.3f} |")
    w("")

    # regimes
    w("## T5 Regime splits (live versions). Cells: n / PF / exp R. Full = 2022-01 to 2026-10, OOS = 2025-07 to 2026-10\n")
    T_br = pd.cut(T.breadth50, [-0.01, 0.3, 0.6, 1.01], labels=["breadth <30%", "breadth 30 to 60%", "breadth >60%"])
    T_fd = pd.cut(T.fund3, [-1, -1e-9, 0.9999e-4, 1], labels=["funding < 0", "funding 0..0.01%", "funding >= 0.01%"])
    T_oi = pd.cut(T.oi_chg3d if "oi_chg3d" in T else pd.Series(np.nan, index=T.index),
                  [-10, 0, 0.10, 100], labels=["OI 3d <= 0", "OI 3d 0..+10%", "OI 3d > +10%"])
    splits = {"BTC vs 50d": T.btc_above50.map({True: "BTC > 50d", False: "BTC < 50d"}),
              "BTC vs 200d": T.btc_above200.map({True: "BTC > 200d", False: "BTC < 200d"}),
              "BTC trend label": T.btc_trend, "BTC 4h vs EMA50": T.btc_4h_below_ema50.map({True: "BTC 4h < EMA50", False: "BTC 4h > EMA50"}),
              "Breadth (coins > 50d)": T_br.astype(str), "Coin funding (last 3)": T_fd.astype(str),
              "OI 3d (coin units)": T_oi.astype(str)}
    w("| Split | Bucket | " + " | ".join(f"{SHORT[s]} full | {SHORT[s]} OOS" for s in lives) + " |")
    w("|---|---|" + "---|" * (2 * len(lives)))
    for nm, ser in splits.items():
        for bk in sorted(ser.dropna().unique()):
            if bk in ("nan", "NA"):
                continue
            cells = []
            for s, x in lives.items():
                for per in ("full", "OOS"):
                    y = x[ser.loc[x.index] == bk]
                    if per == "OOS":
                        y = y[y.period == "OOS"]
                    st = summ(y)
                    cells.append("" if st["n"] == 0 else f"{st['n']} / {st['pf']:.2f} / {st['exp']:+.2f}")
            w(f"| {nm} | {bk} | " + " | ".join(cells) + " |")
    w("")

    # 3. wide stops
    w("## T6 Distribution Short by stop distance (funding veto on, no stop cap)\n")
    D = T[(T.setup == DS) & veto(T) & np.isfinite(T.r)]
    w("| Stop % | all 2022 to 2026: n / PF / exp R | survivors only: n / PF / exp R | IS 2022 to 2025-06 | OOS 2025-07 to 2026-10 | 2026 only |")
    w("|---|---|---|---|---|---|")
    for lo, hi in [(0, 15), (15, 25), (25, 35), (35, 50), (50, 999), (0, 25), (25, 50), (0, 50)]:
        y = D[(D.stop_pct > lo) & (D.stop_pct <= hi)]
        c = lambda z: (lambda st: f"{st['n']} / {st['pf']:.2f} / {st['exp']:+.3f}" if st['n'] else "0")(summ(z))
        w(f"| {lo} to {hi if hi < 999 else 'max'} | {c(y)} | {c(y[~y.dead])} | {c(y[y.period=='IS'])} | "
          f"{c(y[y.period=='OOS'])} | {c(y[y.date.dt.year==2026])} |")
    y = D[(D.stop_pct > 25) & (D.stop_pct <= 50)]
    if len(y) >= 8:
        b = week_boot(y, lambda z: z.r.mean())
        w(f"\n25 to 50% bucket exp R 95% CI (week bootstrap): {np.percentile(b,2.5):+.3f} to {np.percentile(b,97.5):+.3f}; "
          f"PF {pf(y.r):.2f}, n {len(y)}.")
    w("")

    # 4. variants
    w("## T7 Candidate fixes: chosen on IS (2022-01 to 2025-06), tested untouched on OOS (2025-07 to 2026-10)\n")
    w("Cells: n / PF / exp R. delta = variant exp R minus live base exp R on the same period; p one sided week-block bootstrap. "
      "Holm p corrects over every variant tried (all setups).\n")
    rows, oos_ps = [], []
    for s, x in lives.items():
        IS, OOS = x[x.period == "IS"], x[x.period == "OOS"]
        base_is, base_oos = summ(IS), summ(OOS)
        rows.append([s, "BASE (live)", base_is, None, None, base_oos, None, None, halves_ok(OOS, "r"), summ(OOS[OOS.date.dt.year == 2026])])
        for vn, (kind, spec) in variants(s).items():
            rv_is, rv_oos = apply(IS, kind, spec), apply(OOS, kind, spec)
            si = summ(IS.assign(_v=rv_is.values), "_v"); so = summ(OOS.assign(_v=rv_oos.values), "_v")
            di, pi = delta_test(IS, rv_is)
            do, po = delta_test(OOS, rv_oos)
            O2 = OOS.assign(_v=rv_oos.values)
            rows.append([s, vn, si, di, pi, so, do, po, halves_ok(O2, "_v"), summ(O2[O2.date.dt.year == 2026], "_v"),
                         kind, spec])
            oos_ps.append(po)
    adj = iter(holm(oos_ps))
    w("| Setup | Variant | IS n/PF/expR | IS delta (p) | selected | OOS n/PF/expR | OOS delta (p, Holm p) | OOS halves R | 2026 n/expR | OOS edge gate |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    sel = {s: [] for s in lives}
    cf = lambda st: f"{st['n']} / {st['pf']:.2f} / {st['exp']:+.3f}" if st["n"] else "0"
    for r in rows:
        s, vn, si, di, pi, so, do, po, (h1, h2), s26 = r[:10]
        gate = (so["n"] >= 25 and so["pf"] > 1 and h1 > 0 and h2 > 0)
        if di is None:
            w(f"| {SHORT[s]} | {vn} | {cf(si)} | | | {cf(so)} | | {h1:+.1f} / {h2:+.1f} | {s26['n']} / {s26['exp']:+.3f} | {'PASS' if gate else 'fail'} |")
            continue
        hp = next(adj)
        chosen = di > 0 and pi < 0.10 and si["n"] >= 25
        if chosen:
            sel[s].append((vn, r[10], r[11], di))
        w(f"| {SHORT[s]} | {vn} | {cf(si)} | {di:+.3f} ({pi:.2f}) | {'YES' if chosen else 'no'} | {cf(so)} | "
          f"{do:+.3f} ({po:.2f}, {hp:.2f}) | {h1:+.1f} / {h2:+.1f} | {s26['n']} / {s26['exp']:+.3f} | {'PASS' if gate else 'fail'} |")
    w(f"\nVariants tried: {len(oos_ps)} (plus the base per setup). No other variants were run.\n")

    # live arming model
    w("## T9 Entry timing: research (enter at the daily close) vs how live arms (scan h hours later, fire at the then price)\n")
    w("Live as is: stop fixed from the signal close, paper trail at the live stop distance, rejected if price is > 3% below the signal close or at the stop. "
      "Restop: same entry, stop recomputed as live price + 3.5 ATR (DS, BDS; DBF keeps its 7d-high stop). Cells n / PF / exp R.\n")
    w("| Setup | Model | IS | OOS | 2026 |")
    w("|---|---|---|---|---|")
    for s_, x in lives.items():
        for col, nm in [("r", "research: enter at daily close"), ("r_closetrail", "research exits (close trail)")] + \
                [(f"live{d}", f"live as is, scan +{d}h") for d in (6, 12, 20)] + \
                [(f"live{d}_restop", f"restop at arm, scan +{d}h") for d in (6, 12, 20)]:
            if s_ == DBF and (col == "r_closetrail" or col.endswith("restop")):
                continue
            w(f"| {SHORT[s_]} | {nm} | {cf(summ(x[x.period=='IS'], col))} | {cf(summ(x[x.period=='OOS'], col))} | "
              f"{cf(summ(x[x.date.dt.year==2026], col))} |")
    w("")

    # combos
    w("## T8 Selected combination per setup (IS-selected rules AND-ed, post hoc V10/V11 left out), OOS result\n")
    w("| Setup | Rules | IS n/PF/expR | OOS n/PF/expR | OOS halves R | 2026 n/expR | OOS edge gate |")
    w("|---|---|---|---|---|---|---|")
    for s, x in lives.items():
        if not sel[s]:
            w(f"| {SHORT[s]} | none selected on IS | | | | | |")
            continue
        filt = [v for v in sel[s] if v[1] == "filter" and "post hoc" not in v[0]]
        swaps = sorted([v for v in sel[s] if v[1] == "swap"], key=lambda v: -v[3])[:1]
        col = swaps[0][2] if swaps else "r"

        def comb(z):
            m = np.ones(len(z), bool)
            for _, _, fn, _ in filt:
                m &= fn(z).values.astype(bool)
            return z.assign(_v=np.where(m, z[col].astype(float).values, np.nan))
        ci, co = comb(x[x.period == "IS"]), comb(x[x.period == "OOS"])
        so = summ(co, "_v"); h1, h2 = halves_ok(co, "_v")
        s26 = summ(co[co.date.dt.year == 2026], "_v")
        gate = so["n"] >= 25 and so["pf"] > 1 and h1 > 0 and h2 > 0
        names = " + ".join(v[0].split(" ", 1)[0] for v in filt + swaps)
        w(f"| {SHORT[s]} | {names} | {cf(summ(ci, '_v'))} | {cf(so)} | {h1:+.1f} / {h2:+.1f} | {s26['n']} / {s26['exp']:+.3f} | {'PASS' if gate else 'fail'} |")
    w("")
    (out / "shorts_tables.md").write_text("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
