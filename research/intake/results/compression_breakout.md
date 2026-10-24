# Compression breakout long (BTC up only)

Source: research/families/REPORT.md, round 1

Hypothesis: Coins basing after a decline break out hard once the market turns, because sidelined buyers return at the same time; in a weak market the same breakouts fail.

Coins: 520. Tiered costs (0.36% liquid, 0.80% under $2M a day). Strategies tested so far incl. this: 12, so t-stat needed = 2.87.

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | t | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| P=0.1, V=1.5 | 401 | 1.06 | 32% | +0.071 | +29 | -77 | 1.03 | 1.09 | 0.71 | WATCH |
| P=0.2, V=1.5 | 572 | 0.95 | 29% | -0.021 | -12 | -103 | 0.83 | 1.08 | -0.25 | REJECT |
| P=0.1, V=2.0 | 316 | 0.95 | 30% | -0.007 | -2 | -58 | 1.05 | 0.86 | -0.07 | REJECT |
| P=0.15, V=1.5 | 483 | 0.98 | 29% | -0.010 | -5 | -90 | 0.87 | 1.11 | -0.11 | REJECT |

## Best variant (P=0.1, V=1.5) split by context

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC UP | 401 | 1.06 | 32% | +0.071 | +29 | -77 | 1.03 | 1.09 | PASS |
| liquid (>= $2M/day) | 200 | 0.97 | 30% | +0.145 | +29 | -51 | 0.54 | 1.46 | fail |
| small cap (< $2M/day) | 201 | 1.16 | 33% | -0.002 | -0 | -30 | 1.57 | 0.78 | fail |
| excluding crowded days (> 3 signals) | 162 | 0.79 | 25% | -0.244 | -40 | -60 | 0.49 | 1.07 | fail |

By year: 2021: n22 PF 0.91 expR -0.43 · 2023: n46 PF 0.10 expR -0.77 · 2024: n93 PF 1.24 expR +0.11 · 2025: n221 PF 1.18 expR +0.26 · 2026: n19 PF 1.76 expR +0.24
