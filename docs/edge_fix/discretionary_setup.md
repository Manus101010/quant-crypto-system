# Your setup, tested with your exit (29 Oct 2026)

Owner: MY EDGE agent. Code: `research/my_edge/` (core.py, setups.py, run.py, analyze.py, baseline.py, mfe.py, case_evaa.py). Console output: `research/my_edge/results/analyze_output.txt` (universe $10M) and `research/my_edge/results_small/analyze_output.txt` (universe $2M). No production file was touched.

The setup in your words: "When something is extremely oversold or overbought it mean reverts aggressively. My edge is identifying it rolling over, or a super strong uptrend/downtrend. Narrow range (tight stop), a bit of high leverage, watch carefully. Once the coin is 3 to 4% in profit I turn on a 5% trailing limit stop loss."

## Verdict

| Version | Verdict | Why, in one line |
|---|---|---|
| A Rollover short after a run up | **Reject as a live setup.** Paper tag only, to measure your discretion (see section 9) | Best in sample pick: OOS PF 0.93 taker, 1.06 maker, n 105. Random shorts with the same stops and exit did better (PF 1.29). Pre 2023 holdout PF 0.49 |
| B Capitulation long (mirror) | **Reject** | Fails in sample: 0 of 540 variants have PF > 1. OOS pick PF 0.75 |
| C Trend pullback, long | **Reject** | Fails in sample: 0 of 60 variants have PF > 1. OOS pick PF 0.88 |
| C Trend pullback, short | **Reject** | IS PF 1.06 but the first IS half lost. OOS PF 0.94 taker, 1.10 maker, t 0.71. All the profit is in 2025 |

Your trailing exit does not rescue any of them. Across all 80 entry rules, swapping your trail for the old fixed 2R/48h target moves the median PF by less than 0.1, and usually down. The entries have almost no gross edge, so no exit can make them profitable. This is the same conclusion as the earlier overextension, intraday trend and new edge studies, now confirmed with your exit, both directions, three timeframes of trigger logic and both fee levels.

At maker fees (0.11% round trip) the best versions sit at break even (PF 1.0 to 1.1), not at an edge. The largest in sample t among all 1,360 variants at maker fees is 2.0. The Bonferroni bar is 3.96.

## 1. Rules tested (exact)

Entry is at the close of the trigger bar. Every feature uses closed bars only, and 4h values reach the 1h grid only after the 4h bar closes.

**A. Rollover short.** Two conditions, then a trigger.
* Ran up hard, with the peak inside the last 72h. Either:
  * percentage run up from the N day base to the peak: p20_3d (at least 20% over 3 days), p30_3d, p30_7d (your "30% in 7 days"), p50_7d
  * or the peak at least k ATR(4h) above the 4h EMA50: atr5, atr8
* Breakdown trigger, on 1h or 4h bars:
  * SW: first close below the lowest low of the prior 5 bars
  * EMA: first close below that timeframe's EMA20
  * LH: lower high confirmed. A pivot high (2 bars each side) after the peak and below it, then a close below the swing low between the peak and that pivot. The pivot is only usable once it is confirmed, 2 bars later
* Stop: the highest high of the last 3 trigger bars, plus 0.1 ATR(1h).
* Skip when the stop is tighter than 1% (more than 25x) or wider than 8% (not a "narrow range").

**B. Capitulation long.** The exact mirror: dumped p20_3d, p30_3d, p30_7d, p45_7d, atr5 or atr8 (trough inside the last 72h), then a reclaim trigger (SW, EMA or a higher low confirmed), with the stop below the local low.

**C. Strong trend pullback, both directions.**
* Trend: 4h close above EMA20, EMA20 above EMA50, EMA50 rising over 6 bars, and 7 day return at least +10% or +25%. Shorts mirror this with -10% or -20%.
* Pullback: the low of the last 3 1h bars touched the 1h EMA20 (or the 4h EMA20).
* Entry: the first 1h close above the prior 1h high and above the 1h EMA20.
* Stop: the 6h pullback low, minus 0.1 ATR(1h).

