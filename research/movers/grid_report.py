"""Compact read of grid_mtf results: signal vs random, per timeframe, both periods."""
import pandas as pd
from pathlib import Path

R = Path(__file__).resolve().parent / "results"
t = pd.read_csv(R / "grid_mtf_summary.csv")
pd.set_option("display.width", 250, "display.max_rows", 500)
for ex in ("his", "hold", "dir_his"):
    x = t[t.exit == ex].pivot_table(index=["setup", "tf"], columns=["period", "kind"],
                                    values=["n", "pf", "avg_roe"], aggfunc="first")
    print(f"\n=== exit {ex} ===")
    print(x.round(2).to_string())
