# New edge hunt (28 Oct 2026)

Owner: NEW EDGE HUNT agent. Code: `research/edge_hunt/` (fetch_binance.py, harness.py, candidates.py, run.py, analyze.py). Full console output: `research/edge_hunt/results/analyze_output.txt`. No production file was touched.

## Verdict

**Nothing to recommend. No new candidate passes the edge gate out of sample.**

* I tested 7 candidate families in **81 variants**. Six were shortlisted in round 1 and one was added in round 2 after round 1 failed.
* Every variant chosen on in sample data failed out of sample (2025-07 to 2026-10).
* Most of them do no better than random entries with the same stop and exit.
* One post hoc observation, "short new listings on an opening range breakdown", deserves a forward paper log only. It was not the pre-registered pick. It falls short of the Bonferroni bar. And it went flat in 2026, which is the regime that matters.

The main lesson is about mechanics, and it explains why the intraday ideas keep failing in this repo. Structural stops on 1h or 4h sit 3% to 7% away. At the repo cost of 0.36% round trip, that costs **0.07R to 0.12R per trade**. The signals produce gross edges of -0.15R to +0.08R. Nothing in the 15m/1h/4h family clears the cost. For the $500 sleeve, the edge has to come from moves that are large relative to cost: daily structure, or multi day holds.

## 1. What was already tested (skipped)

