# Live forensics: why the live record lost (8 to 28 Oct 2026)

Script: `research/live_forensics.py` (fetch, funding, replay, diagnose). Cache and outputs were written to the
scratchpad (`FORENSICS_CACHE`), nothing in production was touched.

## 0. Headline

* **The real ledger was recoverable.** The nightly `track-admin` workflow uploads `track_export.json` (every
  trigger row) as a GitHub artifact, and the repo is public. The 27 Oct 21:17 UTC export reproduces the Telegram
  record exactly: 7 closed, 1 win (14%), -4.056R; taken 2 closed (CAKE +0.50R manual, LINK -1R), -0.50R; 6 open
  (BLESS, SPX, UNI, BTC, ETHFI, PENDLE). Fetch it with the GitHub API
  (`/repos/Manus101010/quant-crypto-system/actions/artifacts?name=track-export`).
* **All 7 closed losses are Momentum Runner LONGS fired 10 to 12 Oct**, not shorts. No Distribution Short (DS)
  had closed when the record was quoted; BLESS (DS) closed afterwards at -0.84R.
* That burst was much bigger than the record shows: **35 long signals (34 coins) fired in 48 hours**, 28 of them were later given
  status `over_cap` (not in any code path in the repo) and so left out of the record. Re-simulated with the
  production exit code they scored **-20.9R over 25 closed, 0 wins** (3 still open). The system's true paper result
  for the long burst is about **-26R on 32 closed longs, 0 paper wins** (CAKE's +0.50R was the trader's manual exit;
  the paper exit would have been -1R).
* The DS book (6 trades) is too young to judge: BLESS -0.84R closed, the other five marked -0.01R to -0.31R. But it
  is one correlated bet, two of the six are not the setup the research describes, and the DS "validation" in
  `data/crypto_validation.json` was edited by hand into an internally impossible record.

## 1. Match quality (replay vs real ledger)

The replay drives the production code unchanged (`skills.scanner._run_from_bybit`, `skills.new_setups.detect`,
`triggers.scan.run_scan_and_arm`, `monitor._evaluate`, `utils.overext.measure`, `triggers.outcomes._simulate`) on
MEXC perp candles fetched through `utils.exchange` exactly as a US host does (Bybit 403, saved
`data/bybit_perps.json`, 476 of 523 coins resolve to a MEXC perp). Only the stores and clocks are swapped: an in
memory trigger table, forming daily bars rebuilt from 1h candles at each scan slot (19:50, 00:05, 04:00 UTC), 15
minute polls on 1h prices, OKX funding history (the venue the live funding chain reaches).

Inferred config (git history starts at 57f1676 on 25 Oct): until the 12 Oct 19:51 scan, about 14 armed per scan and
no concurrent cap; then top_n 5, MAX_OPEN_POSITIONS 10 and the `over_cap` clean up; DS off the validated list until
18 Oct ("Approved 18 Oct 2026" note); DS 50% stop from 25 Oct 08:15 UTC. The export starts at trigger id 450
(10 Oct 19:51), ids 1 to 449 are gone, so the comparable window starts there.

| measure | ledger | replay | overlap |
|---|---|---|---|
| counted trades (status fired) | 13 | 13 | **12** (CAKE in ledger, AVAX in replay) |
| Distribution Short trades | 6 | 6 | **6 of 6, same scan slot** (BLESS 24 Oct 19:50, SPX 26 Oct 00:05, UNI/BTC/ETHFI 27 Oct 00:05, PENDLE 27 Oct 04:00) |
| fired incl. over_cap | 40 | 56 | 38 of 40 |
| armed (slot, coin, setup) | 81 | 89 | 55 |
| closed result | 7, -4.06R (CAKE manual +0.50) | 7, -5.33R, 0 wins | same trades except CAKE/AVAX |

