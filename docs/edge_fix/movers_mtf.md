# Movers playbook on 15m, 1h and 4h, as grids and as plain positions (30 Oct 2026)

Code: `research/movers/grid_mtf.py` (simulator), `fetch_15m.py` (data), `grid_report.py`. Data: Binance USDT-M 15m candles for every coin-month from 2022 to Sep 2026 that had a mover (24h >= +25% or <= -20%), 477 coins, delisted ones included, coins trading >= $5M a day. 4h and 1h bars are built from the 15m candles. Fills are simulated on the 15m path.

Trigger: the PARTI trade on 30 Oct (+105% pump, bars shrank under the peak, a short futures grid 0.048 to 0.063 with 181 grids at 5x, closed at the 1h midline, +13.85% on margin).

## Entries (each read on 15m, 1h and 4h bars)
* FADE: gainer, top of the last 12 bars >= 3 ATR above the midline, last 3 bars' range <= 0.7x the 3 before, SAR flipped down in the last 3 bars, price still >= 0.5 ATR above the midline.
* FADE0: same, but before the SAR flips (stretched and compressing only).
* DUMP: loser, SAR above price, below the midline, no midline touch for 12 bars.
* RUN: gainer, SAR under price, above the midline, no midline touch for 12 bars.

## Trades
* Grid: Pionex-style futures grid, 100 grids, 5x, 0.05% fee per fill. Fade range: from the midline minus 1.5 ATR up to the 12-bar high plus 0.5 ATR. Stop 1 ATR past the far edge, 72h max. Two exits: close at the midline (what you did) or hold.
* Plain position: same entries, stop, target and time limit.
* Baseline: random entries in the same mover windows, same rules.

## Results in R per trade (leverage independent)

| Setup | 15m | 1h | 4h | Random, same list |
|---|---|---|---|---|
| FADE, plain, exit at midline | PF 0.91 | PF 1.09 (IS 1.02, OOS 1.18) | n 8 | about 0.9 to 1.05 |
| FADE0, plain | 0.95 | 1.00 | 1.11 (IS 1.01, OOS 1.20) | about 0.86 to 0.99 |
| RUN, plain | 1.02 | 1.00 | 1.21 (IS 1.43, OOS 1.07) | 1.18 at 4h |
| DUMP, plain | 0.82 | 0.83 | 0.62 | 0.80 to 0.84 |
| Any setup as a grid | worse than plain on every row (PF 0.13 to 1.04 on margin) | | | |

Read:
* The fade back to the midline is right about 7 times in 10 on 15m and 1h. The 3 misses run to the stop and cost about as much as the 7 wins. That is why it feels like an edge: memory keeps the 7.
* On margin at 5x, some plain versions look very profitable (FADE 1h +10.6% per trade on margin, PF 1.46). That only happens because the stops sit about 22% away, past liquidation, so the simulation caps each loss at -100% and does not model being liquidated before the stop. Measured in R, it is break even.
* A grid on a directional idea is structurally worse than a plain position. Against you, it keeps adding size up to the full position before the stop. In your favour, it closes size as price moves your way. It only beats a plain position in true sideways chop.
* No version passes: nothing clears t >= 2 in both periods and beats the random baseline. RUN on the 4h passes in-sample only, and random entries on the same list did as well.
* PARTI was one of the 7 in 10. It was a good trade, but one trade cannot tell skill from the base rate.

## What this means for the system
* These definitions stay on the movers board as reading aids, not alerts, with the tested verdict next to each.
* Your discretion (what you skip, how you size, when you close) is the part a backtest of a rule cannot test. It gets tested on your own trades instead: every bot logged with its result in R. After 30 or more, we compare your picks with the rule's break-even base rate.
