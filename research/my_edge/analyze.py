"""Selection on IS (2023-01..2025-06), untouched OOS (2025-07..2026-10), extra untouched
pre-IS holdout (2021-08..2022-12). Writes results/*.csv and prints the report tables.

Pre-registered selection rule (fixed before any OOS number was looked at):
  family = A (rollover short), B (capitulation long), C-long, C-short.
  Step 1, entry: with HIS exit exactly (activate trail at +3%, trail 5%), taker cost,
          among entries with IS n >= 50 and both IS halves > 0, the highest day
          clustered t. None qualifies -> best t shown, flagged IS FAIL.
  Step 2, exit: for that entry, the trail exit (15 combos) with the highest IS t.
  OOS: both the default and the tuned exit, at taker and maker cost.
Run: python research/my_edge/analyze.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core as C          # noqa: E402

import os
RES = Path(__file__).resolve().parent / os.environ.get("MY_EDGE_OUT", "results")
WIN = {"pre": (C.PRE_START, C.IS_START), "is": (C.IS_START, C.IS_END), "oos": (C.IS_END, C.DATA_END)}
DEFAULT_X = "act3_tr5"


def load_trades():
    t = pd.read_parquet(RES / "trades.parquet")
    E = list(pd.read_csv(RES / "entries.csv", index_col=0).iloc[:, 0])
    X = list(pd.read_csv(RES / "exits.csv", index_col=0).iloc[:, 0])
    t["t"] = pd.to_datetime(t["t"])
    t["win"] = np.select([t["t"] < C.IS_START, t["t"] < C.IS_END], ["pre", "is"], "oos")
    t["fam"] = np.array([e.split("|")[0] for e in E])[t["e"].to_numpy()]
    cfam = np.where(t["side"] == 1, "C-long", "C-short")
    t["fam"] = np.where(t["fam"] == "C", cfam, t["fam"])
    for k, v in C.COSTS.items():
        t[f"r_{k}"] = (t["net0"] - v) / t["sp"]
        t[f"p_{k}"] = t["net0"] - v
    return t, E, X


def stats(d: pd.DataFrame, col="r_taker", weeks=None) -> dict:
    if len(d) == 0:
        return {"n": 0}
    r = d[col].to_numpy()
    gl = -r[r < 0].sum()
    pf = r[r > 0].sum() / gl if gl > 0 else np.inf
    day = d.groupby(d["t"].dt.floor("D"))[col].sum()
    td = day.mean() / day.std(ddof=1) * np.sqrt(len(day)) if len(day) > 2 and day.std() > 0 else np.nan
    srt = d.sort_values("t")[col].to_numpy()
    h = len(srt) // 2
    pcol = col.replace("r_", "p_")
    out = {"n": len(r), "win": (r > 0).mean(), "pf": pf, "exp": r.mean(), "tot": r.sum(), "t": td,
           "h1": srt[:h].sum(), "h2": srt[h:].sum(), "pct": d[pcol].mean() * 100 if pcol in d else np.nan,
           "stop_med": d["sp"].median() * 100}
    if weeks:
        out["wk"] = len(r) / weeks
    return out


def weeks_of(w):
    a, b = WIN[w]
    return (b - a).days / 7


def cap3(d: pd.DataFrame) -> pd.DataFrame:
    d = d.sort_values("t")
    key = [d["t"].dt.floor("D"), d["side"]]
    return d[d.groupby(key).cumcount() < 3]


def cluster(d: pd.DataFrame) -> dict:
    g = d.groupby([d["t"].dt.floor("D"), d["side"]]).size()
    if len(g) == 0:
        return {}
    big = g[g > 3]
    return {"days_active": len(g), "mean_per_active_day": g.mean(), "max_day": int(g.max()),
            "share_on_days_gt3": big.sum() / g.sum()}


def fmt(s):
    if not s.get("n"):
        return "n 0"
    return (f"n {s['n']:5d} win {s['win']:.0%} PF {s['pf']:.2f} exp {s['exp']:+.3f}R "
            f"({s['pct']:+.2f}%) tot {s['tot']:+.0f}R t {s['t']:+.2f} halves {s['h1']:+.0f}/{s['h2']:+.0f}"
            + (f" wk {s['wk']:.1f}" if "wk" in s else "") + f" stop {s['stop_med']:.1f}%")


def main():
    t, E, X = load_trades()
    nvar = len(E) * len(X)
    z_is = norm.isf(0.05 / nvar)
    print(f"trades {len(t)}  variants {nvar}  Bonferroni IS t bar {z_is:.2f}")
    # full IS / OOS table for every variant
    rows = []
    for (e, x), d in t.groupby(["e", "x"]):
        for w in ("pre", "is", "oos"):
            dw = d[d["win"] == w]
            for col in ("r_taker", "r_maker"):
                s = stats(dw, col, weeks_of(w))
                s.update({"entry": E[e], "exit": X[x], "win": w, "cost": col[2:]})
                rows.append(s)
    tab = pd.DataFrame(rows)
    tab.to_csv(RES / "all_variants.csv", index=False)
    tab["fam"] = tab["entry"].str.split("|").str[0]
    tab.loc[tab["entry"].str.startswith("C|L"), "fam"] = "C-long"
    tab.loc[tab["entry"].str.startswith("C|S"), "fam"] = "C-short"

    # landscape: share of variants profitable
    print("\n== landscape (taker): share of variants with PF > 1, his trail exits only ==")
    trailx = [x for x in X if x.startswith("act")]
    for fam in ("A", "B", "C-long", "C-short"):
        for w in ("is", "oos"):
            q = tab[(tab.fam == fam) & (tab.win == w) & (tab.cost == "taker") & tab["exit"].isin(trailx) & (tab.n >= 30)]
            print(f"{fam:8s} {w:4s} variants {len(q):4d} PF>1 {(q.pf > 1).mean():.0%} median PF {q.pf.median():.2f} "
                  f"best PF {q.pf.max():.2f} median wk {q.wk.median():.1f}")

    picks = {}
    for fam in ("A", "B", "C-long", "C-short"):
        q = tab[(tab.fam == fam) & (tab.win == "is") & (tab.cost == "taker") & (tab["exit"] == DEFAULT_X)]
        ok = q[(q.n >= 50) & (q.h1 > 0) & (q.h2 > 0)]
        flag = "" if len(ok) else "IS FAIL"
        best = (ok if len(ok) else q[q.n >= 50]).sort_values("t", ascending=False).iloc[0]
        q2 = tab[(tab.entry == best.entry) & (tab.win == "is") & (tab.cost == "taker") & tab["exit"].isin(trailx)]
        bx = q2.sort_values("t", ascending=False).iloc[0]["exit"]
        picks[fam] = (best.entry, bx, flag)
    print("\n== picks ==")
    out = []
    for fam, (en, bx, flag) in picks.items():
        ei = E.index(en)
        for xn in dict.fromkeys([DEFAULT_X, bx, "T2R_48h", "T1R_24h"]):
            d = t[(t.e == ei) & (t.x == X.index(xn))]
            for w in ("pre", "is", "oos"):
                dw = d[d.win == w]
                for col in ("r_taker", "r_maker"):
                    s = stats(dw, col, weeks_of(w))
                    sc = stats(cap3(dw), col, weeks_of(w))
                    cl = cluster(dw)
                    act = (dw["code"] == 1).mean() if len(dw) else np.nan
                    out.append({"fam": fam, "entry": en, "exit": xn, "role": "default" if xn == DEFAULT_X else ("tuned" if xn == bx else "fixed"),
                                "flag": flag, "win": w, "cost": col[2:], **s,
                                **{f"cap3_{k}": v for k, v in sc.items()}, **cl, "trail_exit_share": act})
                    if col == "r_taker" or w == "oos":
                        print(f"{fam:7s} {en:22s} {xn:8s} {w:4s} {col[2:]:5s} {fmt(s)} | cap3 PF {sc.get('pf', np.nan):.2f} n {sc.get('n', 0)} {flag}")
    pk = pd.DataFrame(out)
    pk.to_csv(RES / "picks.csv", index=False)
    # years for picks (default exit, taker)
    print("\n== by year, picks, default + tuned exit, taker ==")
    for fam, (en, bx, flag) in picks.items():
        for xn in dict.fromkeys([DEFAULT_X, bx]):
            d = t[(t.e == E.index(en)) & (t.x == X.index(xn))]
            ys = d.groupby(d.t.dt.year).apply(lambda g: f"{len(g)}/{stats(g)['pf']:.2f}/{g.r_taker.sum():+.0f}R", include_groups=False)
            print(fam, en, xn, dict(ys))
    # exit grid for the A pick, IS vs OOS, taker
    print("\n== exit grid per pick (PF IS -> OOS, taker) ==")
    for fam, (en, bx, flag) in picks.items():
        ei = E.index(en)
        line = []
        for xn in X:
            d = t[(t.e == ei) & (t.x == X.index(xn))]
            a, b = stats(d[d.win == "is"]), stats(d[d.win == "oos"])
            line.append(f"{xn}:{a.get('pf', 0):.2f}->{b.get('pf', 0):.2f}")
        print(fam, en, " ".join(line))
    return t, E, X, picks, tab


if __name__ == "__main__":
    main()