I read research/*.py, research/overext, research/intraday, research/grid and docs/night/*.md. These were already covered and failed, so I did not retest them:
* exhaustion and overextension fades (NFI RSI, BB+RSI, z-score, volume climax, OI +30% with funding > 0)
* 1h breakdown and pullback trend shorts and longs (a random entry baseline already had PF 0.83)
* grids
* pairs
* daily momentum and Donchian longs
* oversold bounce longs
* inverse RSI-2 MR shorts
* funding, OI and L/S filters on DS and DBF
* GARCH regime sizing

Time series momentum on 4h was left out because it is the same rule family as the failed 1h breakdowns and the daily momentum longs. Funding carry and session or time of day effects were excluded per the brief. The quarter-hour effect paper ([Kim and Hansen 2026](https://arxiv.org/pdf/2607.09426)) reports about 0.5 bp of gross edge per boundary and says itself that this is far below costs.

## 2. Sources behind the candidates

| Idea | Source | Note |
|---|---|---|
| Perp funding and basis deviations, arbitrage | [He, Manela, Ross, von Wachter, Fundamentals of Perpetual Futures](https://arxiv.org/abs/2212.06888v2) | Deviations are large, co-move and shrink over time |
| High carry predicts crashes | [Schmeling, Schrimpf, Todorov, BIS WP 1087 "Crypto carry"](https://bis.org/publ/work1087.htm) | Basis for C2 (crowded longs via premium) |
| Short term reversal in illiquid coins, momentum in large ones | [Zaremba et al. 2021, IRFA](https://earsiv.medeniyet.edu.tr/items/23a96c9f-3952-4bdf-aec5-abafb3aaab70) | Basis for reversal style C3 and C5 |
| Intraday momentum | [Shen, Urquhart, Wang 2022, Financial Review](https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/) | Half hour horizon, no net-of-cost result |
| HF trend and seasonality | [Concretum: seasonality in BTC intraday trend](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/), [Catching Crypto Trends](https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/) | Sharpe 1.6 is **gross of fees**. The daily Donchian ensemble is long only, close to the deactivated live longs |
| Liquidation cascades | [Amberdata, leverage purge](https://blog.amberdata.io/the-leverage-purge-how-8.55b-in-liquidations-reset-the-market), [Axel Adler cascade guide](https://axeladlerjr.com/bitcoin-liquidation-cascades-guide/) | Descriptive only, no tested rule |
| Negative funding squeezes | [K33 on negative funding streaks](https://k33.com/research/articles/longest-streak-of-negative-funding-rates-in-the-2020s), [jlabs funding model thread](https://typefully.com/jlabsdigital/dissecting-funding-rate-model-BGOoArs) | Anecdotal |
| Failed breakout ("turtle soup") | Raschke and Connors, Street Smarts (classic) | No modern crypto evidence found |
| New listings drift down | [Messari via AMBCrypto: 2025 Binance listings -71% on average](https://ambcrypto.com/messari-data-shows-binances-2025-listings-down-71-on-average/), [Forklog study](https://forklog.com/en/study-reveals-binance-token-listings-as-investor-traps/), [Unchained / SwissBorg: 80% down since listing](https://unchainedcrypto.com/80-of-tokens-on-binance-are-down-since-listing-date-swissborg-researcher/) | These are buy and hold statistics. They ignore the cost of shorting (negative funding) and squeeze risk |
| Community strategies | [freqtrade-strategies forks](https://github.com/OnChainVibe/freqtrade-strategies), [pandianmn/freqtrade-strategies](https://github.com/pandianmn/freqtrade-strategies/blob/master/README.md) | The official repo page (github.com/freqtrade/freqtrade-strategies) was **blocked by the permission prompt** and not read |

Skepticism about GitHub and blog claims:
* Community freqtrade strategies are mostly backtest-only on today's survivor pairlists.
* Many use `informative` higher-timeframe merges without a shift, which is look-ahead: the 4h candle is used before it closes. The repo's earlier overext study already reproduced one of them (BB+RSI) and found PF 0.80.
* The Concretum HF trend numbers are gross of fees.
* The listing studies measure price from the listing day, but the first hours are untradeable. They also cannot be shorted for free: funding on new listings is often deeply negative.
* No Hummingbot or Jesse strategy was relevant. They are market making, arbitrage or educational examples with no evidence attached.

## 3. Data and method

* **Data.** Binance USDT perp archives (data.binance.vision; the Binance API returns 451 here), 2023-01 to 2026-10-26:
  * 1h klines with taker buy volume
  * funding
  * the 1h premium index
  * 5m open interest for the 60 most liquid coins
  * **Delisted symbols are included** (MATIC, EOS, RNDR, and dead small caps), so the universe is point in time.
  * MEXC and OKX could not supply this history: MEXC intraday stops at 2025-11, and OKX keeps 100 hourly OI rows and about 3 months of funding.
  * **Cross check against the cached MEXC 5m data** (8 coins, Nov 2025 to Oct 2026): median price gap 0.00% to 0.04%, 1h return correlation 0.998 to 0.9997, mean funding equal to within 1e-5. So Binance is a sound proxy for Bybit and MEXC.
  * October 2026 has no funding in the archive, so funding counts as 0 for those 4 weeks.
* **Universe.**
  * 486 crypto perps: listed on Bybit today, or delisted from Binance before Sep 2026. Binance's 2026 TradFi perps (oil, stocks, ETFs, gold) are excluded.
  * At each signal the coin must have at least 30 days of history and a trailing 30d average Binance volume of at least $10M a day.
  * New listings (C7) use the average volume since listing instead.
* **Costs.** 0.36% round trip (`backtesting/crypto_validation._COST_PCT`) plus real funding while open. Every table also shows PF at 0.20%.
* **Fills.**
  * Entry is at the close of the signal bar, and every feature uses closed bars only.
  * 4h and daily values are mapped to 1h only after their bar closes.
  * On 1h paths, the stop is checked before the target, and a gap through the stop fills at the open.
  * One trade per coin per variant at a time.
  * I hand checked one trade: entry, stop bar, funding sign and R all match.
* **Sizing.** 1R = $12.50 = 25% of $50 margin, so leverage = 0.25 / stop%. Stops tighter than 1.25% (above 20x) are skipped. Stops wider than 25% are skipped, except C7, where up to 50% is allowed (sized below 1x), the same rule as live DS since commit 57f1676.
* **Selection.**
  * Parameters were chosen only on 2023-02 to 2025-06.
  * Fixed rule per family: among variants with IS n >= 50 and both IS halves profitable, take the highest day clustered t.
  * The single pick per family was then run untouched on 2025-07 to 2026-10.
  * Edge gate: PF > 1, n >= 25, both halves profitable.
* **Multiple testing.** 81 variants: Bonferroni one sided 5% needs **IS t >= 3.23**. There are 7 OOS tests, so the OOS bar is **t >= 2.45**. The t stats are clustered by day, because same day trades are correlated.
* **Lead request: correlation.** Each pick also gets:
  * same day clustering: trades per day by direction, and the share of trades on days with more than 3
  * a cap of 3 trades per direction per day
  * BTC 4h trend alignment (longs only when BTC's last closed 4h bar is above its EMA20, shorts only below)
  * a random entry baseline: same coins, side, stop % and exit, at random OOS hours

## 4. Candidates (exact rules)

Shared stop and exits:
* Stop: structural, at the 24h swing or the signal bar extreme, plus 0.25 ATR(1h).
* Exits: T2R_48h (2R target or 48h), T1R_24h (1R target or 24h), trail_96h (breakeven at +1R, then trail 2 ATR(1h), 96h max).

| | Rule | Economic story |
|---|---|---|
| C1 FUNDNEG_LONG | Funding settles at or below -0.05% or -0.10% per 8h. Long at the print, or on the first 1h close above the prior high within 12h | Crowded shorts get squeezed |
| C2 PREM_SHORT | 8h mean premium of perp over index at or above +0.05% or +0.10%, coin below daily SMA50. Short on the first 1h close below the prior low within 12h | Crowded leveraged longs in a downtrend |
| C3 LIQ_LONG | 1h bar of -4 or -6 sigma (7d sigma of 1h returns), volume at least 5x the 7d average, taker buy share at or below 45%. Optional OI drop of at least 2% in the bar. Long at the close, or on the first green 1h bar within 6h | Forced selling overshoots |
| C4 COVER_SHORT | Price +6% or +10% over 24h while OI in coin units fell 3% or 6%. Coin below SMA50d and 4h EMA20 below EMA50. Short on the first 1h close below the prior low | A rally on short covering only fades |
| C5 SOUP_4H | 4h bar pierces the prior 20 or 55 bar low and closes back above it (long), or the mirror at the high (short) | Failed breakdowns trap late sellers |
| C6 ABSORB | Over 4h, taker buy share at or below 46% or 45% (about the 5th percentile in IS) on at least 2x volume, but price not down: long. Mirror (at least 53% or 54%, price not up): short | A passive limit buyer or seller absorbs the flow |
| C7 NEWLIST_SHORT (round 2) | Listings after 2023-01-15. Short at the 3 day mark, or on the first 4h close below the low of the first 24h or 72h, within 30 days. Stop above the 72h high. Exits: 2R or 14d, trail 4 ATR(1h) for 14d, or a plain 7d hold | Unlock and airdrop supply, low float with high FDV |

## 5. Results

Pre-registered picks. The IS columns are on the selection window; the OOS columns are untouched.

| Family | Pick (chosen on IS) | IS n / PF / t | OOS n | OOS PF | OOS exp R | OOS t | OOS halves R | OOS PF at 0.20% | Random baseline OOS PF | Gate |
|---|---|---|---|---|---|---|---|---|---|---|
| C1 | fund <= -0.10% confirm, trail | 2491 / 0.84 / -2.42 (IS FAIL) | 5082 | 0.80 | -0.104 | -4.30 | -320 / -208 | 0.86 | 0.81 | fail |
| C2 | prem8 >= 0.05%, trail | 4351 / 0.94 / -0.49 (IS FAIL) | 2803 | 0.93 | -0.031 | -1.17 | -13 / -74 | 1.00 | 0.89 | fail |
| C3 | 6 sigma, green bar entry, T1R | 1633 / 0.86 / -0.41 (IS FAIL) | 562 | 0.72 | -0.123 | -1.20 | -80 / +11 | 0.81 | 0.72 | fail |
| C4 | rally >= 10%, OI <= -6%, T2R | 342 / 0.78 / -0.80 (IS FAIL) | 165 | 0.62 | -0.246 | -1.50 | -27 / -14 | 0.67 | 1.00 | fail |
| C5 | soup55 long, T2R | 16531 / 0.76 / -2.58 (IS FAIL) | 11508 | 0.74 | -0.173 | -3.24 | -1237 / -751 | 0.81 | 0.73 | fail |
| C6 | absorb 0.45/0.54 short, T2R | 333 / 0.89 / -0.85 (IS FAIL) | 340 | 0.96 | -0.021 | -0.31 | -2 / -5 | 1.04 | 0.92 | fail |
| C7 | time3d, hold 7d | 175 / 1.55 / +1.57 (IS ok, but below 3.23) | 70 | 0.85 | -0.085 | -0.53 | -5 / -1 | 0.86 | 1.00 | fail |

Gross vs cost per OOS trade (median stop): C1 gross -0.107R vs cost 0.076R (stop 5.8%). C2 +0.023 vs 0.068 (6.9%). C3 -0.031 vs 0.097 (4.6%). C4 -0.150 vs 0.097 (4.0%). C5 -0.059 vs 0.121 (3.3%). C6 +0.080 vs 0.098 (4.2%). C7 -0.042 vs 0.021 (26%).

In the BTC bear subset (BTC below its 50d SMA) OOS, PF was 0.78, 0.87, 0.54, 0.60, 0.78, 1.04 and 0.81. **Nothing works better in the bear regime.** The exception is C6 at PF 1.04 on n 173, which is noise.

**Correlation views (lead request), OOS.** C1, C2 and C5 cluster heavily: 92% to 99% of their trades fall on days with more than 3 same-direction signals (C5 peaks at 285 in one day). C3 and C4 cluster on crash days (up to 51 and 27). C6 and C7 barely cluster (at most 8 and 3 a day). Neither the per day cap of 3 nor BTC 4h alignment rescues any pick:

| Pick | cap 3 PF (n) | BTC aligned PF (n) | cap 3 + aligned PF (n) | Gate |
|---|---|---|---|---|
| C1 | 0.79 (1356) | 0.76 (2016) | 0.75 (655) | fail |
| C2 | 0.89 (1355) | 0.94 (1354) | 0.85 (652) | fail |
| C3 | 0.66 (283) | 0.62 (161) | 0.87 (107) | fail |
| C4 | 0.98 (92) | 0.33 (55) | 0.78 (27) | fail |
| C5 | 0.76 (1307) | 0.83 (2267) | 0.84 (565) | fail |
| C6 | 1.02 (325) | 0.96 (171) | 1.04 (164), 2nd half -7.5R | fail |
| C7 | 0.85 (70) | 0.68 (40) | 0.68 (40) | fail |

Other OOS variants, shown for transparency and **not** used for selection: every variant of C1, C2, C4, C5 and C6 has OOS PF below 1. In C3 only "4 sigma + OI flush, green, T2R" (PF 1.23, n 198, first half -25R) and "6 sigma green T2R" (PF 1.04, first half -76R) exceed 1, and both have a losing half. In C7 the opening range variants look good OOS: orb72 trail PF 2.00 n 59, orb72 T2R PF 1.89 n 59, orb24 T2R PF 2.24 n 31.

### The one thing worth watching: C7 orb72 (post hoc, NOT recommended)

Rule: short a newly listed Bybit perp on the first 4h close below the low of its first 72h of trading, within 30 days of listing. The stop sits above the 72h high plus 0.25 ATR(1h). Exit at 2R or after 14 days.

| Window | n | PF | exp R | t |
|---|---|---|---|---|
| IS | 132 | 1.30 | +0.116 | 1.25 (first half -0.8R) |
| OOS | 59 | 1.89 | +0.297 | 1.96 (below the 2.45 bar) |

* About 1 trade a week, with almost no clustering (at most 3 a day).
* Median stop 33%, so the position runs at about 0.75x leverage ($12.50 risk at a 33% stop is about $38 notional).
* **But the OOS gain is all from Jul to Nov 2025** (listing mania, then the 10 Oct crash). In 2026 it made 22 trades for about -0.3R in total: flat.
* It was not the pre-registered pick. Across 81 variants, its OOS t of 1.96 is consistent with selection luck.
* It also carries real execution risk: new listings squeeze, funding is often deeply negative (the OOS funding drag was -0.02R per trade), and Bybit can raise margin on new contracts.

Verdict: do not trade it. If the lead wants it, log it as a **pre-registered forward paper signal** with exactly the rule above, and judge it after 25 or more closed signals.

## 6. Honest caveats

* Binance is a proxy for Bybit. The cross check says it is close, but Bybit liquidity is about a third of Binance's, so real slippage on small caps may be worse than 0.36%.
* The OI history covers only the 60 most liquid coins, so C3 with OI and C4 are large caps only.
* Signals that fire on the same day share one regime. The day clustered t stats account for that, but the halves test does not.
* October 2026 funding is missing. The effect is small: the funding term averages about ±0.01R per trade.
* What remains of the survivorship bias: the universe needs a coin to exist on Binance. Coins that only ever traded on Bybit are missing.

## 7. Recommendation to the lead

1. Add no new intraday setup. All 81 variants, 7 families and both directions fail. At 1h and 4h structure the cost (0.07R to 0.12R) is larger than any gross signal found.
2. Do not run reversal-style longs in this regime (negative funding, liquidation cascades, failed breakdowns). They lose more than random in BTC bear periods.
3. Optional: put C7 orb72 into the paper ledger as a pre-registered forward test, signal only and never taken. Keep its stop rule and its 50% stop cap.
4. Look for future edges on daily bars or with multi day holds, where cost is about 0.02R per trade. The live system's own daily shorts (DS, DBF) are the right family. Their 2026 decay is the problem to solve (see forensics.md), not the timeframe.

Reproduce:
```
python research/edge_hunt/fetch_binance.py h1          # ~15 min, 531 MB, all Binance USDT perps 2023-01..2026-10
python research/edge_hunt/fetch_binance.py oi 60       # ~28 min, 5m OI for the 60 most liquid coins
python research/edge_hunt/run.py                       # ~2 min, 739,758 trades across 81 variants
python research/edge_hunt/analyze.py                   # selection, OOS, baselines, clustering
```
