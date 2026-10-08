# Hype ignition long (volume + volatility expansion)

Source: Manus: enter small caps showing hype, volume and volatility expansion

Hypothesis: Attention shocks on thin coins are under-reacted to on day one; late buyers keep arriving for days, so momentum continues after the ignition bar.

Coins: 562. Tiered costs (0.36% liquid, 0.80% under $2M a day). Strategies tested so far incl. this: 17, so t-stat needed = 2.97.

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | t | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| vol=3.0, rng=1.5, cap=any | 1766 | 0.94 | 29% | -0.023 | -41 | -120 | 1.02 | 0.87 | -0.51 | REJECT |
| vol=5.0, rng=1.5, cap=any | 989 | 1.03 | 29% | +0.021 | +20 | -55 | 1.05 | 1.01 | 0.32 | WATCH |
| vol=3.0, rng=2.0, cap=any | 1599 | 0.97 | 29% | -0.003 | -5 | -101 | 1.07 | 0.88 | -0.07 | REJECT |
| vol=3.0, rng=1.5, cap=small | 1369 | 0.96 | 28% | -0.019 | -26 | -119 | 1.12 | 0.84 | -0.36 | REJECT |
| vol=5.0, rng=2.0, cap=small | 784 | 1.03 | 28% | +0.007 | +6 | -62 | 1.07 | 0.99 | 0.10 | REJECT |

## Best variant (vol=5.0, rng=1.5, cap=any) split by context

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 170 | 0.63 | 24% | -0.277 | -47 | -57 | 0.72 | 0.56 | fail |
| BTC MIXED | 441 | 1.18 | 28% | +0.087 | +38 | -52 | 0.90 | 1.42 | fail |
| BTC UP | 378 | 1.07 | 32% | +0.077 | +29 | -25 | 1.06 | 1.08 | PASS |
| liquid (>= $2M/day) | 515 | 1.09 | 30% | +0.060 | +31 | -39 | 1.06 | 1.10 | PASS |
| small cap (< $2M/day) | 474 | 0.96 | 27% | -0.022 | -11 | -61 | 1.15 | 0.82 | fail |
| excluding crowded days (> 3 signals) | 897 | 1.05 | 30% | +0.044 | +39 | -54 | 1.06 | 1.04 | PASS |

By year: 2020: n3 PF 1.29 expR +0.01 · 2021: n18 PF 1.84 expR +0.52 · 2022: n46 PF 1.03 expR +0.05 · 2023: n170 PF 0.92 expR -0.07 · 2024: n217 PF 1.19 expR +0.08 · 2025: n224 PF 1.05 expR +0.05 · 2026: n311 PF 0.92 expR -0.03