**Exit (yours).**
* Initial stop as above.
* Once the best price reaches +ACT% in your favour, a TRAIL% trailing stop follows the best price. This is Bybit native: it sits next to the initial stop and the tighter of the two applies.
* ACT is 0 (on from entry), 1, 2, 3 or 4%. TRAIL is 3, 5 or 7%. That is 15 combinations. Yours is act3_tr5.
* 7 day time stop.
* For comparison only: the fixed exits the earlier studies used, T2R_48h (2R target or 48h) and T1R_24h.
* "3 to 4% in profit" is read as the coin's price moving 3 to 4%, not ROE on margin. At 10x to 25x, 3% ROE would be a 0.1% to 0.3% price move, which is inside the spread of the trigger bar.

**Fills.**
* 1h path. The stop is checked first each hour at the level known at the start of the bar, and a gap through it fills at the open.
* The bar's extreme then updates the best price. If the bar closed beyond the new trail level, the trail was certainly hit inside that bar and the trade exits there.
* A wick through the new level that closes back inside is assumed not hit. That is slightly optimistic for your exit.

**Measurement.**
* R: 1R is the distance to the initial stop, R = (price move - cost + funding) / stop%. Leverage does not change R.
* % per trade is also shown (price %, not ROE).

**Costs.**
* Taker: 0.36% round trip, the repo standard.
* Maker ish: 0.11%, a limit entry plus a taker stop exit plus slippage.
* Funding: real Binance prints (shorts receive positive funding). October 2026 has no funding in the archive.

**Data.**
* Binance USDT perps 1h, 2021-06 to 2026-10-26, with delisted coins (LUNA, FTT era, MATIC, SRM and dead small caps).
* Crypto perps only: on Bybit today, or delisted. 496 symbols.
* Point in time universe: 30 day average Binance volume of at least $10M a day (about $3M on Bybit), and at least 30 days listed.
* Sensitivity run at $2M.

**Selection.** Pre registered and written in `analyze.py` before any OOS number was seen.
* Windows: IS 2023-01 to 2025-06, OOS 2025-07 to 2026-10, and an extra untouched pre IS holdout from 2021-08 to 2022-12.
* Step 1: with your exit act3_tr5 at taker cost, the entry with the highest day clustered IS t, among entries with IS n of at least 50 and both IS halves profitable.
* Step 2: the trail combination with the highest IS t for that entry.

**Multiple testing.**
* 80 entries x 17 exits = **1,360 variants**. Bonferroni one sided 5%: **IS t of at least 3.96**.
* OOS: 4 families x 2 exits = 8 tests, so **OOS t of at least 2.50**.
* t statistics are clustered by day.

One detector fix was made before any results were read. In LH, the swing low first included the peak bar's own low. A giant pump bar's low is not the swing low of the roll over, and the live EVAA chart showed it, so the fix excludes the peak bar. A pivot that confirms after price is already below the swing also fires.

## 2. Landscape (taker, your trail exits only, variants with n of at least 30)

| Family | Window | Variants | Share PF > 1 | Median PF | Best PF | Median signals/week |
|---|---|---|---|---|---|---|
| A | IS | 540 | 8% | 0.83 | 1.42 | 33.9 |
| A | OOS | 540 | 5% | 0.86 | 1.12 | 45.6 |
| B | IS | 540 | 0% | 0.61 | 0.90 | 19.8 |
| B | OOS | 540 | 4% | 0.75 | 1.05 | 26.1 |
| C long | IS | 60 | 0% | 0.73 | 0.81 | 63.3 |
| C long | OOS | 60 | 0% | 0.80 | 0.93 | 64.7 |
| C short | IS | 60 | 28% | 0.95 | 1.11 | 64.8 |
| C short | OOS | 60 | 27% | 0.87 | 1.32 | 84.5 |

At maker fees, the share of variants with PF > 1 is A 38% IS / 48% OOS, B 1% / 13%, C long 0% / 8%, C short 68% / 52%. That is a coin flip around break even, not an edge.

## 3. Pre registered picks

Your exit act3_tr5, plus the IS tuned trail. Format: taker / maker.

