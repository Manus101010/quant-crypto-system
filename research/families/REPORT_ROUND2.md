# Round 2: other trade types (8 Oct 2026)

Research only; nothing is imported by the live scanner. Same costs and honesty
rules as round 1. Raw tables are in `results/`.

## Summary

| Study | Verdict | Key numbers |
|---|---|---|
| Grid bots on 5-minute paths | No mechanical rule makes money | neutral weekly bots lose at almost every width and grid count |
| More grids (same range) | Lower profit, slightly more liquidation | ±2.5 ATR, hold, 3x: 10 grids −2.6%/week, 30 −2.9%, 60 −3.4%, 100 −4.1% |
| Weekend vs weekday grids | Weekend less bad, not profitable | ±2.5 ATR 30 grids, 2 days, 3x: weekend +0.0% (71% win) vs weekday −0.3% |
| Grid as execution for passing setups | Plain short wins | bounce fade: plain short +2.92% (81% win) vs short grid +0.61%, n 27 |
| Pairs mean reversion | Fails | best variant PF 0.99, −0.02% per trade (n 365) |
| Trend following, majors basket | Works, long/flat only | 200 SMA filter: CAGR +70.0%, max DD −45.4%, Sharpe 1.33 vs buy and hold +60.1%, −85.5%, 1.02 |
| Cross-sectional momentum | Only BTC-gated, very bumpy | 84d L/S when BTC > 200 SMA: CAGR +43.3%, max DD −71.3%; ungated and reversal books lose |
| Session / weekday returns | Nothing significant | largest |t| ≈ 1.4 once coins' co-movement is accounted for |
| Funding carry | Not worth it at $500 | liquid coins: best +7.6% a year ($38.14 on $500); the +48.4% "all coins" figure is illusory |

## 1. Grid bots (5-minute paths)

25 most liquid MEXC coins, Apr to Oct 2026, a new bot every 7 days on every coin,
0.02% per fill, liquidation modelled at 1% maintenance. Returns are % of margin
per bot run (a week). Full grid in `results/grids_5m.md`.

* **Neutral bots lose in this window at every width.** Narrow ±1 ATR with 10 grids
  and a stop at the edge was the only positive cell (+0.3%/week at 3x, 42% win).
  Win rates of 55 to 70% hide the problem: many small wins, then trends take a
  big bite.
* **Grid count.** At a fixed range, more grids means more fills but LESS profit
  after fees, because each unit only earns one (smaller) spacing per swing and
  fees scale with fills. Liquidation risk rises a little with grid count
  (±1 ATR, hold, 10x: 13% of runs liquidated with 10 grids, 16% with 100).
* **Leverage.** In "hold at the edges" mode, 10x liquidated 6 to 16% of weekly
  runs. Stopping at the edge almost eliminates liquidation (0 to 1%).
* **Filters.** High-volatility deployment was the least bad (±5 ATR, 30 grids,
  3x: −1.3%/week). Quiet chop and BTC-neutral filters were worse.
* **Long grids** made money (+2.0%/week at 3x, ±2.5 ATR, 30 grids) only because
  alts rose in the second half (−1.3% first half, +5.3% second): that is market
  direction, not grid edge. **Short grids** were the worst (−6.4%/week, 7%
  liquidated at 3x).
* **Weekend bots** beat weekday bots in every pairing by 0.3 to 0.9 points per
  2-day run at 3x, but the best was still only breakeven.

What this does NOT say: that your discretionary grids can't work. Picking the
range by eye (support and resistance, news, a coin you know is ranging) is
exactly what a mechanical rule can't copy, and this window was a weak, trendy
period for alts.

## 2. Pairs mean reversion

Walk-forward pair selection every 90 days (correlation and half-life), trade the
next 90 days. 365 to 716 trades per variant; none passes (PF 0.85 to 0.99).

## 3. Trend following on the majors

| | CAGR | max drawdown | Sharpe |
|---|---|---|---|
| BTC + ETH + SOL buy and hold | +60.1% | −85.5% | 1.02 |
| Same basket, long only above the 200 SMA | +70.0% | −45.4% | 1.33 |
| Same basket, Donchian 55/20 long only | +58.2% | −42.3% | 1.32 |
| Same basket, 20/100 cross long/short | +13.7% | −77.9% | 0.52 |

Halving the drawdown is the edge; shorting the majors on trend signals hurts.
On BTC alone the 200 SMA filter roughly matched buy and hold (Sharpe 0.61 vs 0.60);
most of the gain came from ETH and SOL.

## 4. Cross-sectional momentum

Weekly top 5 / bottom 5. Short-term reversal loses heavily at every lookback.
Plain momentum loses or breaks even. Only with the BTC 200 SMA gate does it work
(84 days: CAGR +43.3%, Sharpe 0.82, both halves positive), and the −71.3% drawdown
makes it unsuitable as a core strategy.

## 5. Sessions

No hour or weekday has a statistically meaningful return bias once coins'
co-movement is accounted for. Volatility does vary: the US open hours
(14:00 to 16:00 UTC, 1 to 3am Sydney) average a 192 to 203 bp hourly range,
Saturdays 129 bp. Useful for grid spacing, not for direction.

## 6. Funding carry (long spot, short perp)

On every coin, picking the highest funding looks like +38.7 to +48.4% a year.
That is a mirage: the picks were illiquid microcaps (BULLA, LYN, CLO...) and 28.2%
of holding periods saw a 30%+ squeeze that would liquidate a 3x short leg. On
coins with at least $2M daily MEXC volume the best version earned +7.6% a year,
$38.14 on $500, before basis and venue risk.

## What is worth building

1. Round 1's three setups (bounce fade, distribution short, BTC-up breakouts),
   executed as plain positions with stops.
2. A majors trend filter (BTC, ETH, SOL above the 200 SMA) as a slow core sleeve:
   it halved drawdowns over five years.
3. Grids stay discretionary. If you run them: medium to wide ranges, 10 to 30
   grids, a stop at the range edge, 3 to 5x, and prefer weekends and high
   volatility over quiet chop.
