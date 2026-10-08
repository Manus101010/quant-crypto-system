# Intraday overextension short — Bybit USDT perps

Coins with pump episodes: 769 · episodes: 37615 · 1R = $12.50 · costs 0.36% + real funding.

Tests counted (prior leaderboard + these): 38 → t-stat needed: 3.21

## Variants (target = 4h EMA20, 48h time stop)

| variant | trades | win | PF | avg R | total R | total $ | max DD (R) | t |
|---|---|---|---|---|---|---|---|---|
| core: 3 ATR above 4h+1h EMA20 | 14833 | 49% | 0.76 | -0.120 | -1781.1 | $-22,264 | -1961.3 | -14.20 |
| core: 3 ATR above 4h+1h EMA20 + BTC turning | 7518 | 57% | 0.83 | -0.065 | -487.3 | $-6,091 | -544.7 | -6.58 |
| z-score: 24h gain z>=3 | 7623 | 46% | 0.80 | -0.108 | -823.6 | $-10,295 | -913.6 | -8.75 |
| z-score: 24h gain z>=3 + BTC turning | 5691 | 54% | 0.90 | -0.042 | -239.4 | $-2,992 | -288.6 | -3.35 |
| NFI: 4h RSI>=80, 1h RSI3 turns | 4241 | 41% | 0.67 | -0.202 | -855.4 | $-10,692 | -933.9 | -11.69 |
| NFI: 4h RSI>=80, 1h RSI3 turns + BTC turning | 2917 | 49% | 0.82 | -0.088 | -258.1 | $-3,226 | -368.5 | -4.63 |
| volume climax 8x + 30%/24h | 1079 | 57% | 1.15 | +0.059 | +63.8 | $+797 | -14.6 | 2.07 |
| volume climax 8x + 30%/24h + BTC turning | 599 | 59% | 1.07 | +0.024 | +14.6 | $+182 | -17.7 | 0.69 |
| overleverage: OI +30%, funding>0 | 2039 | 47% | 0.99 | -0.006 | -11.9 | $-149 | -76.1 | -0.21 |
| overleverage: OI +30%, funding>0 + BTC turning | 1103 | 52% | 1.14 | +0.066 | +72.5 | $+906 | -32.6 | 1.72 |
| freqtrade: BB+RSI80 fade | 12050 | 46% | 0.80 | -0.110 | -1323.0 | $-16,537 | -1613.1 | -10.48 |
| freqtrade: BB+RSI80 fade + BTC turning | 7111 | 54% | 0.90 | -0.043 | -308.4 | $-3,855 | -384.9 | -3.75 |

## Baselines vs the best variant (overleverage: OI +30%, funding>0 + BTC turning)

| variant | trades | win | PF | avg R | total R | total $ | max DD (R) | t |
|---|---|---|---|---|---|---|---|---|
| best variant | 1103 | 52% | 1.14 | +0.066 | +72.5 | $+906 | -32.6 | 1.72 |
| A: random entry in the same pump windows | 20074 | 39% | 0.53 | -0.354 | -7105.4 | $-88,818 | -7120.7 | -31.73 |
| B: short as soon as overextended (no turn) | 2590 | 43% | 0.83 | -0.105 | -272.9 | $-3,411 | -319.0 | -3.49 |

## Exit variants for the best setup

| variant | trades | win | PF | avg R | total R | total $ | max DD (R) | t |
|---|---|---|---|---|---|---|---|---|
| target 4h EMA20, 48h | 1103 | 52% | 1.14 | +0.066 | +72.5 | $+906 | -32.6 | 1.72 |
| target 4h EMA20, 24h | 1103 | 51% | 1.02 | +0.009 | +10.4 | $+129 | -33.7 | 0.27 |
| target 1h EMA50, 48h | 1077 | 53% | 1.07 | +0.034 | +36.3 | $+453 | -32.2 | 0.92 |
| trailing 2xATR(1h), 48h | 1445 | 37% | 0.91 | -0.033 | -47.1 | $-589 | -73.3 | -1.20 |

## Best variant split

| variant | trades | win | PF | avg R | total R | total $ | max DD (R) | t |
|---|---|---|---|---|---|---|---|---|
| liquid (20d vol >= $2M) | 555 | 49% | 1.16 | +0.081 | +45.2 | $+565 | -23.2 | 1.40 |
| small (< $2M) | 548 | 54% | 1.11 | +0.050 | +27.3 | $+341 | -22.2 | 1.01 |
| BTC trending up (daily > 50d) | 622 | 51% | 1.15 | +0.074 | +46.3 | $+579 | -28.3 | 1.45 |
| BTC trending down | 481 | 52% | 1.12 | +0.054 | +26.2 | $+327 | -45.4 | 0.95 |
| BTC turning over at entry | 1103 | 52% | 1.14 | +0.066 | +72.5 | $+906 | -32.6 | 1.72 |
| BTC not turning | 0 | | | | | | | |
| year 2025 | 607 | 52% | 1.18 | +0.085 | +51.7 | $+646 | -32.6 | 1.66 |
| year 2026 | 496 | 51% | 1.09 | +0.042 | +20.8 | $+260 | -24.1 | 0.74 |
| first half | 550 | 51% | 1.12 | +0.060 | +33.0 | $+412 | -32.6 | 1.12 |
| second half | 553 | 52% | 1.15 | +0.071 | +39.5 | $+494 | -24.1 | 1.32 |

