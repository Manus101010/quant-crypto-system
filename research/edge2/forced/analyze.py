import sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, "/home/claude/quant-crypto-system/research/my_edge")
import core as C

BASE = Path("/tmp/claude-0/-home-claude/f9afb357-b96a-5c99-93e3-0ac2bb39e920/scratchpad/edge2/forced")
df = pd.read_parquet(BASE / "trades.parquet")
WEEKS = {"IS": (C.IS_END - C.IS_START).days / 7, "OOS": (pd.Timestamp("2026-10-26") - C.IS_END).days / 7}


def st(g, cost):
    r = ((g["net"] - cost) / g["sp"]).to_numpy()
    n = len(r)
    if n == 0:
        return dict(n=0)
    pos, neg = r[r > 0].sum(), -r[r < 0].sum()
    t = r.mean() / r.std(ddof=1) * np.sqrt(n) if n > 1 and r.std() > 0 else NAN
    rs = r[np.argsort(g["t"].to_numpy(), kind="stable")]
    mx = cur = 0
    for x in rs:
        cur = cur + 1 if x <= 0 else 0
        mx = max(mx, cur)
    return dict(n=n, PF=round(pos / neg, 2) if neg else np.inf, avgR=round(r.mean(), 3), win=round((r > 0).mean(), 3),
                t=round(t, 2), maxLS=mx)


NAN = float("nan")
lines = []
for uni in ("all", "pionex"):
    d = df if uni == "all" else df[df.pionex]
    for v in ("V1", "V2", "V3", "V4", "V5"):
        for pr in ("IS", "OOS"):
            s = d[(d.v == v) & (d.per == pr)]
            sig = s[s.kind == "sig"]
            rnd = s[s.kind == "rand"]
            for cname, cost in C.COSTS.items():
                a = st(sig, cost)
                # random: mean over reps of avgR and PF; share of reps whose avgR >= signal avgR
                reps = [st(g, cost) for _, g in rnd.groupby("rep")]
                ravg = np.mean([x["avgR"] for x in reps]) if reps else NAN
                rpf = np.median([x["PF"] for x in reps]) if reps else NAN
                pbeat = np.mean([x["avgR"] >= a.get("avgR", NAN) for x in reps]) if reps else NAN
                lines.append(dict(uni=uni, v=v, per=pr, cost=cname, **a, perwk=round(a["n"] / WEEKS[pr], 2),
                                  rand_avgR=round(ravg, 3), rand_PF=round(rpf, 2), p_rand=round(pbeat, 2)))
    for pr in ("IS", "OOS"):
        s = d[(d.v == "V6") & (d.per == pr)]
        for cname, cost in C.COSTS.items():
            for kind, g in (("DS_all", s), ("DS_noflush", s[s.kind == "noflush"]), ("DS_flush", s[s.kind == "flush"])):
                a = st(g, cost)
                lines.append(dict(uni=uni, v=kind, per=pr, cost=cname, **a,
                                  perwk=round(a["n"] / WEEKS[pr], 2) if a["n"] else 0))
out = pd.DataFrame(lines)
out.to_csv(BASE / "results.csv", index=False)
pd.set_option("display.width", 220, "display.max_rows", 200)
print(out.to_string(index=False))
