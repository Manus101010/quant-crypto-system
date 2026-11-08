"""PRE-REGISTERED (written before any outcome was looked at), 6 variants, K=5.
Pool each day 00:00 UTC: Pionex listed (Binance 1000X mapped), Binance dvol30 >= $10M, age >= 30d,
prior 24h return from closed 1h bars. Entry = close of 23:00 bar (= 00:00 open). One position per coin.
 V1 SHORT top5 gainers, 24h hold, fixed 8% stop, time exit.
 V2 SHORT top5 gainers, 72h hold, stop prior 24h high +1% (clipped 3..20%), time exit.
 V3 V1 but only gainers with prior 24h funding sum > 0.03% (above neutral 0.01%/8h = crowded longs);
    candidates = top10 gainers, take the first 5 that pass.
 V4 V1 inside the mid liquidity tercile of the day's pool only.
 V5 LONG bottom5 losers, 24h hold, 8% stop, only when BTC daily close > its 50d SMA.
 V6 Portfolio: short top5 + long bottom5, equal weight (0.5 gross each side), 24h, no stop; daily returns.
Pass: daily clustered t IS >= 2.64 (Bonferroni 6, two sided 0.05) and OOS t >= 2.0, beats random
(p < 0.05 vs 200 random draws from the same pool, same exits) in IS and OOS.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/quant-crypto-system/research/my_edge")
import core as C
OUT = Path(__file__).resolve().parent
P = pd.read_parquet(OUT / "panel.parquet")
K = 5; NR = 200; rng = np.random.default_rng(11)
IS = lambda t: (t >= C.IS_START) & (t < C.IS_END)
OOS = lambda t: t >= C.IS_END

btc = P[P.sym == "BTCUSDT"].set_index("t").sort_index()
btc_up = (btc.px > btc.px.rolling(50).mean())
P = P[P.t >= C.IS_START - pd.Timedelta(days=1)]

def pool(df, universe="pionex"):
    m = df.dvol >= C.MIN_DVOL
    m &= df.pionex if universe == "pionex" else (df.in_uni | df.pionex)
    d = df[m & df.r24.notna()].copy()
    d["terc"] = d.groupby("t").dvol.transform(lambda x: pd.qcut(x.rank(method="first"), 3, labels=False) if len(x) >= 3 else 1)
    return d

def select(d, spec, side, k=K, rule=None, rand=False, seed=None):
    """Return selected rows. spec in A,B,L. rule(df_day)->filtered candidates ordered."""
    jcol = spec + "_j"; out = []; busy = {}
    r = np.random.default_rng(seed) if rand else None
    for t, g in d.groupby("t", sort=True):
        g = g[[busy.get(s, t) <= t for s in g.sym]]
        if rule is not None:
            g = rule(g)
            if g is None or not len(g):
                continue
        g = g[g[spec + "_net"].notna()]
        if rand:
            pick = g.iloc[r.permutation(len(g))[:k]] if len(g) else g
        else:
            pick = (g.sort_values("r24", ascending=(side == 1))).head(k)
        for s, j in zip(pick.sym, pick[jcol]):
            busy[s] = j
        out.append(pick)
    return pd.concat(out) if out else d.iloc[:0]

def R(sel, spec, cost):
    return (sel[spec + "_net"] - cost) / sel[spec + "_sp"]

def stats(sel, spec, cost):
    r = R(sel, spec, cost); t = sel.t
    res = {}
    for nm, m in (("IS", IS(t)), ("OOS", OOS(t))):
        rr = r[m]; tt = t[m]
        if len(rr) < 5:
            res[nm] = None; continue
        w, lo = rr[rr > 0].sum(), -rr[rr < 0].sum()
        daily = rr.groupby(tt).mean()
        st = (rr > 0).astype(int).values; streak = mx = 0
        for v in st:
            streak = streak + 1 if v == 0 else 0; mx = max(mx, streak)
        mon = rr.groupby(tt.dt.to_period("M")).sum()
        weeks = (tt.max() - tt.min()).days / 7
        res[nm] = dict(n=len(rr), pf=round(w / lo, 2) if lo else np.inf, avgR=round(rr.mean(), 3),
                       win=round((rr > 0).mean(), 3),
                       t_trade=round(rr.mean() / rr.std(ddof=1) * np.sqrt(len(rr)), 2),
                       t_day=round(daily.mean() / daily.std(ddof=1) * np.sqrt(len(daily)), 2),
                       per_wk=round(len(rr) / weeks, 1), maxLstreak=mx,
                       worst_mo=f"{mon.idxmin()} {mon.min():.1f}R")
    return res

def rand_test(d, spec, side, k, rule_pool, cost, real):
    """Random K coins from the same eligible pool, same day, same exits. 24h specs: vectorised
    (no overlap possible). 72h spec: loop with the same one position per coin rule, 40 draws."""
    vals = {"IS": [], "OOS": []}
    dd = rule_pool(d) if rule_pool else d
    dd = dd[dd[spec + "_net"].notna()]
    r_all = ((dd[spec + "_net"] - cost) / dd[spec + "_sp"]).to_numpy()
    isv, oosv = IS(dd.t).to_numpy(), OOS(dd.t).to_numpy()
    nd = NR if spec != "B" else 40
    for s in range(nd):
        if spec == "B":
            sel = select(dd, spec, side, k, rand=True, seed=s); r = R(sel, spec, cost)
            vals["IS"].append(r[IS(sel.t)].mean()); vals["OOS"].append(r[OOS(sel.t)].mean())
        else:
            u = pd.Series(np.random.default_rng(s).random(len(dd)), index=dd.index)
            pick = (u.groupby(dd.t).rank(method="first") <= k).to_numpy()
            vals["IS"].append(r_all[pick & isv].mean()); vals["OOS"].append(r_all[pick & oosv].mean())
    out = {}
    for nm in ("IS", "OOS"):
        v = np.array(vals[nm]); x = real[nm]["avgR"] if real[nm] else np.nan
        out[nm] = dict(rand_avgR=round(v.mean(), 3), p=round((v >= x).mean(), 3))
    return out

def fmt(name, cost, s, rt=None):
    lines = []
    for nm in ("IS", "OOS"):
        x = s[nm]
        if x is None:
            lines.append(f"{name:28s} {cost:5s} {nm:3s} n<5"); continue
        rr = f" rand {rt[nm]['rand_avgR']:+.3f} p={rt[nm]['p']:.3f}" if rt else ""
        lines.append(f"{name:28s} {cost:5s} {nm:3s} n={x['n']:5d} PF={x['pf']:.2f} avgR={x['avgR']:+.3f} win={x['win']:.2f} "
                     f"t={x['t_trade']:+.2f} tday={x['t_day']:+.2f} wk={x['per_wk']} Lstk={x['maxLstreak']} worst={x['worst_mo']}{rr}")
    return lines

def funding_rule(g):
    g = g[g.A_net.notna()].sort_values("r24", ascending=False).head(10)
    return g[g.f24 > 0.0003]

def mid(g):
    return g[g.terc == 1]

if __name__ == "__main__":
    d = pool(P)
    rep = []
    V = {
        "V1 short top5 24h 8%":   dict(spec="A", side=-1, rule=None, rpool=None),
        "V2 short top5 72h hi24": dict(spec="B", side=-1, rule=None, rpool=None),
        "V3 V1 + funding>0.03%":  dict(spec="A", side=-1, rule=funding_rule, rpool=lambda x: x[x.f24 > 0.0003]),
        "V4 V1 mid tercile":      dict(spec="A", side=-1, rule=mid, rpool=lambda x: x[x.terc == 1]),
        "V5 long bot5 BTC>50d":   dict(spec="L", side=1, rule=None, rpool=None, btc=True),
    }
    for name, v in V.items():
        dd = d[d.t.map(btc_up).fillna(False)] if v.get("btc") else d
        sel = select(dd, v["spec"], v["side"], K, rule=v["rule"])
        sel.to_parquet(OUT / f"trades_{name.split()[0]}.parquet")
        for cn, cost in C.COSTS.items():
            s = stats(sel, v["spec"], cost)
            rt = rand_test(dd, v["spec"], v["side"], K, v["rpool"], cost, s) if cn == "taker" else None
            rep += fmt(name, cn, s, rt)
    # BTC control
    b = d.iloc[:0]
    bb = P[P.sym == "BTCUSDT"]
    for spec, nm in (("A", "CTRL BTC short 24h 8%"), ("B", "CTRL BTC short 72h hi24"), ("L", "CTRL BTC long 24h 8%")):
        sel = bb[bb[spec + "_net"].notna()]
        if spec == "B":
            sel = select(bb, "B", -1, 1)
        rep += fmt(nm, "taker", stats(sel, spec, C.COSTS["taker"]))
    # V6 portfolio
    def port(dd, k, cost):
        rows = []
        for t, g in dd[dd.raw.notna()].groupby("t"):
            if len(g) < 2 * k: continue
            g = g.sort_values("r24")
            lo, hi = g.head(k), g.tail(k)
            sh = (-hi.raw + hi.rawf - cost).mean(); lg = (lo.raw - lo.rawf - cost).mean()
            rows.append((t, 0.5 * sh + 0.5 * lg, sh, lg))
        return pd.DataFrame(rows, columns=["t", "ret", "short", "long"]).set_index("t")
    def pstats(pr, label):
        out = []
        for nm, m in (("IS", IS(pr.index)), ("OOS", OOS(pr.index))):
            x = pr[m]
            for col in ("ret", "short", "long"):
                y = x[col]
                sh = y.mean() / y.std() * np.sqrt(365); t = y.mean() / y.std() * np.sqrt(len(y))
                mon = (1 + y).groupby(y.index.to_period("M")).prod() - 1
                out.append(f"{label:28s} {nm:3s} {col:5s} days={len(y)} mean={y.mean()*1e4:+.1f}bp/d Sharpe={sh:+.2f} t={t:+.2f} worst_mo={mon.idxmin()} {mon.min()*100:+.1f}%")
        return out
    for cn, cost in (("gross", 0.0), *C.COSTS.items()):
        pr = port(d, K, cost); pr.to_csv(OUT / f"v6_daily_{cn}.csv")
        rep += pstats(pr, f"V6 portfolio K5 {cn}")
    # random portfolio baseline (taker): random 5 short, random 5 long -> is the long/short split vs random
    # equivalent to zero expected; report quick 50 draws mean Sharpe
    # diagnostics
    rep.append("--- diagnostics (not pass variants) ---")
    for k in (3,):
        sel = select(d, "A", -1, k); rep += fmt(f"D short top{k} 24h 8%", "taker", stats(sel, "A", C.COSTS["taker"]))
        sel = select(d, "B", -1, k); rep += fmt(f"D short top{k} 72h hi24", "taker", stats(sel, "B", C.COSTS["taker"]))
    for tc in (0, 1, 2):
        sel = select(d, "A", -1, K, rule=lambda g, tc=tc: g[g.terc == tc])
        rep += fmt(f"D V1 tercile {tc} (0=low)", "taker", stats(sel, "A", C.COSTS["taker"]))
        sel = select(d, "B", -1, K, rule=lambda g, tc=tc: g[g.terc == tc])
        rep += fmt(f"D V2 tercile {tc} (0=low)", "taker", stats(sel, "B", C.COSTS["taker"]))
    sel = select(d, "L", 1, K); rep += fmt("D long bot5 24h no BTC filt", "taker", stats(sel, "L", C.COSTS["taker"]))
    sel = select(d, "A", -1, K, rule=lambda g: g[g.f24 > 0]); rep += fmt("D V1 funding>0 (any)", "taker", stats(sel, "A", C.COSTS["taker"]))
    sel = select(d, "A", -1, K, rule=lambda g: g.sort_values("r24", ascending=False).head(10).query("f24 <= 0.0003"))
    rep += fmt("D V1 top10 funding<=0.03%", "taker", stats(sel, "A", C.COSTS["taker"]))
    du = pool(P, "all")
    sel = select(du, "A", -1, K); rep += fmt("D V1 full univ incl delisted", "taker", stats(sel, "A", C.COSTS["taker"]))
    rep += pstats(port(du, K, C.COSTS["taker"]), "D V6 full univ taker")
    txt = "\n".join(rep); print(txt); (OUT / "report.txt").write_text(txt)
