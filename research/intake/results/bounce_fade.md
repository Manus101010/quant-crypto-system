# Downtrend bounce fade (short)

Source: research/families/REPORT.md, round 1

Hypothesis: Relief rallies in downtrending coins are driven by short covering, not new demand; once volatility fades, sellers return.

Coins: 520. Tiered costs (0.36% liquid, 0.80% under $2M a day). Strategies tested so far incl. this: 4, so t-stat needed = 2.50.

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | t | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| Z=2.0, S=2.5 | 713 | 1.28 | 69% | +0.052 | +37 | -58 | 1.11 | 1.51 | 1.69 | WATCH |
| Z=2.5, S=2.5 | 520 | 1.35 | 71% | +0.052 | +27 | -40 | 1.05 | 1.73 | 1.61 | WATCH |
| Z=2.0, S=3.0 | 556 | 1.33 | 71% | +0.052 | +29 | -49 | 1.12 | 1.58 | 1.70 | WATCH |
| Z=3.0, S=2.5 | 348 | 1.32 | 72% | +0.044 | +15 | -23 | 1.20 | 1.46 | 1.37 | WATCH |

## Best variant (Z=2.0, S=2.5) split by context

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC MIXED | 713 | 1.28 | 69% | +0.052 | +37 | -58 | 1.11 | 1.51 | PASS |
| liquid (>= $2M/day) | 415 | 1.63 | 72% | +0.099 | +41 | -38 | 1.19 | 2.39 | PASS |
| small cap (< $2M/day) | 298 | 0.89 | 66% | -0.013 | -4 | -20 | 1.07 | 0.76 | fail |
| excluding crowded days (> 3 signals) | 279 | 1.28 | 68% | +0.026 | +7 | -13 | 1.17 | 1.41 | PASS |

By year: 2021: n7 PF 0.39 expR -0.48 · 2022: n47 PF 1.69 expR +0.22 · 2023: n86 PF 0.20 expR -0.64 · 2024: n70 PF 2.96 expR +0.43 · 2025: n226 PF 2.26 expR +0.22 · 2026: n277 PF 1.21 expR +0.02