| Family | Pick | Exit | Pre IS 2021-22 PF (n) | IS PF (n), t | OOS n | OOS PF taker / maker | OOS exp R taker / maker | OOS % per trade | OOS t | OOS halves R | Signals/week OOS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | atr8, LH, 4h | act3_tr5 (yours) | 0.49 (30) | 1.31 (120), +0.87 | 105 | 0.93 / 1.06 | -0.029 / +0.022 | -0.01% / +0.24% | -0.24 | +4 / -7 | 1.5 |
| A | atr8, LH, 4h | act4_tr5 (tuned) | 0.53 (30) | 1.42 (119), +1.21 | 103 | 0.83 / 0.93 | -0.080 / -0.030 | -0.22% / +0.03% | -0.63 | +4 / -13 | 1.5 |
| B | p45_7d, EMA, 4h (IS FAIL) | act3_tr5 | 0.62 (173) | 0.85 (163), -0.45 | 515 | 0.75 / 0.85 | -0.116 / -0.064 | -0.62% / -0.37% | -1.11 | -56 / -3 | 7.5 |
| B | same | act0_tr5 (tuned) | 0.56 (186) | 0.88 (171), -0.38 | 546 | 0.81 / 0.93 | -0.078 / -0.026 | -0.39% / -0.14% | -0.98 | -47 / +5 | 7.9 |
| C long | y25, 4h EMA20 (IS FAIL) | act3_tr5 | 0.71 (528) | 0.72 (1563), -2.67 | 1043 | 0.88 / 0.99 | -0.062 / -0.006 | -0.25% / 0.00% | -1.29 | -3 / -61 | 15.1 |
| C long | same | act4_tr3 (tuned) | 0.77 (523) | 0.81 (1537), -1.71 | 1019 | 0.93 / 1.05 | -0.033 / +0.022 | -0.01% / +0.24% | -0.81 | +13 / -47 | 14.8 |
| C short | y10, 4h EMA20 (IS FAIL, first half lost) | act3_tr5 | 0.86 (3031) | 1.06 (7266), +0.46 | 4996 | 0.94 / 1.10 | -0.028 / +0.046 | +0.01% / +0.26% | -0.44 | +86 / -227 | 72.4 |
| C short | same | act4_tr3 (tuned) | 0.91 (2968) | 1.11 (7112), +0.83 | 4907 | 0.97 / 1.12 | -0.017 / +0.057 | -0.03% / +0.22% | -0.34 | +35 / -120 | 71.1 |

Not one IS t comes near 3.96 and not one OOS t comes near 2.50. Every pick fails the edge gate OOS at taker cost. At maker cost, A and C short show PF 1.06 to 1.12 with t below 1.1 and one losing half: noise.

By year (A pick, your exit, taker; n / PF / total R):

| 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|
| 8 / 0.40 / -2R | 22 / 0.52 / -5R | 49 / 0.92 / -2R | 51 / 2.32 / +20R | 74 / 0.94 / -2R | 51 / 0.70 / -6R |

The whole in sample result is 2024. C short's whole result is 2025 (PF 1.20, +532R across many clustered trades). In 2026, every year line in every family has PF below 1.

## 4. The version closest to your words, and trade frequency

A with "up at least 30% in 7 days" and each trigger. Your exit, OOS, taker / maker:

| Trigger | Signals/week | PF taker / maker | exp R taker / maker | Median stop | Trades per active day (max) | Share on days with more than 3 | Cap 3/day/direction: per week, PF taker / maker |
|---|---|---|---|---|---|---|---|
| SW 1h | 228 | 0.84 / 0.97 | -0.081 / -0.015 | 4.3% | 32.6 (209) | 100% | 21.0, 0.87 / 0.99 |
| EMA 1h | 258 | 0.87 / 1.00 | -0.074 / +0.002 | 3.8% | 36.8 (292) | 100% | 21.0, 0.81 / 0.93 |
| LH 1h | 113 | 0.84 / 0.96 | -0.082 / -0.018 | 4.5% | 16.2 (172) | 100% | 20.8, 0.82 / 0.93 |
| SW 4h | 47 | 0.81 / 0.91 | -0.078 / -0.034 | 6.2% | 7.0 (114) | 90% | 18.3, 0.80 / 0.91 |
| EMA 4h | 55 | 0.86 / 0.99 | -0.060 / -0.006 | 5.4% | 8.0 (97) | 93% | 19.3, 0.81 / 0.92 |
| LH 4h | 29 | 0.95 / 1.08 | -0.020 / +0.030 | 5.8% | 4.6 (105) | 76% | 15.2, 0.88 / 1.00 |
| A pick (atr8 LH 4h) | 1.5 | 0.93 / 1.06 | -0.029 / +0.022 | 5.9% | 1.2 (6) | 6% | 1.5, 0.89 / 1.02 |

