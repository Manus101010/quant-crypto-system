# Futures grid backtest (night run, 2026-10-27)

**Verdict: no grid configuration passes the edge gate.** 1,440 configs were tried, and 0 pass (PF > 1, n >= 25, profitable in both halves). 0 are robust. Walk forward also failed: every strategy's best first-half pick lost money in the second half. The scanner should not present grid bots as edge-gated trades.

## What was built

| file | what |
|---|---|
| `research/grid/sim.py` | Event-driven Bybit USDT-perp futures grid simulator. It has a numba kernel plus a batch kernel for the sweep. |
| `research/grid/data.py` | MEXC USDT-perp 5m candles and MEXC funding history. Output is cached in `research/grid/cache/` (gitignored). |
| `research/grid/run.py` | Strategy sweep, edge gate, neighbour robustness check and walk forward. |
| `research/grid/check_1m.py` | Measures how far 5m OHLC understates grid fills compared with 1m (OKX 1m, last 30 days). |
| `research/grid/trader_style.py` | The trader's own style: ±20 to 25% range, 200 grids, 5x, run with and without the 25% stop rule. |
| `tests/test_grid_sim.py` | 14 offline tests. They cover oscillation profit = crossings × step − fees, the worst case through the stop, liquidation price, gap fills, funding, the time cap, batch = single run, pre-trade rejections, and the kernel against an independent brute-force order book in all 3 modes. |
| `research/grid/results/` | `grid_sweep.csv` (one row per config, all metrics), `walk_forward.csv`, `meta.json`, `check_1m.csv`, `trader_style.csv` |

Reproduce: `python research/grid/data.py 40 30`, then `python research/grid/run.py`. The download took about 10 min and the sweep about 34 min on 2 cores. numba must be installed (`pip install numba`). It is not in requirements.txt.

## Method

**Data.** MEXC USDT perps, 5m, from 2025-11-01 to 2026-10-26. That is the deepest 5m history the MEXC public API returns: about 103,600 bars per coin. The universe has 70 coins: the top 40 Bybit perps by MEXC 24h volume, 30 small caps taken evenly from volume ranks 150 to 350, and DOOD. Funding is MEXC's real settlement history, applied at the 5m bar of each settlement. Bybit returns 403 from here, so MEXC prices stand in for Bybit. ccxt has to be given `httpsProxy` explicitly in this sandbox.

**Simulator assumptions (Bybit futures grid semantics)**
- N grids means N intervals between N+1 lines, arithmetic in this sweep (geometric is supported). Every slot trades the same quantity q.
- Long grid: at creation it market-buys every slot above the start price, so it is fully long at the bottom and flat at the top. Short grid is the mirror image. Neutral grid has no initial position: it goes long below the start price and short above it.
- q is set so the notional of all the bot's orders equals investment × leverage. For a long or short grid, that is the fully filled position held at the stop. For a neutral grid, the two sides share it.
- Fees and slippage:
  - Grid fills are maker, 0.02%, at the line price.
  - The opening market order, the time-cap close, the stop and the profitable-side exit are taker, 0.055%, plus 0.05% adverse slippage.
- Funding is charged on the open position: longs pay positive rates.
- Isolated margin, maintenance margin rate 0.5%. Liquidation loses the whole investment, which is conservative.
- The stop sits 0.2% beyond the range edge on the losing side. The Bybit app rejects a stop inside the range. A neutral grid has a stop on both sides. A directional grid also closes when price leaves the range on its profitable side, because it is flat there and has nothing left to earn.
- Intrabar path: an up candle goes O→L→H→C, a down candle O→H→L→C. Each line crossed in a leg fills once. Stops and liquidation trigger at their exact price, except that a gap fills at the bar open.
- **Bias:** wiggles inside a candle that OHLC does not show are not counted, so grid profit is understated. `check_1m.py` measures the size of this. With wide ranges, 1m earns 0.2 to 6% more grid profit than 5m. With 200 grids on 8 ATR ranges it earns up to 54% more. In expectancy that is at most +0.007R per trade, and it turns no losing family into a winner. Only short 50g/8ATR moves from −0.003R to +0.001R over those 30 days.

**Entry rules.** Signals use closed 1h bars and are acted on at the next 5m open. Only one bot runs per coin at a time.