Exit fidelity: re-running `outcomes._simulate` on our candles reproduces every closed ledger trade to the third
decimal (TAO -1, ETHFI -0.486, ZEC -0.075, DOT -1, KAS -1, LINK -1) and BLESS's later close (-0.844R trail vs
Telegram -0.84R). Residual arming differences are in the 10 to 12 Oct burst only (ranking among ~60 tied momentum
candidates; the macro deployment score that scales conviction is unknown; 1h granularity for breakout fills; the
12 Oct scan ran at 00:20, not 00:05). From 13 Oct the replay and the ledger agree scan by scan, including the slots
that armed nothing.

Counterfactual with today's config over the whole window (`--era current`: top_n 5, cap 10, DS validated
throughout): 10 longs fire 10 to 12 Oct, 9 closed, **0 wins, -7.28R** (incl. BLESS). The cap shrinks the burst, it
does not fix it.

## 2. Per trade

R from the ledger (resim = production exit on our data). MFE/MAE from 1h bars, fire to exit (or now). BTC trend:
1h and 4h = close vs EMA20 vs EMA50 on closed bars; 1d = `new_setups.btc_trend`. Breadth = % of the breadth
universe above its 50d SMA (closed bars).

| coin | setup | fired (UTC) | entry vs signal close | stop % / ATR | exit | R | MFE R | MAE R | BTC 1h/4h/1d | BTC vs 50d | breadth | 5d / 30d coin ret before |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TAO | MomRunner L | 10 Oct 20:46 | +4.6% | 14.7% / 2.0 | stop d15 | -1.00 | 0.34 | 1.07 | UP/MIXED/UP | +2.9% | 71% | -9.7% / +8.2% |
| ETHFI | MomRunner L | 10 Oct 20:46 | +2.9% | 21.2% / 1.9 | time d15 | -0.49 | 0.43 | 0.67 | UP/MIXED/UP | +2.9% | 71% | -10.2% / +8.6% |
| ZEC | MomRunner L | 11 Oct 01:21 | +0.5% | 15.2% / 1.8 | time d15 | -0.08 | 0.75 | 0.96 | UP/DOWN/UP | +2.6% | 77% | -8.7% / +13.1% |
| DOT | MomRunner L | 11 Oct 04:31 | -1.7% | 14.8% / 2.0 | stop d5 | -1.00 | 0.25 | 1.03 | MIXED/DOWN/UP | +2.5% | 77% | +2.2% / +14.8% |
| KAS | MomRunner L | 11 Oct 04:31 | -1.4% | 12.9% / 1.8 | stop d5 | -1.00 | 0.54 | 1.17 | MIXED/DOWN/UP | +2.5% | 77% | -6.2% / +15.4% |
| CAKE (taken) | MomRunner L | 11 Oct 20:46 | +2.6% | 11.3% / 2.0 | manual | +0.50 (paper -1) | 0.41 | 0.09* | UP/MIXED/UP | +3.5% | 77% | -8.0% / +7.5% |
| LINK (taken) | MomRunner L | 12 Oct 20:15 | -2.2% | 11.3% / 1.8 | stop d7 | -1.00 | 0.10 | 1.03 | DOWN/DOWN/UP | +2.4% | 77% | -4.4% / +15.5% |
| BLESS | DS short | 24 Oct 19:51 | +2.7% | 24.8% / 3.2 | trail d5 (after export) | -0.84 | 0.16 | 0.90 | DOWN/DOWN/MIXED | -1.6% | 14% | +7.0% / -15.3% |
| SPX | DS short | 26 Oct 00:21 | -0.1% | 27.3% / 3.5 | open | mark -0.31 | 0.10 | 0.36 | DOWN/DOWN/MIXED | -2.1% | 10% | -5.2% / -22.7% |
| UNI | DS short | 27 Oct 00:06 | +0.2% | 26.1% / 3.5 | open | mark -0.01 | 0.12 | 0.03 | DOWN/DOWN/MIXED | -2.1% | 12% | -4.0% / -26.3% |
| BTC | DS short | 27 Oct 00:06 | +0.1% | 9.0% / 3.5 | open | mark -0.11 | 0.10 | 0.15 | DOWN/DOWN/MIXED | -2.1% | 12% | -4.7% / -5.1% |
| ETHFI | DS short | 27 Oct 00:06 | +0.4% | 29.7% / 3.4 | open | mark -0.06 | 0.09 | 0.11 | DOWN/DOWN/MIXED | -2.1% | 12% | -8.2% / -10.6% |
| PENDLE | DS short | 27 Oct 04:01 | -1.3% | 27.9% / 3.7 | open | mark -0.13 | 0.01 | 0.16 | DOWN/DOWN/MIXED | -2.5% | 12% | -9.5% / -24.0% |