**Frequency is not the problem; edge is.** The loose versions give 20 to 250 signals a week. But they arrive in clusters: on alt dumps, 100 to 290 coins roll over the same day, so they are one bet on the market, not many bets. With a cap of 3 a day per direction, that is 15 to 21 trades a week, and every capped version has PF 0.80 to 0.88 at taker cost and about 0.92 to 1.00 at maker cost. The only rare, unclustered version (atr8, 1.5 a week) is the pick, and it failed OOS.

## 5. Your exit vs fixed targets (median PF across all entries in each family, taker)

| Family | Window | T1R_24h | T2R_48h | act0_tr3 | act1_tr5 | act2_tr5 | **act3_tr5 (yours)** | act4_tr5 | act3_tr7 | act4_tr3 |
|---|---|---|---|---|---|---|---|---|---|---|
| A | pre | 0.80 | 0.84 | 0.73 | 0.74 | 0.72 | 0.73 | 0.77 | 0.79 | 0.83 |
| A | IS | 0.80 | 0.87 | 0.78 | 0.81 | 0.82 | 0.82 | 0.85 | 0.83 | 0.88 |
| A | OOS | 0.86 | 0.94 | 0.73 | 0.84 | 0.84 | 0.86 | 0.89 | 0.90 | 0.90 |
| B | OOS | 0.73 | 0.76 | 0.73 | 0.76 | 0.77 | 0.77 | 0.78 | 0.72 | 0.79 |
| C long | OOS | 0.78 | 0.82 | 0.75 | 0.80 | 0.80 | 0.82 | 0.82 | 0.80 | 0.84 |
| C short | OOS | 0.93 | 1.00 | 0.80 | 0.87 | 0.88 | 0.89 | 0.91 | 0.95 | 0.91 |

* **Turning the trail on earlier makes it worse, not better.** act0 and act1 are the lowest columns. A 3% trail from entry on coins whose 1h noise is 3% to 5% just stops you out on noise.
* The fixed 2R/48h target is as good as or better than your trail in every family OOS.

Why the trail does not help: the activation arithmetic.
* With a 5% trail switched on at +3%, the trail sits at about -2.15% from entry when it starts. It only locks in profit once the best move passes about +5.3%.
* For the A pick (median stop 5.6%), the share of trades reaching each level before the initial stop (pre IS, IS and OOS, n 225): +1% 88%, +2% 77%, **+3% 69%**, +4% 59%, **+5.3% 52%**, +8% 43%, +10% 36%, +15% 25%. Median best move 5.5%.
* So about 1 trade in 6 gets activated and then gives the move back, exiting at a small loss or scratch instead of a full stop. Roughly half lock in profit, but the 5% retrace then caps them, often near +3% to +6%.
* That reshapes the distribution (win rate 41% to 45%, tiny average) but does not create expectancy, because the entries' gross edge is about zero. Random entries in the same coins with the same stops and exit (3 draws per trade) score:

| Pick, exit | IS real PF | IS random PF | OOS real PF | OOS random PF |
|---|---|---|---|---|
| A, act3_tr5 | 1.31 | 0.90 | 0.93 | **1.29** |
| A, act4_tr5 | 1.42 | 1.07 | 0.83 | 0.87 |
| B, act3_tr5 | 0.85 | 0.95 | 0.75 | 1.02 |
| C long, act3_tr5 | 0.72 | 0.74 | 0.88 | 0.95 |
| C short, act3_tr5 | 1.06 | 1.03 | 0.94 | 0.89 |
| C short, act4_tr3 | 1.11 | 0.99 | 0.97 | 0.91 |

OOS, random shorts beat the rollover short. In a falling 2025-26 alt market, any short with your exit does about as well as the pattern.

**Tight stops do not change it** (all A entries pooled, your exit, PF taker / maker):