| strategy | filter → grid |
|---|---|
| neutral_adx / bbw / hurst | ADX(14) < 20, or BB(20) width percentile < 30% (30 days), or Hurst (variance ratio over 7 days) < 0.45 → neutral grid centred on price |
| neutral_always | no filter (control) |
| short_trend / long_trend | close below 4h EMA50 and BTC below its 4h EMA50 → short grid (long is the mirror) |
| short_spike3 / short_spike5 | close > EMA20(1h) + 3 or 5 × ATR(1h) → short grid (the trader's style) |
| short_always / long_always | no filter (controls) |

- Range width = k × ATR(1h). A neutral grid is centred on price. A directional grid starts one third of the way in from the stop edge.
- The sweep covers grids 20/50/100/200, leverage 3/5/10, width 4/8/16/32 ATR, and a time cap of 24/72/168h: 10 × 144 = 1,440 configs.
- Pre-trade rules:
  - With $50 margin, a straight run through the stop must lose at most $12.50 (1R).
  - Liquidation must sit at least 2× the stop distance from entry.
  - The net profit per grid after fees must be above 0.
  - Each config's rejections are counted.

**Evaluation**
- Per trade in R (1R = $12.50): n, PF, win rate, expectancy, max drawdown, both halves (split at 2026-05-04), BTC regime, and top versus small caps.
- Edge gate: PF > 1, n >= 25, profitable in both halves.
- Robust = passes the gate AND every neighbouring config that has n >= 25 (one step in grids, leverage, width or hold) also passes.
- Walk forward: pick the best config per strategy on the first half, then run it unchanged on the second half.

## Results

Totals across 1,440 configs:
- 167.3M signals, 11.86M trades taken.
- Rejected because the stop would lose more than 25%: 125.65M.
- Rejected because the step was too small for fees: 29.77M.
- Rejected for liquidation distance: 0. When the 25% rule holds, liquidation is always far enough away.
- 111 configs had every signal rejected.
- 10 configs reached PF > 1 with n >= 25. **0 passed the gate. 0 were robust.**

### The best configs (every config with PF > 1 and n >= 25 is listed). All fail the gate.

| strategy | grids | lev | width | hold | n | PF | win | exp R | total R | max DD R | PF H1 / H2 | R H1 / H2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| short_spike3 | 20 | 5x | 32 ATR | 72h | 47 | 1.97 | 72% | +0.132 | +6.20 | 2.54 | 0.65 / 2.96 | −0.96 / +7.16 |
| short_spike3 | 50 | 5x | 32 ATR | 72h | 45 | 1.68 | 69% | +0.099 | +4.45 | 2.57 | 0.59 / 2.51 | −1.16 / +5.61 |
| short_spike3 | 100 | 5x | 32 ATR | 72h | 44 | 1.48 | 68% | +0.073 | +3.22 | 2.63 | 0.53 / 2.21 | −1.38 / +4.61 |
| short_spike3 | 200 | 5x | 32 ATR | 72h | 44 | 1.29 | 66% | +0.047 | +2.05 | 2.70 | 0.46 / 1.94 | −1.69 / +3.74 |
| short_spike3 | 20 | 5x | 32 ATR | 168h | 46 | 1.19 | 59% | +0.048 | +2.22 | 4.09 | 0.29 / 1.97 | −3.89 / +6.12 |
| short_spike3 | 50 | 5x | 32 ATR | 168h | 44 | 1.11 | 59% | +0.029 | +1.29 | 3.64 | 0.26 / 1.97 | −4.23 / +5.52 |
| short_trend | 20 | 5x | 32 ATR | 72h | 304 | 1.05 | 60% | +0.009 | +2.82 | 14.62 | 0.80 / 1.27 | −5.27 / +8.09 |
| short_spike3 | 20 | 5x | 32 ATR | 24h | 50 | 1.03 | 60% | +0.003 | +0.16 | 2.87 | 2.69 / 0.84 | +0.84 / −0.68 |
| short_spike3 | 50 | 5x | 32 ATR | 24h | 48 | 1.01 | 60% | +0.001 | +0.06 | 2.92 | 2.52 / 0.82 | +0.79 / −0.73 |
| short_trend | 20 | 3x | 32 ATR | 72h | 1,820 | 1.01 | 58% | +0.001 | +2.25 | 60.56 | 0.98 / 1.04 | −3.57 / +5.83 |

The PF 1.97 row looks good, but it is not an edge:
- The 25% rule rejected 7,511 of its 7,558 signals. Only coins whose 32 ATR range happened to be narrow (about 14.5%) got through.
- 13 trades fell in the first half (PF 0.65) and 34 in the second.
- Its 3x neighbour has n = 346 and PF 0.75.

### Honest failures (best config per family by expectancy)

| family | best config | n | PF | exp R | PF H1 / H2 |
|---|---|---|---|---|---|
| neutral_always | 20g 3x 32ATR 24h | 21,177 | 0.83 | −0.003 | 0.85 / 0.82 |
| neutral_adx | 20g 3x 32ATR 24h | 11,407 | 0.80 | −0.003 | 0.84 / 0.76 |
| neutral_bbw | 20g 3x 32ATR 24h | 12,942 | 0.79 | −0.004 | 0.79 / 0.79 |
| neutral_hurst | 20g 3x 32ATR 24h | 10,595 | 0.77 | −0.004 | 0.81 / 0.74 |
| short_always | 20g 3x 32ATR 72h | 3,023 | 0.96 | −0.006 | 0.97 / 0.96 |
| long_always | 20g 10x 32ATR 24h | 30 | 0.94 | −0.007 | 0.16 / 1.83 |
| long_trend | 20g 5x 32ATR 168h | 166 | 0.92 | −0.021 | 1.52 / 0.64 |
| short_spike5 | 20g 3x 8ATR 24h | 309 | 0.85 | −0.038 | 1.45 / 0.55 |

**Walk forward (pick on H1, apply to H2 unchanged)**

| strategy | H1 pick | H1 result | H2 result |
|---|---|---|---|
| short_trend | 20g/3x/16ATR/72h | PF 1.07, +0.014R | PF 0.92, −0.017R, −39.6R total |
| long_trend | 20g/5x/32ATR/168h | PF 1.52 | PF 0.64, −11.3R |
| short_spike5 | 20g/3x/8ATR/168h | PF 1.47 | PF 0.52, −27.0R |
| short_always | 20g/3x/16ATR/168h | PF 1.06 | PF 0.82, −150.2R |

The other six strategies had no H1 config with PF > 1.

### What the sweep says about parameters (medians across configs)
- **Grid count: more grids is worse.** Median PF: 20 grids 0.72, 50 grids 0.55, 100 grids 0.41, 200 grids 0.30.
  - Grid profit does not scale with count. A 5m bar visits the same lines however finely you cut the range, while maker fees and the cost of opening at market do scale.
  - 200 grids on ranges of 8 ATR or less are also mostly rejected because the step is below the round-trip fee (37% of 200-grid signals).
- **Leverage: more is worse.** Median PF: 3x 0.57, 5x 0.52, 10x 0.45. The 25% rule rejects 42% of signals at 3x, 57% at 5x and 76% at 10x.
- **Range width: wider is less bad.** Median PF: 4 ATR 0.38, 8 ATR 0.51, 16 ATR 0.61, 32 ATR 0.66. Narrow grids get stopped out. About 85 to 99% of 4 ATR trades end at a range edge.
- **Regime filters add nothing to neutral grids.** ADX, BBW and Hurst score within ±0.03 PF of the unfiltered control. Neutral grids are the worst family: every range exit pays a taker close on a position that has run against the bot.
- **Direction:** short grids (median PF 0.67 to 0.69) beat long grids (0.62 to 0.64) and neutral (0.30 to 0.34). Short grids did better when BTC was below its 4h EMA50: in short_always 20g/3x/32ATR/72h, PF was 1.16 with BTC down and 0.81 with BTC up. That points at regime, not at grids.

### The trader's own style (`trader_style.csv`)
Setup: range −20% / +25% around price, 200 grids, $50, held up to 7 days, one bot per coin.

| entry | lev | n | PF | win | exp $ | worst $ | PF H1 / H2 | stopped |
|---|---|---|---|---|---|---|---|---|
| short after spike (3 ATR) | 5x | 1,828 | 0.51 | 62% | −4.88 | −50.00 | 0.63 / 0.44 | 37% |
| short, no filter | 5x | 4,289 | 0.56 | 61% | −3.89 | −50.00 | 0.70 / 0.46 | 34% |
| short, no filter, 50 grids | 5x | 4,289 | 0.78 | 64% | −1.78 | −47.15 | 0.97 / 0.64 | 34% |
| neutral, no filter | 5x | 4,289 | 0.21 | 48% | −3.53 | −19.13 | 0.26 / 0.18 | 34% |

- At 5x, a straight run through the stop costs $43.07 of the $50 margin. The 25% rule rejects **every** one of these setups. At 10x, the liquidation rule rejects all of them as well.
- These bots win about 61% of the time with small gains, then lose most of the margin in roughly a third of runs. The "$100 to $2,000" track record fits that profile: a long run of wins that had not yet met its stop-outs.
- **Reviewer re-checks (docs/night/review.md):**
  - The kernel matches two independent re-implementations: a hand-coded order book on real DOOD bars, and a ∫pos·dx integral on a synthetic lattice. Both agree to 1e-12.
  - Removing the stop does not rescue the style. Short, no filter, 5x/200g, 7d cap, no stop: PF 0.54, 14% of runs liquidated. With no stop and no time cap: PF 0.47, 40% liquidated.
  - Removing the 7d cap alone gives PF 0.50.
  - Measured on the same 8 coins, OKX 1m vs 5m at 200 grids adds about +0.01R per trade.
  - Only the majors (BTC, ETH, SOL and the like, n 674) break even: PF 1.05.
- The figures below assume **$50 invested**. The live bot holds $263.86, which scales the loss about 5.3x. See the reconciliation in review.md: at the app's 75% deploy ratio, a stop at 0.0025125 from entry 0.002096 costs about $148, and from mark 0.00202 about $168 to $223.
- **Live DOODUSDT bot** (short, 5x, 200 grids, 0.0016 to 0.0025, stop just above 0.0025, **$50 investment**):

| opened at | stop-out loss | liquidation | meets 2× liquidation rule? |
|---|---|---|---|
| 0.0020 | $43.07 (86% of margin) | 0.002554, only 2.2% beyond the stop | no |
| 0.0017 | $50 (whole margin) | 0.002456, inside the range | no |

## Recommended default grid rules for the scanner
1. **Do not issue grid plans as edge-gated signals.** No grid configuration has a measured edge. If the scanner shows a grid at all, label it "not edge gated" and size it at 1R maximum, like any unvalidated idea.
2. If the trader runs a grid anyway, use the least-bad family on this data:
   - **short** grid, only with BTC below its 4h EMA50 (or after a 3 ATR spike on the coin);
   - **20 grids** (never 100 or 200);
   - **3x to 5x**;
   - range about **30 ATR(1h)** wide (about 15 to 28% of price), with price one third below the top;
   - stop 0.2% above the top;
   - closed after **72h**, or when price leaves the range.
   - Even this ran at about breakeven: PF 1.01 at 3x (n 1,820, max drawdown 60.6R) and PF 1.05 at 5x (n 304), and it failed the first half.
3. Keep the pre-trade check in the 25% rule (`grid_for_signal` with `margin_usd` / `max_loss_pct` already does this): leverage = the highest level where the fully filled stop-out is at most $12.50. At 5x that limits a short grid to a range about 9% wide; at 3x, about 15%. Wide, high-count, high-leverage bots like the DOOD one should be flagged in the guard as breaking the 25% stop rule.
4. Neutral grids with regime filters should not be offered: PF 0.77 to 0.83 at best.

## Limitations
- One year (2025-11 to 2026-10) on one venue's prices (MEXC, not Bybit). That is one market regime, and survivorship applies: only coins listed today are included.
- 5m OHLC understates grid fills. The 1m check bounds this at +0.007R per trade or less. That cannot close a gap of −0.04 to −0.15R per trade, but tight 200-grid configs are understated the most.
- The range and stop are mechanical (ATR multiples). A discretionary trader placing ranges by eye at support and resistance could do better or worse; that is not testable here.
- Bybit's exact grid order quantity and margin rules (tiered maintenance margin, the minimum order size per grid) are approximated. Liquidation uses a flat 0.5% maintenance margin rate and loses the whole investment.
- "Neighbour" robustness and walk forward are moot because nothing passed.
- A zero-drift synthetic random walk with coarse straight-line steps shows a small fee-free loss for fine grids: −0.26 ± 0.06 USD per trade at 200 grids. The cause is the straight-line path inside each bar. After price touches a line mid-bar, the model keeps it moving the same way until the bar's next extreme. That is momentum, and a mean-reverting grid pays for it. The loss shrinks to −0.035 with 8× finer steps, and the kernel matches an independent brute-force order book to 1e-13. So this is a known conservative bias of OHLC path models, not a bookkeeping bug. The real-data 1m against 5m check above bounds its size.
