"""
Selection in sample, untouched out of sample test, baselines and splits.

Run: python research/edge_hunt/analyze.py   (after run.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as H                                       # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
RNG = np.random.default_rng(20261028)


def table(tr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for v, g in tr.groupby("variant"):
        s = H.stats(g)
        s["variant"] = v
        s["cand"] = g["cand"].iat[0]
        rows.append(s)
    return pd.DataFrame(rows).set_index("variant")


def select(is_tab: pd.DataFrame) -> dict:
    pick = {}
    for cand, g in is_tab.groupby("cand"):
        ok = g[(g["n"] >= 50) & (g["h1"] > 0) & (g["h2"] > 0)]
        if len(ok):
            pick[cand] = (ok["t_day"].idxmax(), True)
        else:
            pick[cand] = (g["t_day"].idxmax(), False)
    return pick


def random_baseline(trades: pd.DataFrame, variant: str, draws: int = 3) -> pd.DataFrame:
    ex = H.EXITS[variant.split(" | ")[1]]
    rows = []
    for sym, g in trades.groupby("sym"):
        df = H.load(sym)
        if df is None:
            continue
        df["atr1h"] = H.atr(df, 14)
        A = H.arrays(df)
        lo = df.index.searchsorted(H.IS_END)
        hi = len(df) - 100
        uni = H.universe_ok(df)
        cand = np.flatnonzero(uni[lo:hi]) + lo
        if len(cand) == 0:
            continue
        for _, t in g.iterrows():
            for _ in range(draws):
                i = int(RNG.choice(cand))
                c = A["close"][i]
                if not np.isfinite(c):
                    continue
                stop = c * (1 - t["side"] * t["stop_pct"])
                r = H.simulate(A, i, int(t["side"]), stop, ex)
                if r:
                    r.pop("exit_j")
                    rows.append(r)
    return pd.DataFrame(rows)


def cost_adj(g: pd.DataFrame, new_cost: float) -> pd.DataFrame:
    g = g.copy()
    g["r"] = g["r"] + (H.COST - new_cost) / g["stop_pct"]
    return g


def main():
    tr = pd.read_parquet(OUT / "trades.parquet")
    n_var = tr["variant"].nunique()
    IS, OOS = tr[~tr["oos"]], tr[tr["oos"]]
    ist = table(IS)
    ist.to_csv(OUT / "is_table.csv")
    print(f"variants tried: {n_var}")
    pd.set_option("display.width", 250)
    cols = ["n", "win", "pf", "exp", "t_day", "h1", "h2", "per_wk"]
    print("\n== IN SAMPLE (2023-02 .. 2025-06) ==")
    print(ist.sort_values(["cand", "t_day"], ascending=[True, False])[cols].round(3).to_string())
    # Bonferroni on IS t across all variants (one sided)
    t_bonf = sps.norm.isf(0.05 / n_var)
    print(f"\nBonferroni one sided 5% over {n_var} IS variants needs t >= {t_bonf:.2f}")
    pick = select(ist)
    t_oos = sps.norm.isf(0.05 / len(pick))
    print(f"OOS: {len(pick)} selected tests, Bonferroni one sided 5% needs t >= {t_oos:.2f}\n")
    res = []
    oost = table(OOS)
    oost.to_csv(OUT / "oos_all_variants.csv")
    for cand, (v, ok) in sorted(pick.items()):
        g = OOS[OOS["variant"] == v]
        s = H.stats(g)
        si = ist.loc[v].to_dict()
        line = {"cand": cand, "variant": v, "is_ok": ok, "is_n": si["n"], "is_pf": si["pf"], "is_t": si["t_day"]}
        line.update({f"oos_{k}": s.get(k) for k in ("n", "win", "pf", "exp", "tot", "t_day", "h1", "h2", "per_wk", "fund_r", "lev_med", "maxdd")})
        line["oos_gate"] = H.gate(s)
        line["oos_bonf"] = bool(s.get("t_day", 0) >= t_oos)
        g20 = cost_adj(g, 0.0020)
        line["oos_pf_cost020"] = H.stats(g20).get("pf")
        line["oos_pf_bear"] = H.stats(g[g["btc_bear"] == True]).get("pf")   # noqa: E712
        line["oos_n_bear"] = int((g["btc_bear"] == True).sum())             # noqa: E712
        line["oos_pf_bybit"] = H.stats(g[g["on_bybit"]]).get("pf")
        line["oos_pf_2026"] = H.stats(g[g["entry_t"] >= "2026-01-01"]).get("pf")
        line["oos_n_2026"] = int((g["entry_t"] >= "2026-01-01").sum())
        res.append(line)
        print(f"{cand} [{'IS ok' if ok else 'IS FAIL'}] {v}")
        print("   IS :", H.fmt(H.stats(IS[IS['variant'] == v])))
        print("   OOS:", H.fmt(s), "| gate", line["oos_gate"], "| bonf", line["oos_bonf"])
        print(f"   OOS PF at 0.20% cost {line['oos_pf_cost020']:.2f} | BTC bear PF {line['oos_pf_bear']} (n {line['oos_n_bear']}) "
              f"| Bybit listed PF {line['oos_pf_bybit']:.2f} | 2026 PF {line['oos_pf_2026']} (n {line['oos_n_2026']})")
    pd.DataFrame(res).to_csv(OUT / "oos.csv", index=False)
    # baselines for selected variants
    print("\n== random entry baseline (same coins, side, stop %, exit; OOS window) ==")
    for cand, (v, ok) in sorted(pick.items()):
        g = OOS[OOS["variant"] == v]
        if len(g) == 0:
            continue
        b = random_baseline(g, v)
        print(f"{cand} {v}\n   random: {H.fmt(H.stats(b)) if len(b) else 'n 0'}")
    # OOS view of every variant (to show selection did not hide a better / worse one)
    print("\n== OOS all variants (for transparency, NOT used for selection) ==")
    print(oost.sort_values(["cand", "t_day"], ascending=[True, False])[cols].round(3).to_string())


if __name__ == "__main__":
    main()