\* CAKE window ends at the manual exit (11 h). Funding at fire was ordinary on every trade (+0.005% to +0.010% per
8h on OKX, KAS/CAKE/BLESS not listed); the crowding veto never triggered in 54 replayed scans.

DS anatomy at the signal bar:

| coin | ret 120d | close vs 200d | from 120d high | OI (coin) 3d before close, OKX | pre-registered OI filter |
|---|---|---|---|---|---|
| UNI | +145% | +55% | -35% | -1.3% | skip |
| BTC | +35% | +10% | -8% | +5.7% | take |
| ETHFI | +94% | +34% | -20% | +10.4% | take |
| PENDLE | +55% | +15% | -30% | +5.2% | take |
| SPX | +5% | **-7%** | **-47%** | -11.7% | skip |
| BLESS | +3% | **-5%** | **-74%** | n/a | n/a |

## 3. Root causes, ranked

**1. One correlated long bet at a market top (all of the -4.06R; about -26R including the hidden signals).**
10 to 12 Oct the scans armed up to 14 longs each (7 to 14) (Momentum Runner and Relative Strength Leader, 7 + 7 per scan via
`_diversify`'s 50% ceiling) with no concurrent cap, and `breakout_long` fires at +0.5% (scan.py:452), so nearly
everything armed fired: 35 longs in 48 hours. BTC had topped on 4 Oct (86.5k) and was only 2.4% to 3.5% above its
50d; alt breadth had already fallen from 95% (25 Sep) to 54% (8 Oct), bounced to 71 to 77% and then broke to 51%
(12 Oct) and under 20% by 18 Oct. The long gate (BTC above 200d and 50d, breadth >= 60%) was open, but every input
was rolling over: BTC 4h trend was DOWN or MIXED at 6 of 7 counted fires and the coins had already fallen 4% to 10%
in the 5 days before entry (Momentum Runner is a 3 month state label, not an entry event). Over the hold the 34 coins
moved together (mean pairwise 1h correlation 0.71), the basket fell 12.5% on average (33 of 34 down) while BTC fell
3.4% (alt beta about 1.5 to 2). 32 closed paper longs, 0 paper wins.

**2. No follow through, not a give back.** Counted longs: median MFE 0.41R, best 0.75R (ZEC, after 10 days), none
reached +1R; the 3R target (6 ATR, roughly 35% to 45% in 15 days) was never in reach; 4 of 7 hit the full -1R stop,
2 timed out red. MAE before MFE was small (median 0.09R): trades went slightly green, then the market fell. Exits
did not lose money that entries had made; entries had no edge in that regime. Momentum Runner's own validation was
thin to begin with (PF 1.206, +0.09R, 39% win on 5,436 backtest trades, not regime conditioned) and it was later
deactivated by the decay watch.

**3. The record hid most of the damage.** 28 of the 35 fired longs were re-statused `over_cap` and are excluded by
`live_stats` (outcomes.py:288 counts only `status == "fired"`). Their paper result: 25 closed, 0 wins, -20.9R. The
live verdict "early, -4.06R" understated a much clearer negative signal.

**4. Distribution Short live: too early to judge, but the inputs are weak.**
* n = 6, one closed. The four of 26/27 Oct are a single bet: mean 1h correlation 0.58, alt beta to BTC 2.04 to 2.23,
  all fired within 4 hours with BTC itself one of them. A 5% BTC squeeze moves the whole book against you together.
* Two of six (BLESS, SPX) are not "ran up hard and went quiet": they were below their 200d SMA, 47% and 74% under
  their 120d high, with 120d returns of +3% to +5%. They qualified only through the lagging `sma50 > sma200` branch
  of `post_up` (new_setups.py:91), i.e. a coin that pumped and dumped months ago. BLESS is the loss.
* Stops of 26% to 30% (3.5 ATR on coins with 7.5% to 8.6% daily ATR) mean +1R needs a 27% fall; the live trail is
  the same distance from the best low, so it locks nothing until a crash. Payoff is a lottery ticket by design,
  which needs many trades to judge, and the research behind it is negative in 2026 (n 42, -0.47R, brief).
* The pre-registered OI filter (OI in coin units up over the prior 3 days) would have skipped UNI and SPX.
* The 25% cap acted as a "wait for a bounce" filter on BLESS: excluded at 00:05 and 04:00 on 24 Oct (stop 28%),
  armed at 19:50 after a 2.7% bounce made the stop 24.8%.

**5. The DS validation record is not a real measurement.** `data/crypto_validation.json` "stats" for DS say n 40,
PF 1.754, but in the same record exits sum to 62 (stop 51, time 11), avg_ret is -10.9% and expectancy_r is -0.4154,
which cannot coexist with PF 1.754; `recommended` (computed in the same run) says n 62, PF 0.225, win 24%. A note
says it was approved by hand on 18 Oct from weekly revalidation PF 1.90 / 1.75 and research/bear_shorts.py. The edge
gate trusts `validated`, so DS is live on a hand edit. The replay confirms DS was off the list before that date: the
detector fired on XMR (12 Oct), GIGGLE (13 Oct) and TRX (15 Oct) and none of them armed in the ledger.

**6. The short side barely exists live.** In 54 replayed scans: Downtrend Bounce Fade 0 detections (needs BTC
"MIXED"; BTC was "UP" until 21 Oct), Breakdown Short (55d low) 0 detections (see B10), Relative Weakness Short
(PF 0.48) is the only frequent short label and is not validated. So once the long gate closed, the live system was
DS only, which is why the book became four DS on one night.

## 4. Bugs and live vs backtest differences (no production file edited)

| # | severity | where | what | proposed fix |
|---|---|---|---|---|
| B1 | high (record) | outside code; outcomes.py:288 | 28 fired signals set to `over_cap` after the fact and dropped from live stats (-20.9R, 0 wins) | never re-status fired signals; if a cap is added, flag the rows and report them separately |
| B2 | high (gate) | data/crypto_validation.json | DS stats hand edited, internally contradictory (n 40 vs 62 exits; PF 1.754 with negative avg_ret and expectancy) | regenerate from a reproducible run; make the edge gate read computed stats only, overrides in a separate audited file |
| B3 | medium | config.py:124-125, outcomes.py:98-100, 130-138 vs backtesting/crypto_optimize.py:206-207 | DS has no `BYBIT_TRAIL` entry, so paper tracking trails at the full initial risk distance from the best intraday LOW from bar one; the research trails `close + 3.5 x ATR_entry` off the CLOSE. BLESS: live closed -0.84R on day 5, the research rule would still be open (mark -0.89R) | add `"Distribution Short": {"k_atr": 3.5, "activate_r": 0.0}` and re-validate DS under the exact live exit (or make `_simulate` use the plan's close based trail) |
| B4 | medium | new_setups.py:109, scan.py:111-116, monitor.py:461-473 | stop is fixed from the signal bar close but entry is the live price at arm time; the signal stays valid all next day, so 19:50 and 04:00 scans enter 4 to 20 hours after the close the research used (BLESS +2.7%, PENDLE -1.3%). The drift guard is one sided (monitor.py:470 only rejects a >3% move down) | arm new_setups signals only at the 00:05 close scan, or recompute stop = entry + 3.5 x ATR at arm time; add an upper drift bound |
| B5 | medium | skills/scanner.py:1105-1148 vs new_setups.py:127 | generic setups (Momentum Runner, RSL, Breakdown Short...) are classified on the still forming daily candle (price, SMA, RSI, Donchian, volume ratio all include the partial bar); `new_setups.latest` drops it and every backtest uses closed bars. Measured: 2 of 34 fired longs had a different label on the last closed bar (UNI, WIF) | drop the forming bar in `_run_from_bybit` the same way `latest()` does |
| B6 | medium | triggers/scan.py:452, 454 | `breakout_long` fires at ref x 1.005 for state labels (Momentum Runner, RSL) that the backtest entered at the close; with up to 14 armed per scan this turned a scan into a basket buy | fire momentum labels only on a real event (close above a level) or at the close as tested |
| B7 | low | skills/scanner.py:757-781, 806; triggers/scan.py:318 | DS and Fade have no `_SETUP_BASE`, so base 25: they rank below every long, never show in the 60 row candidate list, and lose slot races when longs are allowed | add bases from their validation |
| B8 | low | monitor.py:336, outcomes.py:221 | leverage is floored with `int()`: BTC DS (9% stop) gets 2x and risks $9.45 (0.76R); stops 12.5% to 24.5% get 1x and risk $6.25 to $12.25. Close alerts still report R x $12.50. The >25% branch uses about $43 margin, below the $50 minimum rule | report $ from the actual position; use fractional leverage or size by notional |
| B9 | low | scanner.py:489 with _fmt_p (169-174), scan.py:111 | new setup entry is round tripped through text ("Short near $0.000012"): coins under $0.0001 keep 2 significant digits, entry and stop % off by several % | carry the numeric entry in `plan` |
| B10 | info | scanner.py:539 before 700 | Breakdown Short needs a 55d low below the 200d, but such coins usually have RSI < 30, so the falling knife branch returns first; 0 detections in 54 scans (same order in the backtest, so n 74 already reflects it) | if the short is wanted, check it before the falling knife guard and re-validate |
| B11 | info | outcomes.py:107-112, 140 | the partial fire day counts as bar 1 of `max_hold`, one day shorter than the research | count full bars after the fire day |

Not bugs, checked: fills (paper entry = live price at the poll, stop checked before target, gaps fill at the open)
match the backtest's conservative rules; candles for tracking come from the same MEXC perp fallback as the scan;
funding uses OKX (Binance and Bybit refuse US hosts); time exits use the bar close as tested.

## 5. What this means for the fix

1. Judge the system on every fired signal: the honest live record is 0 wins in 32 closed paper longs plus 1 DS
   loss, not 1 in 7.
2. Momentum longs: the failure was regime plus clustering. Any long setup needs a regime filter that reacts to
   breadth *falling* (95% to 54% in two weeks was the warning), a cap on same direction arms per day, and an event
   entry rather than a state label.
3. DS: do not size it up on the strength of the current validation file. Fix B2 and B3, re-validate on the live
   exit and live entry timing (00:05 only), require `ret120 >= 0.5 or close > sma200` (drop the lagging
   `sma50 > sma200` only path) and test the OI filter out of sample. Treat simultaneous DS signals as one position.

## 6. Reproduce

```
export FORENSICS_CACHE=/path/to/cache            # put track_export.json here
python research/live_forensics.py fetch          # ~2 min, MEXC perp 1d (500) + 1h (1000) via utils.exchange
python research/live_forensics.py funding        # OKX funding history
python research/live_forensics.py replay         # ledger era config; --era current for today's config
python research/live_forensics.py diagnose       # per trade table, over_cap resim, DS anatomy, OI, correlation
```
Outputs: `replay_<era>.pkl` (all trigger rows, scan log, short candidates per slot), `compare_<era>.json`,
`diagnose.pkl`, `diagnose_extra.json`.