Average funding effect per trade: -0.014 R (negative = shorts paid).


## Biggest pumps in the data and what the best setup did

| coin | 24h gain | when (UTC) | setup trade |
|---|---|---|---|
| MMT | +831% | 2025-11-04 23:00 | no trade |
| COAI | +660% | 2025-10-06 13:00 | no trade |
| BLESS | +588% | 2025-10-15 22:00 | no trade |
| TAIKO | +546% | 2026-07-02 00:00 | no trade |
| LSK | +480% | 2026-09-13 04:00 | short 0.1126 → stop 0.11766 = -1.08R |
| LIGHT | +454% | 2026-01-01 09:00 | no trade |
| HYPER | +430% | 2025-07-11 02:00 | no trade |
| TNSR | +400% | 2025-11-20 13:00 | short 0.04168 → stop 0.044246 = -1.06R |
| TRUST | +387% | 2025-11-22 02:00 | no trade |
| LAB | +375% | 2026-05-02 17:00 | no trade |
| SKR | +372% | 2026-01-22 03:00 | no trade |
| BTR | +352% | 2026-08-26 20:00 | no trade |
| STO | +348% | 2026-04-02 09:00 | no trade |
| AKE | +342% | 2026-07-15 15:00 | no trade |
| SIREN | +323% | 2026-04-04 22:00 | no trade |
| OGN | +118% | 2026-10-08 19:00 | no trade |
| ORCA | +114% | 2025-03-21 14:00 | short 2.518 → stop 2.7167 = -1.05R; short 2.518 → stop 2.7167 = -1.05R |

**Verdict for the best variant: FAIL** (needs n ≥ 50, PF > 1, avg R > 0, t ≥ 3.21; best t = 1.72).

## Re-entry after a stop (up to 3 tries per pump)

Added after looking at ORCA: every variant shorted ORCA's dips on the way UP
(1.92 on 4 Oct, 2.35 and 2.53–2.60 on 6 Oct), was stopped out each time as it
kept ripping to 3.34, and the one-trade-per-pump rule then gave no second shot
at the real top. Allowing retries does not fix it:

| variant | trades | win | PF | avg R | total R | total $ | max DD (R) | t |
|---|---|---|---|---|---|---|---|---|
| core · up to 3 tries | 19450 | 48% | 0.76 | -0.122 | -2366.7 | $-29,584 | -2580.4 | -16.41 |
| core · up to 3 tries + BTC turning | 8533 | 57% | 0.84 | -0.060 | -511.8 | $-6,397 | -565.4 | -6.45 |
| ↳ 1st attempts only | 7677 | 57% | 0.83 | -0.063 | -484.8 | $-6,060 | -541.0 | -6.53 |
| ↳ 2nd attempts only | 773 | 56% | 0.92 | -0.033 | -25.6 | $-320 | -46.8 | -0.96 |
| ↳ 3rd attempts only | 83 | 57% | 0.96 | -0.016 | -1.3 | $-17 | -10.5 | -0.15 |
| volume climax · up to 3 tries | 1178 | 57% | 1.14 | +0.055 | +64.3 | $+804 | -16.4 | 1.99 |
| volume climax · up to 3 tries + BTC turning | 626 | 60% | 1.07 | +0.025 | +15.4 | $+193 | -17.3 | 0.72 |
| overleverage · up to 3 tries | 3025 | 44% | 1.02 | +0.014 | +41.9 | $+524 | -76.9 | 0.56 |
| overleverage · up to 3 tries + BTC turning | 1432 | 47% | 1.00 | +0.000 | +0.4 | $+5 | -58.7 | 0.01 |

## ORCA (6–7 Oct 2026) and OGN (8 Oct 2026)

- ORCA: shorts at 1.92 (4 Oct), 2.35 (6 Oct 03:00), 2.53–2.60 (6 Oct) — all
  stopped out (−1.05R each) as ORCA ran to 3.34. No qualifying signal at the
  actual top before the 3.34 → 2.27 drop.
- OGN: shorted at 0.0221 on 5 Oct (before the +118% day), small win (+0.27R);
  no qualifying signal at the 0.054 top.

## Verdict in plain terms

**No edge. The Overextension Short is not built.**

- Shorting coins that are stretched far above their averages, even after the
  15m/1h roll-over, lost money in every main version: the core setup lost about
  $22,000 across 14,833 trades ($12.50 risked each); with BTC also turning it
  still lost about $6,100 across 7,518 trades.
- The best version (OI up 30% + funding positive + BTC turning) made +$906 over
  1,103 trades — about 82 cents per trade — and is not statistically
  distinguishable from luck (t = 1.72; 3.21 needed after 38 tests).
- What did hold up: waiting for the turn and for BTC to turn over both help a
  lot (random shorts in the same pumps lost $88,800; shorting the moment a coin
  looked overextended lost $3,400). They just don't help enough to make money.
- Why: these pumps very often make one more leg higher after the first
  roll-over, so the stop above the swing high gets hit (ORCA did exactly this
  three times). Funding cost was small on average (−0.014R per trade).

The "do not chase" guard IS built (see utils/overext.py and monitor.py): the
same data shows buying stretched coins is what gets traders liquidated.