| Stop | 1% to 2% | 2% to 3% | 3% to 5% | 5% to 8% |
|---|---|---|---|---|
| IS | 0.77 / 0.94 | 0.85 / 0.99 | 0.82 / 0.94 | 0.76 / 0.85 |
| OOS | 0.83 / 1.02 | 0.82 / 0.97 | 0.89 / 1.02 | 0.87 / 0.98 |

A tighter stop cuts the dollar loss per stop at high leverage, but it also gets hit more often, and in R it is the same zero edge. Cost per trade in R is higher with a tight stop: 0.36% on a 1.5% stop is 0.24R.

**Smaller coins make it worse.** Universe at $2M Binance volume (about $0.7M on Bybit), which includes EVAA type coins: A pick OOS PF 0.66 taker / 0.76 maker, n 236, t -2.17, 2026 PF 0.58 (n 159, -32R). Pumped small caps pump again more often.

## 6. Live case study: EVAAUSDT, 27 to 28 Oct 2026

The Binance cache ends 26 Oct, so the bars are MEXC public 1h and 5m, cross checked against Bitget (same 1.6000 high at 15:00 UTC). Files: `research/my_edge/data/`, script `case_evaa.py`, result `results/case_evaa.csv`. Times are UTC. "29 Oct ~23:00 Sydney" in the message must mean **28 Oct 23:00 Sydney = 28 Oct 12:00 UTC**: as of the time of writing it is 29 Oct 08:53 Sydney.

Chart:
* Flat base around 0.49 to 0.52 from 21 to 27 Oct.
* 27 Oct 13:00: the pump starts.
* High 1.4269 at 28 Oct 07:00 (MEXC; your Bybit 1.4323). That is +190% from the 7 day base.
* The 4h bar from 08:00 to 12:00 closed red at 1.3123, under the high. On 5m, 1.28 printed at 11:50 to 12:05.
* 12:20: flush to 1.1616.
* Bounce to 1.3528 by 14:00.
* **New high 1.6008 at 15:55**, and again 1.6000 at 20:00. Last close 1.4478 at 22:00.

| Version A rule | What it did on EVAA |
|---|---|
| Run up condition | Met by every A definition (+190% in under 2 days, far above 8 ATR(4h) over the 4h EMA50) |
| SW 1h / 4h | **Did not trigger.** The prior 5 bars include the pump bar lows (1.0292 at 07:00), so price never closed below the swing low |
| EMA20 1h / 4h | **Did not trigger.** The 1h EMA20 was 1.08 to 1.11 at the time, so closes (lowest 1.2087) stayed above it. The 4h EMA20 was 0.85 to 0.96, so no 4h close came near it |
| LH 4h | **Did not trigger.** No confirmed lower high on 4h yet |
| LH 1h | **Triggered at 14:00 close, 1.2656** (pivot high 1.3833 at 11:00 confirmed). Stop 1.3833 + 0.1 ATR = 1.4022 = **10.8% away, above the 8% "narrow range" cap, so it is skipped.** Had it been taken, it would have been stopped at 15:00 for -1.03R (-11.2%) with any exit |
| Universe | EVAA's 30 day Binance volume was $3.3M a day, below the $10M universe, so the production scanner would not even look at it |

Your discretionary trade, simulated on 5m:
* Short about 1.2822 (12:05 close), stop above the local high 1.3833 plus a buffer, about 1.39 (8.4%).
* +3% (1.2437) reached at 12:10, so the trail is on.
* Best 1.1616 inside the 12:20 bar, so the trail sits at 1.2197. That bar closed at 1.2289, above the level, so the trail was hit inside the same 5 minutes: out at **1.2197, +4.9% price, about +0.54R after taker cost.**
* With the stop above the 1.4323 Bybit high (12% away), the same exit is about +0.38R.
* Holding with only a stop, any stop under 1.60 was hit at 15:55 for -1R.

So **your exit worked on this one**: the 9% flush paid you before the second leg, and the trail got you out ahead of the squeeze to 1.60. But this chart is also the general failure mode in miniature. The mechanical triggers either do not fire (giant pump bars wreck swing and EMA levels) or fire late with a wide stop into the next leg up, which is exactly what the earlier overext study found on ORCA. One win in a hand picked chart is not evidence. The table in section 3 is the evidence, and it is flat.

## 7. Comparison with what was already tested

