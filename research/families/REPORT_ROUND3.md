# Round 3: full MEXC futures universe, small caps, and the intake pipeline (8 Oct 2026)

Research only. Universe: every active MEXC USDT crypto perpetual (606 listed,
577 with 30+ days of history; tokenised stocks, ETFs, indices and commodities
excluded), daily perp candles. Every strategy now runs through
`research/intake/run.py` with tiered costs (0.36% round trip for coins trading
$2M+ a day, 0.80% below that) and a multiple-testing bar that rises with every
idea tested. Leaderboard: `research/intake/leaderboard.csv`.

| Strategy | Verdict | Key numbers (best variant) |
|---|---|---|
| Distribution short | **CANDIDATE** | n 669, PF 2.24, +0.366R, t 8.59 (needed 2.73). Works on small caps too: n 247, PF 2.12, +0.378R |
| Downtrend bounce fade | WATCH | n 713, PF 1.28, +0.052R. Liquid coins only: n 415, PF 1.63, +0.099R; small caps fail (PF 0.89) |
| Post-hype fade short (taper) | WATCH | n 1403, PF 1.11, +0.046R. Liquid: PF 1.23, +0.075R; small caps: PF 0.80, −0.039R; disappears without crowded days |
| Compression breakout (BTC up) | REJECT on the full universe | PF 1.06, +0.071R; did not hold beyond the 219 most liquid coins |
| Hype ignition long | REJECT | PF 0.94 to 1.03, about zero expectancy at every setting |

Small caps at lower costs (0.36% instead of 0.80%): hype fade, bounce fade and
hype ignition all stay at or below breakeven, and are worse in the recent half.

## Read with care

* **Survivorship hurts the small-cap short results.** Coins that pumped, faded
  and were delisted are missing from the data. Those would have been some of the
  best shorts, so the true small-cap short edge is probably better than shown.
* **2026 is weak for shorts so far.** Distribution short 2026: n 55, PF 0.32,
  −0.41R; post-hype fade 2026: PF 0.67. Most of the edge came in 2025.
* The live scanner currently scans MEXC *spot* pairs. Covering every futures coin
  means switching its universe to the perp list (`research/families/fetch_perps.py`
  shows the filter).

## Strategy intake pipeline

From Miles Deutscher's process, minus the traps: `research/intake/README.md` and
the `strategy-intake` Claude Code skill turn a Pine script or link into a
`research/strategies/<slug>.py` module and test it on the whole universe. The
t-stat needed rose from 2.50 to 3.05 across the 22 variants tested today.
