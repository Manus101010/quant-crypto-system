# Distribution short (coil after a run-up)

Source: research/families/REPORT.md, round 1

Hypothesis: After a strong run, a tight range with price slipping to its lower half is supply absorbing demand; the next expansion tends to be down.

Coins: 520. Tiered costs (0.36% liquid, 0.80% under $2M a day). Strategies tested so far incl. this: 8, so t-stat needed = 2.73.

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | t | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| P=0.1, M=trail | 669 | 2.24 | 57% | +0.366 | +245 | -79 | 1.30 | 3.56 | 8.59 | CANDIDATE |
| P=0.2, M=trail | 931 | 1.96 | 54% | +0.280 | +260 | -129 | 0.96 | 3.50 | 8.02 | REJECT |
| P=0.1, M=struct | 688 | 2.19 | 54% | +0.325 | +223 | -80 | 1.24 | 3.59 | 7.72 | CANDIDATE |
| P=0.15, M=trail | 817 | 2.22 | 55% | +0.337 | +276 | -108 | 1.18 | 3.84 | 8.94 | CANDIDATE |

## Best variant (P=0.1, M=trail) split by context

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC MIXED | 315 | 1.78 | 56% | +0.265 | +83 | -35 | 1.40 | 2.17 | PASS |
| BTC UP | 354 | 2.70 | 58% | +0.457 | +162 | -45 | 1.17 | 5.85 | PASS |
| liquid (>= $2M/day) | 422 | 2.31 | 58% | +0.360 | +152 | -40 | 1.32 | 3.67 | PASS |
| small cap (< $2M/day) | 247 | 2.12 | 55% | +0.378 | +93 | -40 | 1.51 | 2.92 | PASS |
| excluding crowded days (> 3 signals) | 380 | 1.64 | 51% | +0.216 | +82 | -36 | 1.26 | 2.05 | PASS |

By year: 2021: n57 PF 2.07 expR +0.37 · 2022: n6 PF 12.59 expR +0.87 · 2023: n115 PF 1.51 expR +0.24 · 2024: n161 PF 1.03 expR -0.09 · 2025: n275 PF 5.40 expR +0.83 · 2026: n55 PF 0.32 expR -0.41