| Study | Entry | Exit | Result | Same conclusion? |
|---|---|---|---|---|
| research/overext (REPORT.md) | 15m/1h turn after 3 ATR above 4h+1h EMA20, z score, NFI, BB+RSI, volume climax, OI +30% | Target 4h EMA20 / 48h; trail 2 ATR(1h) | Core PF 0.76 (n 14,833); best PF 1.14, t 1.72 vs 3.21 needed | Yes. Their best trailing variant was also the worst (PF 0.91) |
| research/intraday_trend.py (research/intraday/REPORT.md) | 1h breakdown and 4h trend pullback, both sides | 2 ATR stop, 2R/48h; trail 2 ATR | Every variant PF 0.69 to 0.89; random baseline PF 0.83 | Yes. C here is that family with your exit: still PF 0.73 to 0.95 |
| research/mr_shorts.py | Daily inverse RSI-2 shorts below the 200 SMA | 2 ATR stop / 3R / 15 bars | Failed the gate | Yes |
| docs/edge_fix/new_edges.md (C1 to C7) | Funding, premium, liquidation, soup, absorb, new listings | T2R_48h, T1R_24h, trail 2 ATR | 81 variants, nothing passed OOS; "gross edge of 15m/1h/4h signals -0.15R to +0.08R, cost 0.07R to 0.12R" | Yes, and this study adds the maker fee case: still no edge |
| docs/night/features.md | Daily DS and DBF with filters | Setup specific | DS decays into 2026 | Consistent: every 2026 line here has PF below 1 |

**Why the trailing exit did not change the conclusion.** The earlier studies used fixed targets (2R, the 4h EMA20) or ATR trails, so the open question was whether your trail captures the "aggressive" part of a mean reversion that a fixed target cuts off. It does not.
* In the 25% of A trades that run 15% or more, the 5% trail captures the move.
* But those trades are offset by the roughly 30% of trades that never reach +3% and take the full stop.
* They are also offset by the trades that activate and then retrace 5%, since a 5% retrace on a coin with 3% to 5% hourly noise comes quickly.
* The exit grid in section 5 shows the trail ranking near the fixed target, both IS and OOS. The entry is the problem, not the exit.

## 8. Biases and limits

* **1h bars.** A wick through the new trail level that closes back inside is assumed not hit, which is optimistic for your exit. A 5m check on a few EVAA type trades would be needed to size this. Everything still fails, so the bias does not change the verdict.
* **Binance as a Bybit proxy.** It was cross checked in new_edges.md (1h return correlation 0.998). It is not exact on spikes.
* **Survivorship.** Delisted coins are included, which reduces survivor bias. Funding for October 2026 is missing, so it is counted as 0.
* **The rules are a codification of a discretionary read.** Your eye may filter out the bad cases that a rule takes. The test cannot see that, which is why the paper tag below exists. The point is to measure your filter, not to trade the rule.

## 9. What to build (if anything)

Nothing goes live. If the lead wants a measurement tool, add a paper only **"Your setup (rollover short)"** tag to the scanner. It is not an alert to trade and it does not count toward the risk caps. The purpose is to compare the trades you actually take against the mechanical version on the same days. If your taken trades beat the tag by a clear margin over 50 or more trades, your discretion is the edge, and we then try to codify what you saw.

Detector, exactly as the pick (A|atr8|LH|4h):
1. On 1h bars, the 72h max of (high - 4h EMA50) / ATR14(4h) is at least 8. Both 4h values come from the last closed 4h bar.
2. On closed 4h bars: peak = the highest high in the last 18 4h bars. Take the latest pivot high (high at least the 2 bars before it, and above the 2 bars after it) that comes after the peak bar and sits below the peak. Swing low = the lowest low from the bar after the peak through the pivot.
3. Fire on the 4h close that is below the swing low, when the previous close was not below it or the pivot was confirmed on this bar.
4. Stop: the highest high of the last 3 4h bars, plus 0.1 ATR14(1h). Skip if the stop is under 1% or over 8%.

Exit: yours. Initial stop. Once the best price is 3% in profit, a 5% Bybit trailing stop from the best price. 7 day time stop. Log it at both fee levels.

Expect about 1.5 tags a week, rarely more than one a day.
