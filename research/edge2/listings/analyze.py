from pathlib import Path
import numpy as np
import pandas as pd
import sys
sys.path.insert(0, "/home/claude/quant-crypto-system/research/my_edge")
import core as C  # noqa

OUT = Path(__file__).resolve().parent
df = pd.read_parquet(OUT / "trades.parquet")
ctl = pd.read_parquet(OUT / "controls.parquet")


def per(t):
    return np.where(t < C.IS_START, "PRE", np.where(t < C.IS_END, "IS", "OOS"))


df["period"] = per(df.t)
MONTHS = {"PRE": 19.0, "IS": 30.0, "OOS": (C.DATA_END - C.IS_END).days / 30.44}


def tstat(r):
    return r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if len(r) > 2 else np.nan


def ctstat(r, t):
    m = r.groupby(t.dt.to_period("M")).sum()
    n = len(r)
    # clustered SE of the mean: sqrt(sum of squared cluster sums of demeaned) / n
    d = (r - r.mean()).groupby(t.dt.to_period("M")).sum()
    se = np.sqrt((d ** 2).sum()) / n
    return r.mean() / se


def pf(r):
    lo = -r[r < 0].sum()
    return r[r > 0].sum() / lo if lo > 0 else np.inf


def maxdd(r, order):
    eq = r.loc[order.sort_values().index].cumsum()
    return (eq.cummax() - eq).max()


rows = []
for cost_name, cost in C.COSTS.items():
    ctl["R"] = (ctl.net0 - cost) / ctl.stop_pct
    btc = ctl[ctl.rep == -1].set_index("ti")["R"]
    rnd = ctl[ctl.rep >= 0]
    rnd_mean = rnd.groupby("ti")["R"].mean()
    df["R"] = (df.net0 - cost) / df.stop_pct
    for uni in ("pionex", "all"):
        for v in sorted(df.variant.unique()):
            g0 = df[(df.variant == v) & ((df.pionex) if uni == "pionex" else True)]
            for p in ("PRE", "IS", "OOS", "IS+OOS"):
                g = g0[g0.period.isin(["IS", "OOS"])] if p == "IS+OOS" else g0[g0.period == p]
                if len(g) < 5:
                    continue
                r = g.R
                b = btc.reindex(g.index)
                rm = rnd_mean.reindex(g.index)
                rr = rnd[rnd.ti.isin(g.index)]
                rep_means = rr.groupby("rep")["R"].mean()
                months = MONTHS["IS"] + MONTHS["OOS"] if p == "IS+OOS" else MONTHS[p]
                rows.append(dict(cost=cost_name, uni=uni, var=v, per=p, n=len(g), per_month=round(len(g) / months, 1),
                                 pf=round(pf(r), 2), avgR=round(r.mean(), 3), win=round((r > 0).mean(), 2),
                                 t=round(tstat(r), 2), t_clu=round(ctstat(r, g.t), 2),
                                 maxddR=round(maxdd(r, g.exit_t), 1),
                                 rnd_avgR=round(rm.mean(), 3), rnd_p95=round(rep_means.quantile(0.95), 3),
                                 t_vs_rnd=round(tstat((r - rm).dropna()), 2),
                                 btc_avgR=round(b.mean(), 3), t_vs_btc=round(tstat((r - b).dropna()), 2),
                                 med_stop=round(g.stop_pct.median() * 100, 1),
                                 lev_med=round(min(5, 0.25 / g.stop_pct.median()), 2),
                                 capped=round(g.capped.mean(), 2),
                                 avg_move=round(g.net0.mean() * 100, 2)))
S = pd.DataFrame(rows)
S.to_csv(OUT / "summary.csv", index=False)
pd.set_option("display.width", 250, "display.max_rows", 500, "display.max_columns", 30)
print(S[S.cost == "taker"].drop(columns="cost").to_string(index=False))

# verdicts
print("\nVERDICTS (taker)")
for v in sorted(df.variant.unique()):
    ok_all = True
    notes = []
    for uni in ("pionex", "all"):
        s = S[(S.cost == "taker") & (S.uni == uni) & (S["var"] == v)].set_index("per")
        if not {"IS", "OOS", "IS+OOS"} <= set(s.index):
            ok_all = False
            continue
        c = [s.loc["IS", "t"] >= 2, s.loc["OOS", "t"] >= 2, s.loc["IS+OOS", "t"] >= 2.64,
             s.loc["IS+OOS", "t_vs_rnd"] >= 2, s.loc["IS+OOS", "t_vs_btc"] >= 2,
             s.loc["IS+OOS", "avgR"] > s.loc["IS+OOS", "rnd_p95"]]
        notes.append(f"{uni}:{''.join('Y' if x else 'n' for x in c)}")
        ok_all &= all(c)
    print(v, "PASS" if ok_all else "FAIL", " ".join(notes), "(IS t, OOS t, pooled t>=2.64, vs rnd, vs btc, >rnd p95)")
