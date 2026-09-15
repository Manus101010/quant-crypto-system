"""
SHELVED PROTOTYPE — market-neutral pairs. NOT wired into the scanner and arms
nothing. Failed the edge gate (pooled PF 0.80 on majors, 500d, net costs); parked
for a possible future range-bound regime, not for use now. Kept in the repo per
an explicit decision. Run manually only:
    ./venv/bin/python research/pairs_prototype.py

EXPLORATORY market-neutral PAIRS edge-gate (measurement only, not production).
Classic spread mean-reversion on liquid majors. Signal-only concept: when the
A/B log-spread stretches to |z|>=entry, long the cheap leg / short the rich leg,
exit on reversion to 0. Nets 2-leg costs. Uses the normal exchange chain (not
MEXC-pinned) so it runs during the MEXC outage.
"""
import sys, itertools
sys.path.insert(0, "/Users/manusmclaughlin/Desktop/claude-trading-sytem")
import numpy as np, pandas as pd
from utils.exchange import get_ohlcv_batch

MAJORS = ["ETH-USD","SOL-USD","BNB-USD","XRP-USD","ADA-USD","AVAX-USD","LINK-USD",
          "DOT-USD","LTC-USD","BCH-USD","ATOM-USD","UNI-USD","AAVE-USD","NEAR-USD",
          "APT-USD","ARB-USD","OP-USD","INJ-USD","SUI-USD","FIL-USD","ETC-USD",
          "DOGE-USD","TRX-USD","XLM-USD","ALGO-USD"]
LOOKBACK = 30
ENTRY_Z = 2.0
EXIT_Z = 0.5
STOP_Z = 4.0
MAX_HOLD = 20
COST_LEG = 0.36        # per leg round trip

def trade_pair(la, lb):
    spread = la - lb
    mean = spread.rolling(LOOKBACK).mean()
    sd = spread.rolling(LOOKBACK).std()
    z = (spread - mean) / sd
    n = len(z); trades = []
    i = LOOKBACK
    while i < n - 1:
        zi = z.iloc[i]
        if not np.isfinite(zi) or abs(zi) < ENTRY_Z:
            i += 1; continue
        side = -1 if zi > 0 else 1          # zi>0: A rich → short A/long B (side -1 on A)
        entry_a, entry_b = la.iloc[i], lb.iloc[i]
        exit_k = None
        for k in range(1, MAX_HOLD + 1):
            j = i + k
            if j >= n: break
            zj = z.iloc[j]
            if not np.isfinite(zj): continue
            if abs(zj) <= EXIT_Z or (side == -1 and zj <= 0) or (side == 1 and zj >= 0):
                exit_k = j; break
            if abs(zj) >= STOP_Z:
                exit_k = j; break
        if exit_k is None:
            exit_k = min(i + MAX_HOLD, n - 1)
        # log returns per leg; spread trade pnl = side*(dA - dB)
        da = (la.iloc[exit_k] - entry_a)
        db = (lb.iloc[exit_k] - entry_b)
        ret = side * (da - db) * 100          # ~% (log)
        ret -= 2 * COST_LEG                    # two legs
        trades.append({"ret_pct": ret, "win": ret > 0})
        i = exit_k + 1
    return trades

def pool(trades):
    if not trades: return (0, 0.0, 0.0)
    gw = sum(t["ret_pct"] for t in trades if t["ret_pct"] > 0)
    gl = abs(sum(t["ret_pct"] for t in trades if t["ret_pct"] <= 0))
    pf = (gw / gl) if gl > 0 else (99.0 if gw > 0 else 0.0)
    win = sum(t["win"] for t in trades) / len(trades) * 100
    return (len(trades), round(pf, 3), round(win, 1))

def main():
    data = get_ohlcv_batch(MAJORS, "1d", 500)
    logp = {s: np.log(df["close"]) for s, df in data.items() if len(df) > LOOKBACK + 40}
    print(f"coins with data: {len(logp)}")
    all_tr = []
    per_pair_pf = []
    for a, b in itertools.combinations(sorted(logp), 2):
        la, lb = logp[a].align(logp[b], join="inner")
        if len(la) < LOOKBACK + 40: continue
        tr = trade_pair(la, lb)
        if tr:
            all_tr += tr
            n, pf, win = pool(tr)
            if n >= 5: per_pair_pf.append(pf)
    n, pf, win = pool(all_tr)
    print(f"\nPAIRS edge-gate (majors, 500d, net 2x0.36%/trade):")
    print(f"  all pairs pooled: n={n} pf={pf} win={win}%  [{'PASS' if pf>1 and n>=25 else 'FAIL'}]")
    if per_pair_pf:
        arr = np.array(per_pair_pf)
        print(f"  per-pair PF (n>=5 pairs): {len(arr)} pairs, median {np.median(arr):.2f}, "
              f"%pairs PF>1: {(arr>1).mean()*100:.0f}%")

if __name__ == "__main__":
    main()
